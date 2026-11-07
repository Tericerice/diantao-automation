#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_signin_tasks.py - 签到赢元宝全自动化执行器 (标准双退出标准版)
==================================================================
严格遵循用户规范：
1. 猜价格执行标准：
   - 出现【XXXXX后再试/后再来玩/猜对啦】立即退出，绝不多点！
   - 出现【达到当日上限/已达最大上限次数】立即退出并标记今日跳过！
   - 坐标完全采用原版实测基准 (col_x=[225, 633, 1043], confirm=(633, 2520), close=(1179, 745))。
2. 任务前后里程碑弹窗严格自愈：第5/15/26步弹窗一键消除。
3. 浏览/视频任务：动态滑动控制，完成后安全返回。
"""

import os
import sys
import time
import re
import random
from guess_price_codebuddy import run_guess_price
from utils import click_ocr_text, has_ocr_text


def dismiss_milestone_popups(d) -> bool:
    """
    自愈检查：关闭【前进步数奖励/继续做任务】或遮罩弹窗
    """
    if click_ocr_text(d, "继续做任务", settle_seconds=0.5, attempts=1, log=True):
        print("  🎯 [自愈] OCR 发现并点击【继续做任务】弹窗...")
        time.sleep(2)
        return True

    if has_ocr_text(d, ["前进步数奖励", "恭喜获得", "步数奖励"], settle_seconds=0.3, attempts=1, log=True):
        print("  ⚠️ OCR 检测到奖励遮罩，但未识别到安全按钮，不进行盲点")

    return False


def do_browse_or_video(d, duration=45):
    """执行浏览或视频任务"""
    sw, sh = d.window_size()
    print(f"\n📋 [浏览/视频] 启动滑动 (时长: {duration}s)...")
    time.sleep(3)
    start_t = time.time()
    while time.time() - start_t < duration:
        sx = int(sw * random.uniform(0.45, 0.55))
        sy = int(sh * random.uniform(0.75, 0.85))
        ey = int(sh * random.uniform(0.18, 0.28))
        d.swipe(sx, sy, sx, ey, duration=0.3)
        time.sleep(random.uniform(3.0, 4.2))

    print("  ↩️ 滑动结束，按 back 返回签到主页...")
    d.press("back")
    time.sleep(2.5)


def run_signin_loop():
    if sys.stdout.encoding and sys.stdout.encoding.lower() == 'gbk':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    from u2_scanner import connect_device
    d = connect_device()
    sw, sh = d.window_size()
    print("=" * 60)
    print("🚀 启动【签到赢元宝】全新双退出标准版全自动调度")
    print("=" * 60)

    # 3 列任务卡片的红色【去完成】按钮位置
    btn_col1 = (230, 2620)
    btn_col2 = (495, 2620)
    btn_col3 = (815, 2620)

    guess_price_limit = False
    max_rounds = 20

    for r in range(1, max_rounds + 1):
        print(f"\n{'='*40}\n▶️ 签到子任务执行轮次 #{r}\n{'='*40}")

        # 1. 任务前：严格消除任何可能存在的里程碑遮罩
        dismiss_milestone_popups(d)

        # 2. 任务选择与分流
        if not guess_price_limit:
            print("👉 选择卡片 1: 【玩1次猜价格】...")
            d.click(btn_col1[0], btn_col1[1])
            time.sleep(2.5)
            # 执行猜价格（内含两大退出标准判定与原版实测坐标）
            success = run_guess_price(d)
            if not success:
                guess_price_limit = True
                print("⚠️ 猜价格已达当日上限，后续将自动跳过猜价格！")
        else:
            print("👉 猜价格已达上限，执行卡片 2: 【看视频/精选推荐】...")
            d.click(btn_col2[0], btn_col2[1])
            do_browse_or_video(d, duration=45)

        # 3. 任务后：立刻消除第 5、15、26 步里程碑弹窗！
        time.sleep(1.5)
        print("🛡️ [任务收尾] 检查并消除里程碑弹窗...")
        dismiss_milestone_popups(d)

    print("\n🎉 【签到赢元宝】全部子任务执行完毕！")


if __name__ == "__main__":
    run_signin_loop()
