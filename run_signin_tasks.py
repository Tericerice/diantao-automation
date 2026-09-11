#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_signin_tasks.py - 签到赢元宝连续任务执行器
============================================================
核心防护：
1. 任务返回后，必须先消除【继续做任务】/里程碑弹窗，再执行下一项。
2. 猜价格：固定3次单选框，若出现上限提示则关闭并标记跳过。
3. 浏览/视频：平稳滑动浏览，完成后 back 返回。
4. 遇阻停下并截屏。
"""

import os
import sys
import time
import re
import random
import subprocess
from pathlib import Path
from PIL import Image
import uiautomator2 as u2

CODEBUDDY_CLI = r"D:\WORKBUDDY\resources\app.asar.unpacked\cli\dist\codebuddy.js"
VISION_MODEL = "deepseek-v4.1-flash"
TEMP_DIR = Path(r"D:\GitHub Program\diantao\.cb_vision_temp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


def ai_call(img_path: str, prompt_text: str, timeout: int = 25) -> str:
    prompt = f"请使用Read工具读取图片：{img_path}。\n{prompt_text}"
    cmd = [
        "node", CODEBUDDY_CLI,
        "-y", "--strict-mcp-config", "--mcp-config", "{}",
        "--model", VISION_MODEL,
        "--tools", "Read",
        "-p", prompt
    ]
    try:
        t0 = time.time()
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        out = res.stdout.strip()
        print(f"  🧠 [AI 识别] ({time.time()-t0:.2f}s): {out[:50]}")
        return out
    except Exception as e:
        print(f"  ⚠️ [AI 异常]: {e}")
        return ""


def snap(d, prefix="snap"):
    img = d.screenshot()
    w, h = img.size
    small = img.resize((720, int(h * (720.0 / w))), Image.Resampling.LANCZOS)
    p = TEMP_DIR / f"{prefix}_{int(time.time()*1000)}.jpg"
    small.convert("RGB").save(str(p), "JPEG", quality=65)
    return str(p)


def dismiss_milestone_popups(d) -> bool:
    """
    自愈检查：关闭【前进步数奖励/继续做任务】或遮罩弹窗
    优先 U2 原生检查，其次 AI 检查，防止遮挡任务卡片
    """
    # 1. 优先使用 U2 检查【继续做任务】
    btn = d(textContains="继续做任务")
    if btn.exists(timeout=1):
        print("  🎯 [U2 原生检出] 发现【继续做任务】弹窗，点击消除...")
        btn.click()
        time.sleep(2)
        return True

    # 2. 兜底中心点击可能存在的弹窗按钮
    # 截屏快速查一次
    img_p = snap(d, "popup")
    out = ai_call(img_p, "当前页面是否有【继续做任务】弹窗或右上角关闭X？只回答：有 或 无")
    try:
        os.remove(img_p)
    except Exception:
        pass

    if "有" in out:
        sw, sh = d.window_size()
        print(f"  🛡️ 点击消除弹窗 @({sw//2}, {int(sh*0.73)})...")
        d.click(sw // 2, int(sh * 0.73))
        time.sleep(2)
        return True
    return False


def do_guess_price(d) -> bool:
    """执行猜价格任务"""
    sw, sh = d.window_size()
    print("\n🎲 [猜价格] 开始执行...")
    time.sleep(2.5)

    # 检查上限
    img_p = snap(d, "guess_limit")
    out = ai_call(img_p, "当前界面是否提示【已达最大上限次数】或【今日次数已用完】？回答：已达上限 或 正常答题")
    try:
        os.remove(img_p)
    except Exception:
        pass

    if "已达上限" in out:
        print("🛑 猜价格已达当日上限，点击关闭退出...")
        d.click(1180, 670)
        time.sleep(2)
        return False

    # 正常 3 次商品单选
    checkmarks = [(360, 1600), (770, 1600), (1180, 1600)]
    for i in range(3):
        cx, cy = checkmarks[i]
        print(f"  👉 第 {i+1}/3 次商品选择 @({cx}, {cy}) ➔ 点击确认...")
        d.click(cx, cy)
        time.sleep(1)
        d.click(632, 2520)
        time.sleep(2)

    time.sleep(1)
    # 点击右上角关闭 X (1180, 670)
    print("  👆 点击右上角 X 关闭猜价格...")
    d.click(1180, 670)
    time.sleep(2)
    # 偶尔误入商品页时的返回兜底
    if d(textContains="购物车").exists(timeout=1) or d(textContains="店铺").exists(timeout=1):
        d.press("back")
        time.sleep(2)
    return True


def do_browse_or_video(d, duration=50):
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
        time.sleep(random.uniform(3.0, 4.5))

    print("  ↩️ 滑动结束，按 back 返回签到主页...")
    d.press("back")
    time.sleep(2.5)


def run_all_tasks_loop():
    if sys.stdout.encoding and sys.stdout.encoding.lower() == 'gbk':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    d = u2.connect()
    sw, sh = d.window_size()
    print("=" * 60)
    print("🚀 签到赢元宝：全自动化任务执行循环启动")
    print("=" * 60)

    # 任务卡片固定按钮位置（3列卡片）
    btn_col1 = (230, 2620)
    btn_col2 = (495, 2620)
    btn_col3 = (815, 2620)

    guess_price_limit = False

    max_rounds = 15
    for r in range(1, max_rounds + 1):
        print(f"\n{'='*40}\n▶️ 执行轮次 #{r}\n{'='*40}")

        # 1. 任务前第一步：彻底消除任何遮罩或里程碑弹窗
        dismiss_milestone_popups(d)

        # 2. 依次按任务类型推进
        if not guess_price_limit:
            print("👉 选择卡片 1: 【玩1次猜价格】...")
            d.click(btn_col1[0], btn_col1[1])
            success = do_guess_price(d)
            if not success:
                guess_price_limit = True
        else:
            # 猜价格已达上限，执行卡片 2（视频/浏览）
            print(f"👉 猜价格已达上限，执行卡片 2: 【看视频/精选】...")
            d.click(btn_col2[0], btn_col2[1])
            do_browse_or_video(d, duration=50)

        # 3. 任务后第一步：立即检查并消除第5/15/26步里程碑弹窗！
        print("🛡️ [任务收尾] 检查是否触发前进步数里程碑弹窗...")
        dismiss_milestone_popups(d)

    print("\n🎉 签到赢元宝全部轮次执行完毕！")


if __name__ == "__main__":
    run_all_tasks_loop()
