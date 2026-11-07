#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
guess_price_codebuddy.py - 猜价格标准化执行器 (双退出标准版)
============================================================
核心退出标准（依用户明确指示定做）：
标准 1: 出现【XXXXX后再试】/【XXXXX后再来玩】/【猜对啦】
        -> 游戏立即结束，点击右上角 X 关闭退出，绝不多点一次！
标准 2: 出现【达到当日上限】/【已达最大上限次数】/【今日次数已用完】
        -> 立即关闭退出，并返回 False 标记今日不再执行猜价格！
标准坐标（原版实测基准）：
- 3 列商品单选 X: [225, 633, 1043]
- 行 1 Y: 1609, 行 2 Y: 2218
- 确认按钮: (633, 2520)
- 关闭 X 按钮: (1179, 745)
"""

import time
import re
from typing import Tuple
import uiautomator2 as u2
from utils import get_ocr_text_blocks, has_ocr_text


def check_game_over_conditions(device) -> Tuple[bool, str]:
    """
    检查两大退出标准：
    返回 (is_over, reason):
      - is_over: 是否应该结束游戏
      - reason: 'countdown' (倒计时/再试/猜对) 或 'limit' (达到当日上限) 或 ''
    """
    # 点淘 WebView 只通过 OCR 读取可见文字，不查询 U2 控件树。
    try:
        blocks = get_ocr_text_blocks(device)
        full_text = " ".join(b.get("text", "") for b in blocks)
        if any(kw in full_text for kw in ["已达最大上限", "达到当日上限", "今日次数已用完", "明日再来"]):
            return True, "limit"
        if any(kw in full_text for kw in ["后再试", "后再来玩", "猜对啦"]):
            return True, "countdown"
        if re.search(r"\d{1,2}:\d{2}(?::\d{2})?\s*后", full_text):
            return True, "countdown"
    except Exception:
        pass

    return False, ""


def close_guess_popup(device):
    """标准关闭猜价格弹窗"""
    print("  👆 点击右上角关闭 X @(1179, 745)...")
    device.click(1179, 745)
    time.sleep(1.5)
    # 偶尔误入商品页时通过 OCR 判断并返回。
    if has_ocr_text(device, ["购物车", "店铺"], settle_seconds=0.3, attempts=1, log=True):
        print("  ⚠️ OCR 检测到进入商品详情页，按 back 返回...")
        device.press("back")
        time.sleep(1.5)


def run_guess_price(device) -> bool:
    """
    执行猜价格游戏
    返回: True (正常完成), False (达到当日上限，后续应跳过)
    """
    print("\n  ========== 🎲 猜价格游戏 (标准双标准版) ==========")
    screen_w, screen_h = device.window_size()

    # 原版实测基准坐标
    col_x = [225, 633, 1043] if screen_w > 1000 else [screen_w // 6, screen_w // 2, screen_w * 5 // 6]
    row1_y = 1609 if screen_h > 2400 else int(screen_h * 0.58)
    row2_y = 2218 if screen_h > 2400 else int(screen_h * 0.80)
    confirm_y = 2520 if screen_h > 2400 else int(screen_h * 0.905)
    confirm_x = screen_w // 2

    time.sleep(2)

    # 进入前先检查一次是否直接显示上限
    is_over, reason = check_game_over_conditions(device)
    if is_over:
        if reason == "limit":
            print("  🛑 【标准 2 触发】当前提示【达到当日上限次数】，立即退出并标记！")
            close_guess_popup(device)
            return False
        else:
            print("  ✅ 【标准 1 触发】已存在倒计时/后再试提示，立即关闭退出！")
            close_guess_popup(device)
            return True

    # 最多执行 3 次选择
    max_clicks = 3
    for attempt in range(max_clicks):
        col = attempt % 3
        check_x = col_x[col]
        check_y = row1_y

        print(f"  👉 第 {attempt+1}/{max_clicks} 次猜测：点击商品 @({check_x}, {check_y})...")
        device.click(check_x, check_y)
        time.sleep(0.8)

        print(f"     点击【猜它最接近】 @({confirm_x}, {confirm_y})...")
        device.click(confirm_x, confirm_y)
        time.sleep(2.0)

        # 每次点击确认后，立刻检查两大退出标准！
        is_over, reason = check_game_over_conditions(device)
        if is_over:
            if reason == "limit":
                print("  🛑 【标准 2 触发】检测到【达到当日上限次数】，游戏立即终止！")
                close_guess_popup(device)
                return False
            else:
                print(f"  🎉 【标准 1 触发】检测到【XXXXX后再试/猜对啦】，成功命中，立即退出！")
                close_guess_popup(device)
                return True

    print("  ℹ️ 3 次机会已用完，收工退出。")
    close_guess_popup(device)
    return True
