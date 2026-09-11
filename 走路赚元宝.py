"""
走路赚元宝 自动化脚本
用户需先在手机上打开走路赚元宝页面，脚本自动扫描执行任务
优先级：福利直播 > 看直播 > 猜价格 > 浏览精选

采用纯 OCR + 坐标配对方案（参考打工得体力.py）
"""
import time
import sys
import re
import random

import uiautomator2 as u2
from utils import (
    connect_device, get_ocr_text_blocks, check_can_open,
    log_task_completed, show_today_summary,
    DT_APP, get_current_app, pause_global_watcher, resume_global_watcher,
)
from u2_scanner import (
    execute_live_task, execute_video_task, execute_browse_task,
    handle_guess_price_game,
)

# ========================================================
# 全局变量
# ========================================================
d = connect_device()
screen_width, screen_height = d.window_size()
print(f"屏幕分辨率: {screen_width} x {screen_height}")

MAX_SCROLL = 12
NAME_ABOVE_GAP = 200  # 任务名在"去完成"上方，最大垂直间距
NAME_H_OFFSET = 690   # 任务名在左侧，"去完成"按钮在右侧，水平间距上限

# 黑名单关键词
BLACKLIST_KEYWORDS = [
    "元宝商城", "下单", "购买", "充值", "付款",
    "邀请", "邀请好友", "拉好友", "助力", "分享", "去邀请",
    "喂鸡", "蚂蚁庄园", "蚂蚁新村", "饿了么", "果园",
    "消消乐", "农场小游戏", "斗地主", "开心消消乐",
    "猜谜", "猜一猜",
    "查看并完成", "玩小游戏",
    "同程旅行",
]

# 白名单：只执行白名单中的任务，其他任务一律跳过
# 走路赚元宝页面的典型安全任务列表
WHITELIST = [
    "看福利直播",
    "看直播",
    "直播",
    "猜价格",
    "浏览精选推荐",
    "浏览当季上新好物",
    "浏览省钱专区",
    "浏览",
    "签到",
    "查看",
    "看视频",
]

# 去完成按钮关键词
DONE_BTN_KEYWORDS = ["去完成", "去浏览", "去观看", "去参与", "去领取", "去签到", "立即参与", "立即领取"]

# 任务类型优先级：福利直播 > 看直播 > 猜价格 > 浏览
TASK_PRIORITY = {
    "live_welfare": 1,
    "live": 2,
    "video": 2,
    "guess_price": 3,
    "browse": 4,
}


def parse_seconds(text, default=60):
    """从任务名提取秒数"""
    m = re.search(r"(\d+)\s*秒", text)
    return int(m.group(1)) if m else default


def match_task_type(text):
    """精确匹配任务名 → 返回类型字符串"""
    if "福利直播" in text or ("看直播" in text and "福利" in text):
        return "live_welfare"
    if "看视频" in text:
        return "video"
    if "猜价格" in text:
        return "guess_price"
    if "直播" in text:
        return "live"
    if "浏览" in text or "精选推荐" in text or "猜你喜欢" in text \
       or "省钱" in text or "上新好物" in text or "签到" in text \
       or "查看" in text:
        return "browse"
    return "other"


def detect_task_name(blocks, btn_block):
    """从按钮上方同一列提取真实任务名（参考打工得体力.py）
    布局：
        任务名              ← 目标
        额外得XX元宝        ← 过滤掉
        (0/15)              ← 过滤掉
        去完成              ← 按钮
    """
    cx, cy = btn_block["cx"], btn_block["cy"]
    above = []
    for nb in blocks:
        if nb["cy"] >= cy:
            continue
        vdist = cy - nb["cy"]
        if vdist > NAME_ABOVE_GAP:
            continue
        hdist = abs(nb["cx"] - cx)
        if hdist > NAME_H_OFFSET:
            continue
        above.append((vdist, nb["text"]))

    above.sort(key=lambda x: x[0])  # 按垂直距离排序（最近优先）

    # 过滤干扰文本，取第一个非干扰文本作为任务名
    for _, t in above:
        if "额外得" in t or "额外返" in t:
            continue
        if "元宝" in t or "金币" in t:
            continue
        if re.match(r'^\(\d+/\d+\)$', t.strip()):
            continue
        if re.match(r'^\d+$', t.strip()):
            continue
        return t

    # 全部被过滤掉，回退到最近的文本
    return above[0][1] if above else ""


def is_blacklisted(text):
    """检查任务名是否在黑名单中"""
    if not text:
        return True
    return any(kw in text for kw in BLACKLIST_KEYWORDS)


def is_whitelisted(text):
    """白名单自读：检查任务名是否在白名单中
    只有白名单中的任务才会被执行，其他一律跳过
    """
    if not text:
        return False
    return any(kw in text for kw in WHITELIST)


def parse_tasks_from_blocks(blocks):
    """从 OCR 文本块中解析出所有可执行任务
    返回: [(priority, task_type, task_name, btn_cx, btn_cy), ...]
          按优先级排序：福利直播 > 看直播 > 猜价格 > 浏览
    """
    candidates = []
    for b in blocks:
        text = b["text"]
        if not any(kw in text for kw in DONE_BTN_KEYWORDS):
            continue

        task_name = detect_task_name(blocks, b)
        if not task_name:
            continue

        # 🟢 白名单自读：只执行白名单中的任务
        if not is_whitelisted(task_name):
            print(f"    ⊘ 非白名单跳过: 【{task_name}】")
            continue

        # 黑名单过滤（二级安全网）
        if is_blacklisted(task_name):
            print(f"    ⊘ 黑名单跳过: 【{task_name}】")
            continue

        task_type = match_task_type(task_name)
        if task_type == "other":
            continue

        priority = TASK_PRIORITY[task_type]
        candidates.append((priority, task_type, task_name, int(b["cx"]), int(b["cy"])))

    candidates.sort(key=lambda x: x[0])
    return candidates


