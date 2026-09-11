"""
一键下滑 自动化脚本
流程：5轮顺序执行，每轮：重启点淘 → 元宝中心 → 导航目标页 → 下滑浏览

轮次顺序:
  1. 打工赚元宝
  2. 睡觉赚元宝
  3. 签到赢元宝（特殊导航：下滑找"今日签到"→"去看看"）
  4. 购物赚钱（特殊导航：固定坐标 → 查看更多）
  5. 摇一摇（特殊导航：点淘鸭家园 → 右滑2次 → OCR找去摇一摇）

配置说明：
  修改 ROUNDS_CONFIG 列表，每个轮次可独立配置：
    - swipe_seconds: 下滑浏览秒数
    - nav_func:     导航函数（接收 device 参数，负责进入对应页面）
"""
import time
import sys
import random

from u2_scanner import connect_device, DT_APP, navigate_chain, u2_click_text, scan_page, find_clickable_with_text
from utils import get_ocr_text_blocks


# ========================================================
# 全局变量
# ========================================================
d = connect_device()
screen_width, screen_height = d.window_size()
print(f"屏幕分辨率: {screen_width} x {screen_height}")


# ========================================================
# 🧭 导航函数库（每个轮次使用不同的导航策略）
# ========================================================

def _nav_to_dagong(device):
    """导航：元宝中心 → 打工赚元宝（文字匹配）"""
    navigate_chain(device, [("进入打工赚元宝", "打工赚元宝")])


def _nav_to_sleep(device):
    """导航：元宝中心 → 睡觉赚元宝（文字匹配）"""
    navigate_chain(device, [("进入睡觉赚元宝", "睡觉赚元宝")])


