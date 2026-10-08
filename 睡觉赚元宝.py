"""
睡觉赚元宝 自动化脚本
流程：进点淘 → 睡觉赚元宝页面 → 扫描气泡任务 + 收集浮动气泡
"""
import time
import sys
from task_recheck import report_task_found, report_round_finished
import re
import random

import uiautomator2 as u2
from u2_scanner import (
    connect_device, DT_APP, navigate_to_sleep_page,
    click_u2_control,
    execute_browse_task, execute_video_task,
    execute_live_task,
    handle_guess_price_game, click_three_selected_items,
    scan_float_bubbles, click_float_bubbles,
    u2_find_task_buttons, is_stale_task_list, is_stale_no_buttons,
)
from utils import log_task_completed, show_today_summary
from utils import click_device_point

# ========================================================
# 全局变量
# ========================================================
d = connect_device()
screen_width, screen_height = d.window_size()
print(f"屏幕分辨率: {screen_width} x {screen_height}")

BROWSE_TIME = 65
STALE_LIMIT = 3

TASK_KW = [
    "猜价格", "去玩一次猜",
    "看直播", "看福利", "看视频",
    "直播间",
    "精选推荐", "精选好物", "精选宝贝", "新好物", "省钱专区",
    "浏览", "去浏览", "查看",
]

CENTER_WAITING = ["后可开启", "熟睡中", "倒计时"]
CENTER_ACTIVE = ["开启晚睡", "开始睡觉", "收下元宝"]


def check_center_btn():
    """检测中央睡觉按钮"""
    print("  检测中央按钮...")
    # 倒计时中
    for kw in CENTER_WAITING:
        if d(textContains=kw).exists(timeout=1):
            print(f"    倒计时中: {kw}")
            return "waiting"
    # 可点击
    for kw in CENTER_ACTIVE:
        btn = d(textContains=kw)
        if btn.exists(timeout=1):
            click_u2_control(d, btn, kw)
            print(f"    点击 {kw}")
            time.sleep(3)
            return "clicked"
    print("    无按钮")
    return "no_button"


def find_bubble():
    """找气泡任务（文字本身就是可点击的气泡按钮）"""
    for kw in TASK_KW:
        btn = d(textContains=kw)
        if btn.exists(timeout=1):
            text = btn.get_text().strip()
            try:
                cx, cy = btn.center()
                cx, cy = int(cx), int(cy)
            except:
                continue
            # 气泡按钮在屏幕 15%~65% 范围内才接受
            if cy < int(screen_height * 0.15) or cy > int(screen_height * 0.65):
                continue
            print(f"    [匹配] {text} → 点击文字本身 @({cx},{cy})")
            return {"name": text, "cx": cx, "cy": cy}
    return None


def do_bubble_task(name, btn_cx, btn_cy):
    """执行气泡任务"""
    print(f"  🎯 {name}")

    if "猜价格" in name:
        d.click(btn_cx, btn_cy)
        time.sleep(3)
        try:
            btn = d(className="android.widget.Button", textMatches=r"打开|允许|始终允许")
            if btn.exists(timeout=1):
                click_u2_control(d, btn, "打开/允许")
                time.sleep(1)
        except:
            pass
        handle_guess_price_game(d)
        time.sleep(2)
        try:
            log_task_completed("睡觉赚元宝", name)
        except:
            pass
        return

    if "看视频" in name:
        click_device_point(d, btn_cx, btn_cy, "视频任务按钮")
        time.sleep(0.5)
        execute_video_task(
            d, name, btn_cx, btn_cy,
            extra_time_seconds=10,
            verify_media_page=True,
        )
        time.sleep(1.5)
    elif any(kw in name for kw in ["看直播", "直播"]):
        click_device_point(d, btn_cx, btn_cy, "直播任务按钮")
        time.sleep(0.5)
        execute_live_task(d, name, btn_cx, btn_cy)
        d.press("back")
        time.sleep(1.5)
    elif "精选宝贝" in name or ("查看" in name and "个" in name) or "签到" in name:
        click_device_point(d, btn_cx, btn_cy, "精选宝贝任务按钮")
        time.sleep(0.5)
        click_three_selected_items(d)
        # click_three_selected_items 每次点完商品已 back 回到列表页，
        # 再按一次从列表页退回睡觉页
        d.press("back")
        time.sleep(1.5)
    else:
        # 浏览任务
        click_device_point(d, btn_cx, btn_cy, "浏览任务按钮")
        time.sleep(0.5)
        try:
            btn = d(className="android.widget.Button", textMatches=r"打开|允许|始终允许")
            if btn.exists(timeout=1):
                click_u2_control(d, btn, "打开/允许")
                time.sleep(1)
        except:
            pass
        # 看精选/上新类任务固定60秒浏览
        if any(kw in name for kw in ["精选推荐", "精选好物", "上新好物", "省钱专区"]):
            execute_browse_task(d, BROWSE_TIME)
        else:
            execute_browse_task(d, 20)
        d.press("back")
        time.sleep(1.5)

    try:
        log_task_completed("睡觉赚元宝", name)
    except:
        pass


def scan_and_collect():
    """主循环：找气泡 → 执行 → 收集浮动气泡"""
    total = 0
    prev_snap = []
    prev_empty = []

    btn_status = check_center_btn()
    if btn_status == "waiting":
        print("  跳过点击")
    elif btn_status == "clicked":
        time.sleep(3)

    print("\n🔍 扫描气泡...")
    while True:
        time.sleep(1.5)
        print(f"\n📡 扫描中 ({total}个)...")

        target = find_bubble()
        if target:
            prev_snap.clear()
            prev_empty.clear()
            report_task_found()
            do_bubble_task(target["name"], target["cx"], target["cy"])
            total += 1
            print(f"  ✅ 已完成: {total}")
            continue

        # 收集浮动气泡
        count = click_float_bubbles(d, max_collect=5)
        if count > 0:
            report_task_found()
            prev_snap.clear()
            
            prev_empty.clear()
            total += count
            continue

        # 当前可视区域无气泡+无浮动气泡，直接结束（不下滑）
        print("  当前区域无可用任务，结束")
        break

    print(f"\n📊 共完成 {total} 个")
    report_round_finished()
    return total


def main():
    if sys.stdout.encoding == 'gbk':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 50)
    print(" 睡觉赚元宝")
    print("=" * 50)

    navigate_to_sleep_page(d)
    scan_and_collect()

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
