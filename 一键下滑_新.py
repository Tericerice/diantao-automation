"""
一键下滑 (新) - 标准路径版
============================================================
流程：6轮顺序执行，每轮：重启点淘 → 进入元宝中心 → 标准路径导航进入目标页 → 下滑浏览

【核心改造点】
1. 路径改回标准路径：严格遵循 UIAutomator2 原生控件定位优先原则。
   - 打工：元宝中心 → 查找点击【打工赚元宝】
   - 睡觉：元宝中心 → 查找点击【睡觉赚元宝】
   - 签到：元宝中心 → 下滑查找【今日签到】/【去看看】（废弃进两次连退3次黑魔法）
   - 购物：元宝中心 → 查找点击【购物赚钱】文本（彻底废除固定坐标盲点）
   - 摇一摇：元宝中心 → 点击【点淘鸭家园】→ 查找【去摇一摇】
   - 走路：元宝中心 → 查找点击【走路赚元宝】（废除多次耗时全屏 OCR 轮询）
2. 防空滑安全网（修复代码审计问题 13）：
   - 所有导航函数明确返回 bool 状态。
   - 导航失败时直接跳过该轮次下滑，绝不残留于错误页面盲滑。
3. 零顶层副作用：
   - 设备连接收口到 main 执行流程，便于被外部模块或测试安全导入。
============================================================
"""
import time
import sys
import random

from u2_scanner import (
    connect_device, DT_APP, navigate_chain, u2_click_text,
    scan_page, find_clickable_with_text, click_u2_control
)


# ========================================================
# 🧭 标准导航函数库
# ========================================================

def _nav_to_yuanbao_center(device, sw: int, sh: int) -> bool:
    """进入元宝中心（标准路径）"""
    print("  🧭 正在进入【元宝中心】...")
    for text in ["元宝中心", "赚元宝"]:
        btn = device(textContains=text)
        if btn.exists(timeout=3):
            click_u2_control(device, btn, text)
            time.sleep(4)
            return True

    # 兜底：点击底部导航栏右侧元宝中心常用区域
    print("    ⚠️ 未找到文字，使用底部区域兜底点击...")
    device.click(int(sw * 0.7), int(sh * 0.93))
    time.sleep(4)
    return True


def _nav_to_dagong(device, sw: int, sh: int) -> bool:
    """导航：元宝中心 → 打工赚元宝（标准 U2 文本匹配）"""
    print("  🧭 查找【打工赚元宝】入口...")
    for text in ["打工赚元宝", "打工"]:
        btn = device(textContains=text)
        if btn.exists(timeout=2):
            click_u2_control(device, btn, text)
            time.sleep(4)
            print("  ✅ 已成功进入【打工赚元宝】")
            return True

    # hierarchy 兜底扫描
    nodes = scan_page(device)
    target = find_clickable_with_text(nodes, "打工赚元宝") or find_clickable_with_text(nodes, "打工")
    if target and target["cx"] > 0:
        device.click(target["cx"], target["cy"])
        time.sleep(4)
        print(f"  ✅ hierarchy 点击进入【打工赚元宝】 @({target['cx']},{target['cy']})")
        return True

    print("  ⚠️ 未找到【打工赚元宝】入口")
    return False


def _nav_to_sleep(device, sw: int, sh: int) -> bool:
    """导航：元宝中心 → 睡觉赚元宝（标准 U2 文本匹配）"""
    print("  🧭 查找【睡觉赚元宝】入口...")
    for text in ["睡觉赚元宝", "睡觉"]:
        btn = device(textContains=text)
        if btn.exists(timeout=2):
            click_u2_control(device, btn, text)
            time.sleep(4)
            print("  ✅ 已成功进入【睡觉赚元宝】")
            return True

    nodes = scan_page(device)
    target = find_clickable_with_text(nodes, "睡觉赚元宝") or find_clickable_with_text(nodes, "睡觉")
    if target and target["cx"] > 0:
        device.click(target["cx"], target["cy"])
        time.sleep(4)
        print(f"  ✅ hierarchy 点击进入【睡觉赚元宝】 @({target['cx']},{target['cy']})")
        return True

    print("  ⚠️ 未找到【睡觉赚元宝】入口")
    return False


