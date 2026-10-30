"""走路球体完成：依次点击走路赚元宝的步数档位，领取奖励并完成额外元宝任务。

流程：
首页 → 元宝中心 → 走路赚元宝 → 扫描步数档位
→ 从小到大点击档位 → 出现「领取走路奖励 / 再得XX元宝」弹窗
→ 点击「再得XX元宝」完成浏览/直播任务 → 返回走路页 → 下一个档位

某个档位点击后没有任何弹窗，说明今天步数未达到该档（灰色），
由于档位是累计的，直接停止，不再尝试更高档位。
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


def browse_seconds(blocks, default=DEFAULT_BROWSE_SECONDS):
    for block in blocks:
        match = BROWSE_SECONDS_PATTERN.search(text(block))
        if match:
            seconds = int(match.group(1))
            if 0 < seconds <= 180:
                return seconds
    return default


def navigate_to_walk_page():
    blocks = get_ocr_text_blocks(d)
    if is_walk_page(blocks):
        print("  ✅ 已在走路赚元宝页面")
        return True
    print("  🧭 启动点淘，导航到【元宝中心 → 走路赚元宝】...")
    d.app_start(DT_APP, stop=True)
    time.sleep(5)
    if not navigate_chain(d, [("元宝中心", "元宝中心"), ("走路赚元宝", "走路赚元宝")]):
        print("  ⚠️ 导航未完成")
        return False
    time.sleep(3)
    blocks = get_ocr_text_blocks(d)
    if is_walk_page(blocks):
        print("  ✅ 已进入走路赚元宝页面")
        return True
    print("  ⚠️ 未识别到走路赚元宝页面")
    return False


def return_to_walk_page():
    for attempt in range(4):
        d.press("back")
        time.sleep(2)
        blocks = get_ocr_text_blocks(d)
        if is_walk_page(blocks) and not popup_visible(blocks):
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
        print(f"  ⊘ 档位【{steps}】没有出现领取弹窗，判定为灰色/未达成")
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
    blocks = get_ocr_text_blocks(d)
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
            print("  ⚠️ 仍未能返回走路页，停止")
            return "failed"
    print(f"  ✅ 档位【{steps}】处理完成")
    return "claimed"


def main():
    if sys.stdout.encoding == "gbk":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 50)
    print(" 🚶 走路球体完成")
    print("=" * 50)

    if not navigate_to_walk_page():
        print(" ⚠️ 无法进入走路赚元宝页面，停止")
        return

    last_steps = None
    repeats = 0
    processed = 0
    for _ in range(MAX_TIERS):
        blocks = get_ocr_text_blocks(d)
        tiers = scan_tiers(blocks)
        if not tiers:
            print("\n ✅ 当前页面没有更多可点击档位，结束")
            break
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
        if result == "failed":
            print("\n 档位处理失败，停止")
            break
        processed += 1
        time.sleep(2)

    print(f"\n 📊 本次共处理 {processed} 个走路档位")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ 已停止")
    except Exception as exc:
        print(f"\n❌ {exc}")
        import traceback
        traceback.print_exc()
