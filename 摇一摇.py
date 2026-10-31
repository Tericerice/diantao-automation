"""摇一摇 自动化脚本
流程：启动点淘 → 元宝中心 → 点淘鸭家园 → 右滑 → 去摇一摇
→ 扫描「额外获得XX元宝 / 再得XX元宝」弹窗 → 循环完成视频/浏览任务
"""
import re
import sys
import time

from u2_scanner import (
    connect_device, DT_APP, execute_browse_task, execute_video_task,
)
from utils import click_ocr_text, get_ocr_text_blocks
from yuanbao_popup import handle_yuanbao_live_popups


d = connect_device()
screen_width, screen_height = d.window_size()
print(f"屏幕分辨率: {screen_width} x {screen_height}")

EXTRA_YUANBAO_VIDEO_SECONDS = 30
EXTRA_YUANBAO_EXTRA_SECONDS = 10
# 连续该秒数没有发现新弹窗即视为摇一摇奖励已领完。
EXTRA_YUANBAO_SCAN_TIMEOUT_SECONDS = 30
EXTRA_YUANBAO_PATTERN = re.compile(r"(额外获得|再得)\s*\d+\s*元宝")
BROWSE_TASK_NAME = "摇一摇浏览任务"
SCAN_ROUND_SECONDS = 2


# ========================================================
# 🧭 摇一摇逻辑：元宝中心 → 点淘鸭家园 → 右滑 → 去摇一摇
# ========================================================
def navigate():
    """进入摇一摇页面（不依赖手工停留在该页面）"""
    print("🔄 导航到【摇一摇赚元宝】...")

    print("  📱 启动点淘...")
    d.app_start(DT_APP, stop=True)
    time.sleep(5)

    print("  Step 1: 进入【元宝中心】...")
    if not click_ocr_text(
        d, ["元宝中心", "赚元宝"], settle_seconds=2.5,
        attempts=4, log=True,
    ):
        return False
    time.sleep(4)
    if not handle_yuanbao_live_popups(d):
        return False

    print("  Step 2: 进入【点淘鸭家园】...")
    if not click_ocr_text(
        d, "点淘鸭家园", settle_seconds=2.5,
        attempts=3, log=True,
    ):
        return False
    time.sleep(5)

    print("  Step 3: 右滑到最右边...")
    for index in range(2):
        start_x = int(screen_width * 0.15)
        end_x = int(screen_width * 0.85)
        swipe_y = int(screen_height * 0.50)
        print(f"    第 {index + 1}/2 次右滑")
        d.swipe(start_x, swipe_y, end_x, swipe_y, duration=0.3)
        time.sleep(1.5)
    print("  ✅ 已右滑到最右边")

    print("  Step 4: 点击【去摇一摇】...")
    if not click_ocr_text(
        d, "去摇一摇", settle_seconds=2.5,
        attempts=5, log=True,
    ):
        return False
    time.sleep(5)
    print("  ✅ 已进入摇一摇页面")
    return True


# ========================================================
# 💰 元宝部分：扫描「额外获得XX元宝 / 再得XX元宝」并执行
# ========================================================
def scan_extra_yuanbao_task(blocks):
    for block in blocks:
        text = block["text"]
        match = EXTRA_YUANBAO_PATTERN.search(text)
        if match:
            task_type = "video" if match.group(1) == "额外获得" else "browse"
            return task_type, text, int(block["cx"]), int(block["cy"])
    return None


def execute_extra_yuanbao_task(task_type, task_name, btn_cx, btn_cy):
    label = BROWSE_TASK_NAME if task_type == "browse" else task_name
    print(f"  🎯 执行【{label}】({task_name})")
    d.click(btn_cx, btn_cy)
    if task_type == "video":
        completed = execute_video_task(
            d,
            task_name,
            btn_cx,
            btn_cy,
            duration=EXTRA_YUANBAO_VIDEO_SECONDS + EXTRA_YUANBAO_EXTRA_SECONDS,
            verify_media_page=True,
            initial_swipe=True,
        )
    else:
        time.sleep(1.5)
        completed = execute_browse_task(
            d,
            min_duration=EXTRA_YUANBAO_VIDEO_SECONDS,
            max_wait=(EXTRA_YUANBAO_VIDEO_SECONDS + EXTRA_YUANBAO_EXTRA_SECONDS
                      + EXTRA_YUANBAO_SCAN_TIMEOUT_SECONDS),
            extra_seconds=EXTRA_YUANBAO_EXTRA_SECONDS,
        )
        if not completed:
            print(f"  ⚠️ 【{label}】浏览超时，保留当前页面，停止自动执行")
            return False
        d.press("back")
        time.sleep(2)
    if not completed:
        print(f"  ⚠️ 【{label}】未完成，停止自动执行")
        return False
    print(f"  ✅ 完成【{label}】")
    return True


def scan_and_execute():
    total = 0
    idle_seconds = 0

    print("\n🔍 开始扫描当前屏幕上的【额外获得XX元宝 / 再得XX元宝】...")
    while True:
        time.sleep(SCAN_ROUND_SECONDS)
        blocks = get_ocr_text_blocks(d)
        task = scan_extra_yuanbao_task(blocks) if blocks else None
        if not task:
            idle_seconds += SCAN_ROUND_SECONDS
            if idle_seconds >= EXTRA_YUANBAO_SCAN_TIMEOUT_SECONDS:
                print("  ✅ 持续未发现新弹窗，摇一摇额外元宝已领完")
                return
            print("  ⏳ 未发现额外元宝/再得元宝，继续等待")
            continue

        idle_seconds = 0
        task_type, name, cx, cy = task
        print(f"  📌 发现【{name}】 @({cx},{cy})")
        if not execute_extra_yuanbao_task(task_type, name, cx, cy):
            return
        total += 1
        print(f"  📊 已完成 {total} 个额外元宝任务")


def main():
    if sys.stdout.encoding == "gbk":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 50)
    print(" 🎉 摇一摇")
    print("=" * 50)

    if not navigate():
        print(" ⚠️ 无法进入摇一摇页面，停止")
        return

    scan_and_execute()


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