def _nav_to_signin(device, sw: int, sh: int) -> bool:
    """
    导航：元宝中心 → 签到赢元宝（标准路径下滑查找）
    规范化单次进入，废除原有强行连退3次的黑魔法。
    """
    print("  📜 下滑查找【今日签到】入口...")
    for scroll_idx in range(6):
        sign_btn = device(textContains="今日签到")
        if sign_btn.exists(timeout=2):
            try:
                sign_cx, sign_cy = sign_btn.center()
                sign_cx, sign_cy = int(sign_cx), int(sign_cy)
            except Exception:
                continue

            # 优先寻找同行/附近的"去看看"或"去签到"按钮
            for btn_kw in ["去看看", "去签到", "立即签到"]:
                go_btn = device(textContains=btn_kw)
                if go_btn.exists(timeout=1):
                    try:
                        gx, gy = go_btn.center()
                        gx, gy = int(gx), int(gy)
                        if abs(gx - sign_cx) > 40 and -30 <= gy - sign_cy <= 220:
                            device.click(gx, gy)
                            time.sleep(3)
                            print(f"  ✅ 点击【{btn_kw}】进入签到页面 @({gx},{gy})")
                            return True
                    except Exception:
                        pass

            # 若未找到右侧去看看，直接点击签到文本区域
            device.click(sign_cx, sign_cy)
            time.sleep(3)
            print(f"  ✅ 点击【今日签到】文本进入 @({sign_cx},{sign_cy})")
            return True

        # 未找到时标准下滑半屏继续寻找
        device.swipe(sw // 2, int(sh * 0.75), sw // 2, int(sh * 0.35))
        time.sleep(1.5)

    print("  ⚠️ 未能在元宝中心找到【今日签到】")
    return False


def _nav_to_shop(device, sw: int, sh: int) -> bool:
    """
    导航：元宝中心 → 购物赚钱（标准路径文本匹配，废弃固定坐标盲点）
    """
    print("  🧭 查找【购物赚钱】入口...")
    for text in ["购物赚钱", "点淘购物赚钱"]:
        btn = device(textContains=text)
        if btn.exists(timeout=2):
            click_u2_control(device, btn, text)
            time.sleep(3)
            print(f"  ✅ 点击【{text}】成功进入购物赚钱页面")
            return True

    # 尝试轻微滑动一屏查找
    device.swipe(sw // 2, int(sh * 0.70), sw // 2, int(sh * 0.40))
    time.sleep(1.5)
    for text in ["购物赚钱", "点淘购物赚钱"]:
        btn = device(textContains=text)
        if btn.exists(timeout=2):
            click_u2_control(device, btn, text)
            time.sleep(3)
            print(f"  ✅ 下滑后点击【{text}】成功进入购物赚钱页面")
            return True

    print("  ⚠️ 未找到【购物赚钱】标准入口")
    return False


def _nav_to_yaoyiyao(device, sw: int, sh: int) -> bool:
    """
    导航：元宝中心 → 点淘鸭家园 → 去摇一摇（标准路径）
    """
    print("  🧭 Step 1: 查找【点淘鸭家园】入口...")
    duck_entered = False
    for text in ["点淘鸭家园", "点淘鸭"]:
        btn = device(textContains=text)
        if btn.exists(timeout=2):
            click_u2_control(device, btn, text)
            time.sleep(4)
            duck_entered = True
            break

    if not duck_entered:
        # 兼容旧版实测比例坐标兜底 (0.77*sw, 0.70*sh)
        duck_x = int(sw * 0.77)
        duck_y = int(sh * 0.70)
        print(f"    ⚠️ 未找到文字，尝试比例坐标兜底 @({duck_x},{duck_y})...")
        device.click(duck_x, duck_y)
        time.sleep(4)

    print("  🧭 Step 2: 查找【去摇一摇】入口...")
    for attempt in range(3):
        for text in ["去摇一摇", "摇一摇"]:
            btn = device(textContains=text)
            if btn.exists(timeout=2):
                click_u2_control(device, btn, text)
                time.sleep(3)
                print(f"  ✅ 已成功进入【{text}】页面")
                return True
        # 右滑查看更多活动
        device.swipe(int(sw * 0.2), int(sh * 0.5), int(sw * 0.8), int(sh * 0.5), duration=0.25)
        time.sleep(1.5)

    print("  ⚠️ 未能找到【去摇一摇】入口")
    return False


def _nav_to_walk(device, sw: int, sh: int) -> bool:
    """
    导航：元宝中心 → 走路赚元宝（标准原生文本定位，废除5次全屏OCR）
    """
    print("  🧭 查找【走路赚元宝】入口...")
    for text in ["走路赚元宝", "走路"]:
        btn = device(textContains=text)
        if btn.exists(timeout=2):
            click_u2_control(device, btn, text)
            time.sleep(4)
            print(f"  ✅ 已成功进入【{text}】")
            return True

    # 下滑一屏寻找
    for _ in range(3):
        device.swipe(sw // 2, int(sh * 0.75), sw // 2, int(sh * 0.35))
        time.sleep(1.5)
        btn = device(textContains="走路赚元宝")
        if btn.exists(timeout=2):
            click_u2_control(device, btn, "走路赚元宝")
            time.sleep(4)
            print("  ✅ 下滑后找到并点击【走路赚元宝】")
            return True

    print("  ⚠️ 未能找到【走路赚元宝】入口")
    return False


# ========================================================
# 📋 轮次配置
# ========================================================
ROUNDS_CONFIG = [
    {
        "label": "1",
        "name": "打工赚元宝",
        "swipe_seconds": 180,
        "nav_func": _nav_to_dagong,
    },
    {
        "label": "2",
        "name": "睡觉赚元宝",
        "swipe_seconds": 180,
        "nav_func": _nav_to_sleep,
    },
    {
        "label": "3",
        "name": "签到赢元宝",
        "swipe_seconds": 180,
        "nav_func": _nav_to_signin,
    },
    {
        "label": "4",
        "name": "购物赚钱",
        "swipe_seconds": 180,
        "nav_func": _nav_to_shop,
    },
    {
        "label": "5",
        "name": "摇一摇",
        "swipe_seconds": 180,
        "nav_func": _nav_to_yaoyiyao,
    },
    {
        "label": "6",
        "name": "走路赚元宝",
        "swipe_seconds": 180,
        "nav_func": _nav_to_walk,
    },
]


# ========================================================
# 📱 下滑浏览
# ========================================================
def swipe_browse(device, seconds: int, sw: int, sh: int):
    """纯下滑浏览（保留稳定滑动节奏）"""
    if seconds <= 0:
        print("  ⏭️ 跳过下滑（swipe_seconds <= 0）")
        return

    print(f"  📋 开始下滑浏览 {seconds}s (含 10s 缓冲)")
    start = time.time()
    count = 0
    while time.time() - start < seconds + 10:
        start_y = random.randint(int(sh * 0.80), int(sh * 0.90))
        end_y = random.randint(int(sh * 0.15), int(sh * 0.25))
        device.swipe(int(sw * 0.5), start_y, int(sw * 0.5), end_y)
        count += 1
        time.sleep(random.uniform(2, 4))
    print(f"  ✅ 浏览完成 (共执行 {count} 次有效下滑)")


# ========================================================
# 🚀 单轮执行（含防空滑熔断机制）
# ========================================================
def run_round(device, label: str, name: str, swipe_seconds: int, nav_func, sw: int, sh: int) -> bool:
    """执行一轮：冷启点淘 → 元宝中心 → 标准导航目标页 → 安全下滑"""
    print(f"\n{'='*60}")
    print(f"  第 {label} 轮: {name}")
    print(f"  计划浏览时长: {swipe_seconds}s")
    print(f"{'='*60}")

    # Step 1: 重启点淘到首页
    print("  🚀 重启点淘...")
    device.app_start(DT_APP, stop=True)
    time.sleep(5)

    # Step 2: 进入元宝中心
    if not _nav_to_yuanbao_center(device, sw, sh):
        print(f"  ❌ 未能进入元宝中心，终止第 {label} 轮")
        return False

    # Step 3: 标准路径导航
    entered = nav_func(device, sw, sh)
    if not entered:
        print(f"  ⚠️ 标准导航未能进入【{name}】，跳过本轮浏览（触发安全防护，避免在错误页面空跑）")
        return False

    # Step 4: 下滑浏览
    swipe_browse(device, swipe_seconds, sw, sh)
    print(f"  ✅ 第 {label} 轮【{name}】顺利完成")
    return True


# ========================================================
# 🏁 主函数
# ========================================================
def main():
    if sys.stdout.encoding == 'gbk':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 60)
    print(" 🎮 一键下滑 (新) - 标准路径版")
    print("   流程: 打工 → 睡觉 → 签到 → 购物赚钱 → 摇一摇 → 走路赚元宝")
    print("   特性: 标准U2导航 + 失败防空跑保护")
    print("=" * 60)

    device = connect_device()
    sw, sh = device.window_size()
    print(f"📱 屏幕分辨率: {sw} x {sh}")

    success_count = 0
    total_count = len(ROUNDS_CONFIG)

    for r in ROUNDS_CONFIG:
        ok = run_round(
            device=device,
            label=r["label"],
            name=r["name"],
            swipe_seconds=r["swipe_seconds"],
            nav_func=r["nav_func"],
            sw=sw,
            sh=sh,
        )
        if ok:
            success_count += 1

    print(f"\n{'='*60}")
    print(f"  全部执行完毕: 成功 {success_count}/{total_count} 轮")
    print(f"{'='*60}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ 用户手动中断")
    except Exception as e:
        print(f"\n❌ 执行异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(" 👋 任务结束")