def _nav_to_signin(device):
    """
    导航：元宝中心 → 签到赢元宝（首次弹窗规避）
    首次进入会弹窗遮挡，需要关闭后重新进入。
    所以进入2次：第一次进→back关闭→第二次进→正常下滑
    """
    for attempt in range(2):
        print(f"  📜 下滑找今日签到...（第{attempt+1}/2次）")

        found = False
        for _ in range(8):
            sign_btn = device(textContains="今日签到")
            if sign_btn.exists(timeout=2):
                try:
                    sign_cx, sign_cy = sign_btn.center()
                    sign_cx, sign_cy = int(sign_cx), int(sign_cy)
                except:
                    continue

                go_btn = device(textContains="去看看")
                if go_btn.exists(timeout=1):
                    try:
                        gx, gy = go_btn.center()
                        gx, gy = int(gx), int(gy)
                    except:
                        gx, gy = 0, 0
                    if abs(gx - sign_cx) > 50 and -20 <= gy - sign_cy <= 200:
                        device.click(gx, gy)
                        time.sleep(3)
                        found = True
                        break

                # 兜底：点签到右侧
                if not found:
                    device.click(sign_cx + 200, sign_cy)
                    time.sleep(3)
                    found = True
                    break

            if found:
                break
            device.swipe(screen_width // 2, int(screen_height * 0.85),
                         screen_width // 2, int(screen_height * 0.2))
            time.sleep(2)

        if not found:
            print("  ⚠️ 未找到今日签到")
            return

        if attempt == 0:
            # 第一次进入：弹窗遮挡，直接关闭退回
            print("  ⏹️ 第一次进入，关闭弹窗退回...")
            for _ in range(3):
                device.press("back")
                time.sleep(1.5)
            time.sleep(2)
        else:
            # 第二次进入：弹窗已消失，正常进入
            print("  ✅ 第二次进入成功，弹窗已清除")


def _nav_to_shop(device):
    """
    导航：元宝中心 → 购物赚钱
    （固定坐标入口 → 找"查看更多"）
    """
    print(f"  点击购物赚钱入口 (934, 1723)...")
    device.click(934, 1723)
    time.sleep(3)

    # 找"查看更多"展开任务列表
    #for b in get_ocr_text_blocks(device):
        #if "查看更多" in b.get("text", ""):
            #print(f"  点击查看更多 @({b['cx']},{b['cy']})")
            #device.click(b["cx"], b["cy"])
            #time.sleep(2)
            #break


def _nav_to_walk(device):
    """导航：元宝中心 → OCR扫描走路赚元宝 → 点击进入"""
    print("  🔍 OCR 查找【走路赚元宝】...")
    entered = False
    for attempt in range(5):
        blocks = get_ocr_text_blocks(device)
        if blocks:
            for b in blocks:
                text = b.get("text", "")
                if "走路赚元宝" in text:
                    print(f"  🎯 点击【{text}】 @({b['cx']},{b['cy']})")
                    device.click(b["cx"], b["cy"])
                    time.sleep(4)
                    entered = True
                    print("  ✅ 已进入走路赚元宝页面")
                    break
        if entered:
            break
        print(f"  ⚠️ 未找到走路赚元宝（第 {attempt+1} 次），重试...")
        time.sleep(1.5)

    if not entered:
        print("  ⚠️ 未能进入走路赚元宝页面，跳过该轮")


def _nav_to_yaoyiyao(device):
    """
    导航：元宝中心 → 点淘鸭家园 → 右滑2次 → OCR找去摇一摇
    （复用点淘鸭摇一摇.py 的导航逻辑，5次 OCR 重试）
    """
    # 固定比例坐标（基于 1264×2780 实测换算）
    DUCK_ENTRY_X_RATIO = 0.77
    DUCK_ENTRY_Y_RATIO = 0.70

    # Step 1: 点击点淘鸭家园
    duck_x = int(screen_width * DUCK_ENTRY_X_RATIO)
    duck_y = int(screen_height * DUCK_ENTRY_Y_RATIO)
    print(f"  点击点淘鸭家园 @({duck_x},{duck_y})...")
    device.click(duck_x, duck_y)
    time.sleep(5)

    # Step 2: 右滑2次到最右边
    print("  右滑2次到最右边...")
    for i in range(2):
        sx = int(screen_width * 0.15)
        ex = int(screen_width * 0.85)
        sy = int(screen_height * 0.50)
        device.swipe(sx, sy, ex, sy, duration=0.3)
        print(f"    第 {i+1}/2 次右滑")
        time.sleep(1.5)
    print("  ✅ 已右滑到最右边")

    # Step 3: OCR找"去摇一摇"并点击（5次重试）
    print("  🔍 OCR 查找【去摇一摇】...")
    entered = False
    for attempt in range(5):
        blocks = get_ocr_text_blocks(device)
        if blocks:
            for b in blocks:
                if "去摇一摇" in b.get("text", ""):
                    print(f"  🎯 点击【{b['text']}】 @({b['cx']},{b['cy']})")
                    device.click(b["cx"], b["cy"])
                    time.sleep(4)
                    entered = True
                    print("  ✅ 已进入摇一摇页面")
                    break
        if entered:
            break
        print(f"  ⚠️ 未找到去摇一摇（第 {attempt+1} 次），重试...")
        time.sleep(1.5)

    if not entered:
        print("  ⚠️ 未能进入摇一摇页面，跳过该轮")


# ========================================================
# 📋 轮次配置（每个轮次独立设置）
# ========================================================
# ✨ 修改以下配置即可调整每步的行为：
#   - swipe_seconds: 下滑浏览秒数
#   - nav_func:      导航函数（定义在上面）
ROUNDS_CONFIG = [
    {
        "label": "1",
        "name": "打工赚元宝",
        "swipe_seconds": 240,
        "nav_func": _nav_to_dagong,
    },
    {
        "label": "2",
        "name": "睡觉赚元宝",
        "swipe_seconds": 230,
        "nav_func": _nav_to_sleep,
    },
    {
        "label": "3",
        "name": "签到赢元宝",
        "swipe_seconds": 240,
        "nav_func": _nav_to_signin,
    },
    {
        "label": "4",
        "name": "购物赚钱",
        "swipe_seconds": 230,
        "nav_func": _nav_to_shop,
    },
    {
        "label": "5",
        "name": "摇一摇",
        "swipe_seconds": 230,
        "nav_func": _nav_to_yaoyiyao,
    },
    {
        "label": "6",
        "name": "走路赚元宝",
        "swipe_seconds": 240,
        "nav_func": _nav_to_walk,
    },
]


# ========================================================
# 下滑浏览
# ========================================================
def swipe_browse(seconds):
    """纯下滑浏览"""
    if seconds <= 0:
        print("  ⏭️ 跳过下滑（swipe_seconds <= 0）")
        return

    print(f"  📋 下滑浏览 {seconds}s")
    sw, sh = screen_width, screen_height
    start = time.time()
    count = 0
    while time.time() - start < seconds + 10:
        d.swipe(int(sw * 0.5), random.randint(int(sh * 0.80), int(sh * 0.90)),
                int(sw * 0.5), random.randint(int(sh * 0.15), int(sh * 0.25)))
        count += 1
        time.sleep(random.uniform(2, 4))
    print(f"  ✅ 浏览完成 ({count}次下滑)")


# ========================================================
# 执行一轮
# ========================================================
def run_round(label, name, swipe_seconds, nav_func):
    """执行一轮：重启点淘 → 元宝中心 → 导航目标页 → 下滑"""
    print(f"\n{'='*60}")
    print(f"  第 {label} 轮: {name}")
    print(f"  下滑时间: {swipe_seconds}s")
    print(f"{'='*60}")

    # Step 1: 重启点淘到首页
    print("  🚀 重启点淘...")
    d.app_start(DT_APP, stop=True)
    time.sleep(5)

    # Step 2: 进入元宝中心
    navigate_chain(d, [("进入元宝中心", "元宝中心")])

    # Step 3: 使用该轮次自己的导航函数进入目标页面
    nav_func(d)

    # Step 4: 下滑浏览
    swipe_browse(swipe_seconds)

    print(f"  ✅ 第 {label} 轮完成")


# ========================================================
# 主函数
# ========================================================
def main():
    if sys.stdout.encoding == 'gbk':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 60)
    print(" 🎮 一键下滑")
    print("   流程: 打工 → 睡觉 → 签到 → 购物赚钱 → 摇一摇 → 走路赚元宝")
    print("   每轮配置如下：")
    for r in ROUNDS_CONFIG:
        print(f"     {r['label']}. {r['name']}: 下滑 {r['swipe_seconds']}s")
    print("=" * 60)

    for r in ROUNDS_CONFIG:
        run_round(
            label=r["label"],
            name=r["name"],
            swipe_seconds=r["swipe_seconds"],
            nav_func=r["nav_func"],
        )

    print(f"\n{'='*60}")
    print(" ✅ 全部完成！")
    print(f"{'='*60}")


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