def exec_live(btn_cx, btn_cy, task_name=""):
    """执行看直播任务"""
    print(f"  🎯 {task_name}")
    d.click(btn_cx, btn_cy)
    time.sleep(0.5)
    check_can_open(d)
    execute_live_task(d, task_name, btn_cx, btn_cy)
    d.press("back")
    time.sleep(1.5)


def exec_video(btn_cx, btn_cy, task_name=""):
    """执行看视频任务：入口点击后只定时上滑，到点返回。"""
    print(f"  🎯 {task_name}")
    pause_global_watcher(d)
    try:
        d.click(btn_cx, btn_cy)
        execute_video_task(
            d, task_name, btn_cx, btn_cy,
            verify_media_page=True,
        )
    finally:
        resume_global_watcher(d)


def exec_guess_price(btn_cx, btn_cy, task_name=""):
    """执行猜价格任务"""
    print(f"  🎯 {task_name}")
    d.click(btn_cx, btn_cy)
    time.sleep(3)
    check_can_open(d)
    handle_guess_price_game(d)


def exec_browse(btn_cx, btn_cy, task_name=""):
    """执行浏览任务（使用OCR智能监控，避免多等extra_seconds）"""
    print(f"  🎯 {task_name}")
    d.click(btn_cx, btn_cy)
    time.sleep(3)
    check_can_open(d)

    duration = parse_seconds(task_name, default=90)
    execute_browse_task(d, min_duration=duration, max_wait=duration + 30)

    d.press("back")
    time.sleep(2)


def execute_task(task_type, task_name, btn_cx, btn_cy):
    """根据任务类型执行"""
    if task_type == "video":
        exec_video(btn_cx, btn_cy, task_name)
    elif task_type in ("live_welfare", "live"):
        exec_live(btn_cx, btn_cy, task_name)
    elif task_type == "guess_price":
        exec_guess_price(btn_cx, btn_cy, task_name)
    elif task_type == "browse":
        exec_browse(btn_cx, btn_cy, task_name)

    try:
        log_task_completed("走路赚元宝", task_name)
    except:
        pass


def main():
    if sys.stdout.encoding == 'gbk':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 50)
    print(" 🚶 走路赚元宝")
    print("   优先级: 福利直播 > 看直播 > 猜价格 > 浏览")
    print(" 🟢 白名单自读模式已启用")
    print(f"   白名单: {' | '.join(WHITELIST)}")
    print("=" * 50)

    print("\n📌 请确保已在走路赚元宝页面")
    time.sleep(3)

    total_all = 0
    scroll_count = 0
    ocr_empty_retries = 0
    first_scan = True

    while True:
        # 每次扫描前确保 u2 调试覆盖层已关闭
        try:
            d.settings["uiautomator"] = {}
            d.settings["operation_delay"] = 0.5
        except Exception:
            pass
        try:
            d.settings.pop("debug", None)
        except Exception:
            pass

        # 首次 OCR 前先等待页面稳定
        if first_scan:
            first_scan = False
            time.sleep(2)

        time.sleep(1.5)
        print(f"\n🔍 扫描中 (已成功{total_all}个)...")

        blocks = get_ocr_text_blocks(d)
        if not blocks:
            ocr_empty_retries += 1
            if ocr_empty_retries <= 3:
                wait = 3.0 * ocr_empty_retries
                print(f"  ⚠️ OCR 无结果（第 {ocr_empty_retries} 次），{wait}s 后重试...")
                time.sleep(wait)
                continue
            print("  ⚠️ OCR 多次无结果，结束")
            break

        task_list = parse_tasks_from_blocks(blocks)
        if not task_list:
            # 诊断：打印前 20 个 OCR 文本块
            print(f"  🐛 OCR 返回 {len(blocks)} 个文本块，但未匹配到任务按钮")
            print(f"  🐛 前 20 个文本块:")
            for idx, b in enumerate(blocks[:20]):
                print(f"    [{idx}] \"{b['text']}\" @({b['cx']},{b['cy']}) conf={b.get('conf',0):.2f}")

            # 下滑找更多任务
            scroll_count += 1
            if scroll_count > MAX_SCROLL:
                print(f"  ✅ 已下滑 {MAX_SCROLL} 次无任务，全部完成")
                break

            print(f"  ⬇️ 下滑 ({scroll_count}/{MAX_SCROLL})...")
            d.swipe(screen_width // 2, int(screen_height * 0.7),
                    screen_width // 2, int(screen_height * 0.3))
            time.sleep(2)
            continue

        # 有任务 → 重置计数
        scroll_count = 0
        ocr_empty_retries = 0

        # 只执行第一个（优先级最高的）
        priority, task_type, task_name, btn_cx, btn_cy = task_list[0]
        print(f"\n  ▶️ [{total_all + 1}] {task_name} (优先级{priority})")
        execute_task(task_type, task_name, btn_cx, btn_cy)
        total_all += 1
        print(f"  ✅ 已完成: {total_all} 个任务")

    print(f"\n📊 共完成 {total_all} 个任务")

    try:
        show_today_summary()
    except:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ 中断")
    except Exception as e:
        print(f"\n❌ {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(" 👋")
