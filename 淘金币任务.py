"""
淘金币任务自动化（U2 Hierarchy 版）
路径：首页淘金币 → 固定坐标点"赚更多金币" → 进入任务列表 → 扫描执行

布局说明（以"更多专享福利"为分割线）：
┌─ 上半区（图像任务区）：左侧任务名 + 右侧金币圆形带数字 → 点击金币圆形区域
├─ 更多专享福利（分割线）
└─ 下半区（类点淘区）：左侧名称 + 右侧"去完成"按钮 → 按名称确定类型

任务类型：浏览类 / 直播类 / 视频类 / 点击3次 / 跳转类（特殊处理）
"""
import time
import re
import os
import sys

# 强制 UTF-8 输出
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import connect_device, get_current_app, TB_APP, DT_APP, TMALL_APP
from u2_scanner import (
    scan_page, execute_live_task, execute_video_task,
    handle_guess_price_game, back_to_task, is_blacklisted, u2_click_text,
)


# ========================================================
# 全局配置
# ========================================================
d = connect_device()
screen_width, screen_height = d.window_size()
print(f"屏幕分辨率: {screen_width} x {screen_height}")

ENTER_TASK_BTN = (639, 751)  # 固定坐标：首页"赚更多金币"

# 任务类型关键词映射
KEYWORD_TASK_TYPE = {
    "猜价格": "guess_price",
    "浏览": "browse",
    "精选推荐": "browse",
    "猜你喜欢": "browse",
    "省钱": "browse",
    "上新好物": "browse",
    "签到": "browse",
    "查看": "browse",
    "看视频": "video",
    "视频": "video",
    "直播": "live",
    "点击": "click_three",
}

# "去完成"按钮类关键词
DONE_BTN_TEXTS = ["去完成", "去浏览", "去观看", "去参与", "去领取", "立即参与", "立即领取"]
JUMP_DONE_TEXTS = ["去逛逛", "逛一逛", "去逛", "逛逛"]

# 内部 App（跳转类不处理外部 App）
INTERNAL_APPS = [TB_APP, DT_APP, TMALL_APP]


# ========================================================
# 首页导航
# ========================================================

def navigate_to_task_list():
    """首页 → 点击固定坐标进入任务列表页"""
    print(f"\n  点击【赚更多金币】@({ENTER_TASK_BTN[0]}, {ENTER_TASK_BTN[1]})")
    d.click(ENTER_TASK_BTN[0], ENTER_TASK_BTN[1])
    time.sleep(5)
    return True


# ========================================================
# 任务列表解析
# ========================================================

def find_split_y(nodes):
    """找"更多专享福利"Y坐标（分割线）"""
    for n in nodes:
        text = n.get("text", "")
        if "更多专享福利" in text:
            print(f"  📐 分割线【更多专享福利】@Y={n['cy']}")
            return n["cy"]
    return None


def find_progress_nodes(nodes, split_y):
    """
    上半区：找圆形金币图案 → 表示"可点击"的图像任务入口
    策略：在上半区找 ImageView 或可点击节点，其右半部分 X > 屏幕60% 且 Y 对应任务行
    返回 [{"task_name": str, "cx": int, "cy": int}, ...]
    """
    upper = [n for n in nodes if n["cy"] < split_y and n.get("text", "").strip()]
    screen_w, screen_h = d.window_size()

    # 找右侧金币/圆形控件：可点击，且 X 在右侧 60%-95% 区域
    # 典型特征：资源 ID 含 coin/right_btn/gold，或 text 为数字
    coin_regions = []
    for n in upper:
        text = n.get("text", "").strip()
        rid = n.get("resource_id", "")
        cls = n.get("class", "")

        # 判断是否为金币按钮：可点击、在右侧、短数字文本
        is_right_side = n["cx"] > int(screen_w * 0.55)
        if not is_right_side:
            continue

        # 条件1：text 是纯数字（金币的数字）
        is_coin_digit = text.isdigit() and len(text) <= 4
        # 条件2：text 是分数格式 数字/数字
        is_progress = bool(re.match(r'^\d+/\d+$', text))
        # 条件3：resource_id 含 coin 关键词
        is_coin_res = "coin" in rid.lower() or "gold" in rid.lower() or "right" in rid.lower()
        # 条件4：ImageView + content_desc
        is_image_coin = ("ImageView" in cls) and ("金币" in n.get("content_desc", "") or n.get("content_desc", "").isdigit())

        if not (is_coin_digit or is_progress or is_coin_res or is_image_coin):
            continue

        # 找到该行左边的任务名
        task_name = ""
        same_row = [nb for nb in upper if abs(nb["cy"] - n["cy"]) < 60 and nb["cx"] < n["cx"]]
        same_row.sort(key=lambda x: x["cx"], reverse=True)

        for c in same_row:
            t = c["text"]
            if t in ("额外得", "元宝", "金币", "奖励"):
                continue
            if re.match(r'^\d+/\d+$', t.strip()):
                continue
            if t.isdigit() and len(t) <= 4:
                continue
            if len(t) < 2:
                continue
            task_name = t
            break
        if not task_name and same_row:
            task_name = same_row[0]["text"]
        if not task_name:
            continue

        if is_blacklisted(task_name):
            continue

        coin_regions.append((task_name, n["cx"], n["cy"]))

    return coin_regions


