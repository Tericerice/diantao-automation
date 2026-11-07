"""走路球体完成：依次点击走路赚元宝的步数档位，领取奖励并完成额外元宝任务。

流程：
首页 → 元宝中心 → 走路赚元宝 → 扫描步数档位
→ 从小到大点击档位 → 出现「领取走路奖励 / 再得XX元宝」弹窗
→ 点击「再得XX元宝」完成浏览/直播任务 → 返回走路页 → 下一个档位

某个档位点击后，确认仍在走路页且没有弹窗，才按累计规则视为灰色/未达成。
页面识别为空或不含走路页标题时视为未知，有限重试，不把网络/OCR 未知当完成。
完成额外元宝任务后若返回识别失败，复用原导航链有限恢复，并把不可恢复故障明确上报。
"""
from __future__ import annotations

import re
import sys
import time

from u2_scanner import (
    DT_APP, classify_media_page, connect_device,
    execute_browse_task, execute_live_task, navigate_chain,
)
from utils import get_ocr_text_blocks


d = connect_device()
screen_width, screen_height = d.window_size()
print(f"屏幕分辨率: {screen_width} x {screen_height}")

TIER_PATTERN = re.compile(r"(\d+)步")
EXTRA_BUTTON_PATTERN = re.compile(r"再得(\d+)元宝")
BROWSE_SECONDS_PATTERN = re.compile(r"浏览(\d+)秒")
POPUP_KEYWORDS = ("领取走路奖励", "放弃领取额外奖励")
MAX_TIERS = 12
DEFAULT_BROWSE_SECONDS = 35
PAGE_UNKNOWN_RETRIES = 2
PAGE_UNKNOWN_WAIT_SECONDS = 2
RETURN_NAVIGATION_RETRIES = 1


def text(block):
    return re.sub(r"[\s​-‍﻿]+", "", str(block.get("text", "")))


def find(blocks, keyword):
    return next((b for b in blocks if keyword in text(b)), None)


def is_walk_page(blocks):
    labels = [text(b) for b in blocks]
    heading = any("走路赚元宝" in t for t in labels)
    context = any(
        "今日已走" in t or "赚步数" in t or TIER_PATTERN.fullmatch(t)
        for t in labels
    )
    return heading and context


def popup_visible(blocks):
    labels = [text(b) for b in blocks]
    return any(k in t for t in labels for k in POPUP_KEYWORDS)


def scan_tiers(blocks):
    """按步数从小到大返回可点击的档位。"""
    tiers = []
    for block in blocks:
        match = TIER_PATTERN.fullmatch(text(block))
        if match:
            tiers.append((int(match.group(1)), block))
    return sorted(tiers, key=lambda item: item[0])


def find_extra_button(blocks):
    for block in blocks:
        if EXTRA_BUTTON_PATTERN.fullmatch(text(block)):
            return block
    return None


def read_walk_page(retries=PAGE_UNKNOWN_RETRIES):
    """返回 (页面文字块, 是否确认在走路页)；空 OCR / 非走路页是未知，不是完成。"""
    for attempt in range(retries + 1):
        blocks = get_ocr_text_blocks(d)
        if is_walk_page(blocks):
            return blocks, True
        if attempt < retries:
            print(f"  ⚠️ 走路页识别未知（第 {attempt + 1} 次），等待后重扫")
            time.sleep(PAGE_UNKNOWN_WAIT_SECONDS)
    return blocks, False


def browse_seconds(blocks, default=DEFAULT_BROWSE_SECONDS):
    for block in blocks:
        match = BROWSE_SECONDS_PATTERN.search(text(block))
        if match:
            seconds = int(match.group(1))
            if 0 < seconds <= 180:
                return seconds
    return default


def navigate_to_walk_page():
    blocks, confirmed = read_walk_page(retries=0)
    if confirmed:
        print("  ✅ 已在走路赚元宝页面")
        return True
    for attempt in range(RETURN_NAVIGATION_RETRIES + 1):
        print("  🧭 启动点淘，导航到【元宝中心 → 走路赚元宝】...")
        d.app_start(DT_APP, stop=True)
        time.sleep(5)
        if not navigate_chain(d, [("元宝中心", "元宝中心"), ("走路赚元宝", "走路赚元宝")]):
            print(f"  ⚠️ 导航未完成（第 {attempt + 1} 次）")
            continue
        time.sleep(3)
        blocks, confirmed = read_walk_page(retries=0)
        if confirmed:
            print("  ✅ 已进入走路赚元宝页面")
            return True
        print(f"  ⚠️ 未识别到走路赚元宝页面（第 {attempt + 1} 次）")
    print("  ⚠️ 无法确认走路赚元宝页面：页面/OCR 未知或导航失败")
    return False


def return_to_walk_page():
    for attempt in range(4):
        d.press("back")
        time.sleep(2)
        blocks, confirmed = read_walk_page(retries=PAGE_UNKNOWN_RETRIES)
        if confirmed and not popup_visible(blocks):
            return True
    return False