def find_done_button_tasks(nodes, split_y):
    """
    下半区：找"去完成"类按钮 → 上方找任务名
    返回 [{"task_name": str, "cx": int, "cy": int, "click_text": str}, ...]
    """
    # 如果没有分割线，所有节点都算下半区
    if split_y:
        lower = [n for n in nodes if n["cy"] > split_y + 30]
    else:
        lower = nodes[:]

    results = []
    for n in lower:
        text = n.get("text", "").strip()
        if not text:
            continue

        # 判断是否为"去完成"类按钮
        is_done_btn = any(kw == text or kw in text for kw in DONE_BTN_TEXTS)
        is_jump_btn = any(kw in text for kw in JUMP_DONE_TEXTS)
        if not (is_done_btn or is_jump_btn):
            continue

        # 找该按钮上方的任务名（垂直距离 250px 内）
        above_texts = []
        for nb in lower:
            if nb is n:
                continue
            if nb["cy"] >= n["cy"]:
                continue
            vd = n["cy"] - nb["cy"]
            if vd > 250:
                continue
            if abs(nb["cx"] - n["cx"]) > 80:
                continue
            t = nb.get("text", "").strip()
            if t and t not in DONE_BTN_TEXTS + JUMP_DONE_TEXTS and len(t) >= 2:
                above_texts.append((vd, t))

        above_texts.sort(key=lambda x: x[0])
        task_name = above_texts[0][1] if above_texts else text

        if is_blacklisted(task_name):
            continue

        # 确定点击类型
        if is_jump_btn:
            click_type = "jump"
        else:
            click_type = "done"

        results.append((task_name, n["cx"], n["cy"], text, click_type))

    # 去重
    seen = set()
    unique = []
    for r in results:
        key = (r[2] // 20, r[1] // 20)  # (cy_group, cx)
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique


def match_task_type(task_name):
    """任务名 → 任务类型"""
    for kw, tt in KEYWORD_TASK_TYPE.items():
        if kw in task_name:
            return tt
    # 如果包含跳转关键词
    if any(kw in task_name for kw in ["去逛逛", "逛一逛", "去逛", "逛逛"]):
        return "jump"
    # 默认：如果名称含"元宝"或"金币"则跳过
    if "元宝" in task_name or "金币" in task_name:
        return "skip"
    return "browse"  # 默认尝试浏览


def parse_task_list(nodes):
    """
    统一解析任务列表
    返回 [{"type": str, "name": str, "cx": int, "cy": int, ...}, ...]
    """
    split_y = find_split_y(nodes)
    results = []

    if split_y:
        # 上半区：金币圆形任务
        coins = find_progress_nodes(nodes, split_y)
        for (task_name, cx, cy) in coins:
            tt = match_task_type(task_name)
            if tt == "skip":
                continue
            results.append({
                "type": tt,
                "name": task_name,
                "cx": cx,
                "cy": cy,
                "click_type": "coin",
            })

        # 下半区：去完成按钮
        done_btns = find_done_button_tasks(nodes, split_y)
        for (task_name, cx, cy, click_text, click_type) in done_btns:
            tt = match_task_type(task_name)
            if tt == "skip":
                continue
            results.append({
                "type": tt,
                "name": task_name,
                "cx": cx,
                "cy": cy,
                "click_text": click_text,
                "click_type": click_type,
            })

        if coins:
            print(f"  🏞️ 上半区图像任务: {len(coins)} 个")
        if done_btns:
            print(f"  📋 下半区去完成: {len(done_btns)} 个")

    else:
        # 无分割线 → 全部按去完成按钮处理
        done_btns = find_done_button_tasks(nodes, 0)
        for (task_name, cx, cy, click_text, click_type) in done_btns:
            tt = match_task_type(task_name)
            if tt == "skip":
                continue
            results.append({
                "type": tt,
                "name": task_name,
                "cx": cx,
                "cy": cy,
                "click_text": click_text,
                "click_type": click_type,
            })
        print(f"  ⚠️ 无分割线，找到 {len(done_btns)} 个去完成按钮")

    return results


# ========================================================
# 任务执行
# ========================================================

def browse_loop(duration):
    """浏览任务：下滑停留"""
    start = time.time()
    while time.time() - start < duration:
        d.swipe(screen_width // 2, int(screen_height * 0.7),
                screen_width // 2, int(screen_height * 0.3))
        time.sleep(5)


def exec_task(task_def):
    """执行一个任务"""
    tt = task_def["type"]
    task_name = task_def["name"]
    cx, cy = task_def["cx"], task_def["cy"]
    click_type = task_def.get("click_type", "done")
    click_text = task_def.get("click_text", "")

    print(f"\n  ▶️ [{tt}] {task_name} @({cx},{cy})")

    # ── 猜价格 ──
    if tt == "guess_price":
        d.click(cx, cy)
        time.sleep(3)
        handle_guess_price_game(d)
        return True

    # ── 直播 ──
    elif tt == "live":
        d.click(cx, cy)
        time.sleep(3)
        execute_live_task(d, task_name, cx, cy)
        return True

    # ── 视频 ──
    elif tt == "video":
        d.click(cx, cy)
        time.sleep(3)
        execute_video_task(
            d, task_name, cx, cy,
            verify_media_page=True,
        )
        return True

    # ── 点击3次 ──
    elif tt == "click_three":
        d.click(cx, cy)
        time.sleep(3)
        # 点击三次执行：快速点击三个不同位置
        for i in range(3):
            d.click(screen_width // 2, screen_height // 2 + i * 100)
            time.sleep(1.5)
        time.sleep(5)
        return True

    # ── 跳转 ──
    elif tt == "jump":
        print(f"  🦘 跳转类任务")
        d.click(cx, cy)
        time.sleep(5)
        pkg, _ = get_current_app(d)
        print(f"  📱 当前 App: {pkg}")
        if pkg in INTERNAL_APPS:
            # 内部跳转：直接回退即可
            time.sleep(5)
            d.press("back")
            time.sleep(2)
            return True
        else:
            # 外部 App
            time.sleep(3)
            d.press("back")
            time.sleep(2)
            d.press("back")
            time.sleep(1.5)
            return False

    # ── 浏览（默认） ──
    else:
        d.click(cx, cy)
        time.sleep(3)
        m = re.search(r"(\d+)\s*秒", task_name)
        duration = int(m.group(1)) if m else 60
        print(f"  🎯 浏览 {duration}s")
        browse_loop(duration)
        return True

    return False


def back_to_task_page():
    """返回任务列表页"""
    for _ in range(5):
        try:
            if d(textContains="去完成").exists(timeout=1) or \
               d(textContains="更多专享福利").exists(timeout=1):
                return True
        except:
            pass
        d.press("back")
        time.sleep(1.5)
    return True


# ========================================================
# 主流程
# ========================================================

def main():
    print("=" * 50)
    print(" 淘金币任务自动化（U2 Hierarchy 版）")
    print("=" * 50)

    # 导航：首页 → 任务列表
    if not navigate_to_task_list():
        input("  ⏸️ 请手动进入任务列表页后按 Enter 继续...")

    total = 0
    empty_times = 0

    while True:
        print(f"\n🔍 扫描任务列表... (已做{total}个)")

        # 用 U2 dump_hierarchy 扫描（不会关闭覆盖层）
        nodes = scan_page(d)
        if not nodes:
            empty_times += 1
            if empty_times >= 3:
                print("  ✅ 多次无结果，结束")
                break
            print(f"  ⚠️ 空结果（第{empty_times}次），下滑")
            d.swipe(screen_width // 2, int(screen_height * 0.7),
                    screen_width // 2, int(screen_height * 0.3))
            time.sleep(2)
            continue

        tasks = parse_task_list(nodes)

        if not tasks:
            empty_times += 1
            if empty_times >= 3:
                print("  ✅ 无可用任务，结束")
                break
            print(f"  ⚠️ 无任务（第{empty_times}次），下滑")
            d.swipe(screen_width // 2, int(screen_height * 0.7),
                    screen_width // 2, int(screen_height * 0.3))
            time.sleep(2)
            continue

        empty_times = 0
        # 只执行第一个（然后重新扫描）
        print(f"  🎯 本轮 {len(tasks)} 个可见任务")
        task_def = tasks[0]
        print(f"    执行: [{task_def['type']}] {task_def['name']}")

        try:
            ok = exec_task(task_def)
        except Exception as e:
            print(f"  ❌ {e}")
            import traceback
            traceback.print_exc()
            ok = False

        total += 1

        # 返回任务列表
        back_to_task_page()

    print(f"\n📊 共完成 {total} 个任务")
    try:
        from utils import show_today_summary
        show_today_summary()
    except:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ 手动中断")
    except Exception as e:
        print(f"\n❌ 异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(" 👋 程序结束")