def claim_tier(tier_block):
    """处理一个档位；返回 claimed / unavailable / failed。"""
    steps = text(tier_block)
    print(f"\n  🎯 点击档位【{steps}】 @({tier_block['cx']},{tier_block['cy']})")
    d.click(int(tier_block["cx"]), int(tier_block["cy"]))
    time.sleep(2)
    blocks = get_ocr_text_blocks(d)

    if not popup_visible(blocks):
        # 空 OCR / 非走路页是识别未知，不能据此判定灰色档位或业务完成。
        if not blocks or not is_walk_page(blocks):
            print(f"  ⚠️ 【{steps}】点击后页面识别未知，有限重扫后仍无法确认")
            return "unknown"
        print(f"  ⊘ 档位【{steps}】仍在走路页且无领取弹窗，判定为灰色/未达成")
        return "unavailable"

    extra = find_extra_button(blocks)
    if not extra:
        print(f"  ⚠️ 【{steps}】弹窗未找到「再得XX元宝」，只领取主奖励")
        give_up = find(blocks, "放弃领取额外奖励")
        if give_up:
            d.click(int(give_up["cx"]), int(give_up["cy"]))
            time.sleep(2)
        return "claimed"

    print(f"  🎁 点击【{text(extra)}】 @({extra['cx']},{extra['cy']})")
    d.click(int(extra["cx"]), int(extra["cy"]))
    time.sleep(4)
    blocks, _ = read_walk_page(retries=0)
    seconds = browse_seconds(blocks)
    media = classify_media_page(blocks)
    print(f"  🔎 额外任务类型: {media or 'browse'}，目标时长约 {seconds} 秒")

    if media == "live":
        execute_live_task(d, "走路额外元宝", 0, 0, duration=seconds + 5)
    else:
        completed = execute_browse_task(
            d, min_duration=seconds, max_wait=seconds + 40, extra_seconds=10,
        )
        if not completed:
            print("  ⚠️ 浏览任务超时，停止以避免在错误页面继续点击")
            return "failed"

    if not return_to_walk_page():
        print("  ⚠️ 未能返回走路页，尝试放弃额外奖励后继续")
        blocks = get_ocr_text_blocks(d)
        give_up = find(blocks, "放弃领取额外奖励")
        if give_up:
            d.click(int(give_up["cx"]), int(give_up["cy"]))
            time.sleep(2)
        if not return_to_walk_page():
            print("  ⚠️ 返回识别仍未知，沿用导航链有限恢复")
            if not navigate_to_walk_page():
                print("  ⚠️ 仍未能确认走路页，停止以避免在错误页面继续点击")
                return "unknown"
            blocks, confirmed = read_walk_page(retries=0)
            if not confirmed:
                print("  ⚠️ 导航后仍无法确认走路页，停止")
                return "unknown"
    print(f"  ✅ 档位【{steps}】处理完成")
    return "claimed"


def main():
    if sys.stdout.encoding == "gbk":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 50)
    print(" 🚶 走路球体完成")
    print("=" * 50)

    if not navigate_to_walk_page():
        print(" ⚠️ 无法进入走路赚元宝页面，停止（页面/OCR 未知或导航失败）")
        return 1

    last_steps = None
    repeats = 0
    processed = 0
    for _ in range(MAX_TIERS):
        blocks, confirmed = read_walk_page(retries=PAGE_UNKNOWN_RETRIES)
        tiers = scan_tiers(blocks)
        if confirmed and not tiers:
            print("\n ✅ 当前页面没有更多可点击档位，结束")
            break
        if not confirmed or not tiers:
            print("\n ⚠️ 走路页/档位识别未知，有界重扫后仍无法确认")
            if not navigate_to_walk_page():
                return 1
            blocks, confirmed = read_walk_page(retries=0)
            tiers = scan_tiers(blocks)
            if not confirmed or not tiers:
                print("\n ⚠️ 导航恢复后仍未确认走路页档位，停止")
                return 1
        steps, tier_block = tiers[0]
        if steps == last_steps:
            repeats += 1
            if repeats >= 2:
                print(f"\n ⚠️ 档位【{steps}步】连续处理仍未消失，停止避免死循环")
                break
        else:
            repeats = 0
        last_steps = steps

        result = claim_tier(tier_block)
        if result == "unavailable":
            print("\n 已遇到灰色档位，按累计规则停止")
            break
        if result in ("failed", "unknown"):
            reason = (
                "浏览任务有界超时或额外任务失败"
                if result == "failed" else
                "页面/OCR 未知或有界恢复失败；已停止以防在错误页面继续点击"
            )
            print(f"\n 档位处理未完成，停止：{reason}")
            return 1
        processed += 1
        time.sleep(2)

    print(f"\n 📊 本次共处理 {processed} 个走路档位")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n⚠️ 已停止")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\n❌ {exc}")
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
