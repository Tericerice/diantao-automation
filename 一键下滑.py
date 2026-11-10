"""
一键下滑 自动化脚本
流程：6轮顺序执行，每轮：重启点淘 → 元宝中心 → OCR 定位入口 → 下滑浏览

轮次顺序:
  1. 打工赚元宝
  2. 睡觉赚元宝
  3. 签到赢元宝（OCR下滑找"今日签到"→"去看看"）
  4. 购物赚钱（OCR 定位购物入口并校验落地页）
  5. 摇一摇（OCR定位点淘鸭家园 → 右滑2次 → OCR找去摇一摇）
  6. 走路赚元宝（OCR定位入口）

配置说明：
  修改 ROUNDS_CONFIG 列表，每个轮次可独立配置：
    - swipe_seconds: 下滑浏览秒数
    - nav_func:     导航函数（接收 device 参数，负责进入对应页面）
"""
import argparse
import json
import time
from yuanbao_popup import handle_yuanbao_live_popups
import sys
import random
import re

from u2_scanner import connect_device, DT_APP
from utils import get_ocr_text_blocks, get_current_app
from task_checkpoint import run_step

CENTER_OCR_PRE_SCAN_DELAY_SECONDS = 5
CENTER_OCR_SCAN_ATTEMPTS = 3
CENTER_OCR_RETRY_DELAY_SECONDS = 3
CENTER_OCR_CLICK_WAIT_SECONDS = 4
OCR_PRE_SCAN_DELAY_SECONDS = 3
OCR_SCAN_ATTEMPTS = 5
OCR_RETRY_DELAY_SECONDS = 3
OCR_CLICK_WAIT_SECONDS = 5
DUCK_OPEN_WAIT_SECONDS = 7

# Trail e-diantao-151: 校验允许 OCR 抖动与页面滚动；只有离开应用才判跳页。
PAGE_VALIDATION_ATTEMPTS = 4
PAGE_VALIDATION_RETRY_DELAY_SECONDS = 1.5
NAV_PAGE_MARKERS = {
    "打工赚元宝": ("打工赚元宝", "做任务赚元宝", "每日开店赚元宝"),
    "睡觉赚元宝": ("睡觉赚元宝", "睡觉", "做任务赚元宝"),
    "签到赢元宝": ("签到赢元宝", "今日签到", "每日前进赚元宝", "做任务赚元宝"),
    "购物赚钱": ("精选推荐", "做任务领元宝", "快速领", "购物赚钱", "精选宝"),
    "摇一摇": ("摇一摇", "去摇一摇", "摇一摇PK赚元宝"),
    "走路赚元宝": ("走路赚元宝", "做任务赚步数"),
}

# 避开 Android 底部手势区（0.80~1.00）和顶端状态栏；拖动手势用更长
# duration，避免 WebView 商品卡片把短促 swipe 误判成一次点击。
SAFE_SWIPE_START_MIN_RATIO = 0.62
SAFE_SWIPE_START_MAX_RATIO = 0.68
SAFE_SWIPE_END_MIN_RATIO = 0.34
SAFE_SWIPE_END_MAX_RATIO = 0.40
# 导航内部滚动/横滑仍使用短拖动；下滑浏览单独使用更长的拖动时长。
SWIPE_DURATION_SECONDS = 0.55
# Trail e-diantao-169：下滑浏览改为左侧安全边带 + 0.9s 长拖动。历史日志
# 显示 0.55s、右侧 0.84~0.91 的拖动会被直播 H5 商品卡识别成点击并误入
# 「同款好物」；边带避开商品卡点击热区，长拖动确保被识别为滚动。
SWIPE_X_MIN_RATIO = 0.08
SWIPE_X_MAX_RATIO = 0.15
BROWSE_SWIPE_DURATION_SECONDS = 0.9
WRONG_PAGE_MARKERS = (
    "同款好物", "同款低价", "搜索其他心仪好物", "全部同款", "低价同款",
)

# Trail e-diantao-169：导航校验失败的有界重试与错误页恢复上限。
NAV_ATTEMPTS_LIMIT = 2
WRONG_PAGE_MAX_RECOVERIES = 2
WRONG_PAGE_RECOVERY_LIMIT_TOTAL = 3
# 直播 H5 容器：同包 Activity 切换时不能仅凭包名放行，必须结合本轮 marker。
LIVE_H5_ACTIVITY_MARKERS = (
    "browseractivity", "browserupperactivity", "h5.browser",
)


# ========================================================
# 全局变量
# ========================================================
d = connect_device()
screen_width, screen_height = d.window_size()
print(f"屏幕分辨率: {screen_width} x {screen_height}")


# ========================================================
# 🧭 导航函数库（每个轮次使用不同的导航策略）
# ========================================================

def _normalize_ocr_text(value):
    """OCR 文本归一化：忽略空白并统一大小写，兼容活动页文字微调。"""
    return re.sub(r"\s+", "", str(value)).casefold()


def _find_ocr_block(blocks, keywords, *, near=None, max_dy=None):
    """在 OCR 文本块中按关键字查找；near 用于限制同一行的关联入口。"""
    if isinstance(keywords, str):
        keywords = (keywords,)
    needles = tuple(_normalize_ocr_text(k) for k in keywords if str(k).strip())
    for block in blocks or []:
        text = _normalize_ocr_text(block.get("text", ""))
        if not any(needle in text for needle in needles):
            continue
        if near is not None and max_dy is not None:
            try:
                cx, cy = int(block["cx"]), int(block["cy"])
            except (KeyError, TypeError, ValueError):
                continue
            if abs(cx - near[0]) <= 50 or not (-20 <= cy - near[1] <= max_dy):
                continue
        return block
    return None


def _nearby_ocr_text(blocks, target, *, radius=180, limit=6):
    """收集点击目标附近的 OCR 文本，作为“点的是入口而非同名文本”的证据。"""
    try:
        cx, cy = int(target.get("cx")), int(target.get("cy"))
    except (AttributeError, TypeError, ValueError):
        return []
    nearby = []
    for block in blocks or []:
        if block is target:
            continue
        try:
            bx, by = int(block.get("cx")), int(block.get("cy"))
        except (TypeError, ValueError):
            continue
        if abs(bx - cx) <= radius and abs(by - cy) <= radius:
            nearby.append(block.get("text", ""))
    return nearby[:limit]


def _safe_back(device):
    """一次安全回退；不重启应用、不连续按键，避免误操作其他页面。"""
    print("  ↩️ 页面校验失败，执行 1 次安全返回")
    try:
        device.press("back")
    except Exception as exc:
        print(f"  ⚠️ 安全返回失败：{exc}")
        return False
    time.sleep(2)
    return True


def _ocr_blocks(device, context):
    """读取 OCR 文本块；失败时记录真实原因并返回空列表。"""
    try:
        return get_ocr_text_blocks(device)
    except Exception as exc:
        print(f"  ⚠️ {context} OCR 失败：{exc}")
        return []


def _is_live_h5_activity(activity):
    """判断 Activity 是否属于点淘直播 H5 容器（BrowserActivity 等）。"""
    if not activity:
        return False
    needle = str(activity).casefold()
    return any(marker in needle for marker in LIVE_H5_ACTIVITY_MARKERS)


def _wrong_page_in_blocks(blocks):
    """在已读取的 OCR 文本块中识别「同款好物」等错误商品页标记。"""
    for block in blocks or []:
        text = _normalize_ocr_text(block.get("text", ""))
        for marker in WRONG_PAGE_MARKERS:
            if _normalize_ocr_text(marker) in text:
                print(f"  ⚠️ 检测到错误商品页标记：{block.get('text', '')!r}")
                return True
    return False


def _read_current_app(device, context, *, attempts=2):
    """读取前台包名与 Activity；短暂读取失败时有限重试。"""
    package, activity = None, None
    for attempt in range(attempts):
        try:
            package, activity = get_current_app(device)
        except Exception as exc:
            print(f"  ⚠️ {context}页面校验失败：{exc}")
            package, activity = None, None
        if package:
            return package, activity
        if attempt < attempts - 1:
            time.sleep(1)
    return package, activity


def _expected_page_reached(device, markers, *, attempts=PAGE_VALIDATION_ATTEMPTS):
    """确认已进入本轮目标页：必须命中本轮 marker，仅“还在点淘”不算成功。

    Trail e-diantao-169：历史日志显示“仍在点淘 + 4 次 OCR 未命中”仍被放行，
    导致在未确认的页面上开始下滑并误入商品页。现在连续未命中即返回 False，
    由调用方回退并做有界重试；直播 H5 容器（BrowserActivity 等）没有 marker
    时明确判为错误页面。
    """
    last_activity = None
    for attempt in range(1, attempts + 1):
        try:
            package, activity = get_current_app(device)
        except Exception as exc:
            print(f"  ⚠️ 页面校验读取前台应用失败：{exc}")
            package, activity = None, None
        last_activity = activity
        if package and package != DT_APP:
            print(f"  ⚠️ 页面校验失败：前台应用为 {package!r}，预期 {DT_APP!r}")
            return False
        blocks = _ocr_blocks(device, "页面校验")
        matched = _find_ocr_block(blocks, markers)
        if matched:
            print(f"  ✅ OCR 确认预期页面：{matched.get('text', '')!r}")
            return True
        print(
            f"  ⚠️ 预期页面文字未命中（第 {attempt}/{attempts} 次，"
            f"Activity={activity!r}）")
        if attempt < attempts:
            time.sleep(PAGE_VALIDATION_RETRY_DELAY_SECONDS)
    if _is_live_h5_activity(last_activity):
        print("  ⚠️ 直播 H5 容器内未命中本轮任务标记，判定为错误页面")
    print(f"  ⚠️ 连续 {attempts} 次未命中本轮预期文字，导航未到达目标页")
    return False


def _ensure_yuanbao_center(device):
    """导航重试前回到元宝中心；已在中心时不再重复点击。"""
    if _is_yuanbao_center_ocr(device):
        return True
    return _enter_yuanbao_center_ocr(device)


def _navigate_and_verify(device, name, click_target,
                         *, max_attempts=NAV_ATTEMPTS_LIMIT):
    """统一导航后校验：失败时安全回退、回到元宝中心，有界重试后仍失败才跳过。"""
    markers = NAV_PAGE_MARKERS.get(name, (name,))
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"  🔁 第 {attempt}/{max_attempts} 次重新导航【{name}】")
            if not _ensure_yuanbao_center(device):
                print("  ⚠️ 重试前未能回到元宝中心，停止重试")
                break
        if not click_target(device):
            print(f"  ⚠️ 未能通过 OCR 进入【{name}】（第 {attempt}/{max_attempts} 次）")
            continue
        if _expected_page_reached(device, markers):
            return True
        _safe_back(device)
        print(
            f"  ⚠️ 导航后未确认【{name}】预期页面"
            f"（第 {attempt}/{max_attempts} 次），已安全回退")
    print(f"  ⚠️ 导航后未确认【{name}】预期页面，跳过本轮")
    return False


def _is_yuanbao_center_ocr(device):
    """用 OCR 判断当前是否已在元宝中心页面。"""
    try:
        blocks = get_ocr_text_blocks(device)
    except Exception as exc:
        print(f"  ⚠️ OCR 检查元宝中心失败：{exc}")
        return False

    center_markers = ("我的元宝", "提现", "兑红包")
    return any(
        marker in block.get("text", "")
        for block in blocks
        for marker in center_markers
    )


def _enter_yuanbao_center_ocr(device):
    """等待首页稳定后，用 OCR 查找并点击元宝中心。"""
    print(
        f"  ⏳ 等待首页稳定 {CENTER_OCR_PRE_SCAN_DELAY_SECONDS}s，"
        "再用 OCR 查找元宝中心..."
    )
    time.sleep(CENTER_OCR_PRE_SCAN_DELAY_SECONDS)

    for scan_index in range(1, CENTER_OCR_SCAN_ATTEMPTS + 1):
        try:
            blocks = get_ocr_text_blocks(device)
        except Exception as exc:
            blocks = []
            print(f"  ⚠️ 元宝中心 OCR 第 {scan_index} 次扫描失败：{exc}")

        target = next(
            (b for b in blocks if "元宝中心" in b.get("text", "")),
            None,
        )
        if target:
            target_x, target_y = int(target["cx"]), int(target["cy"])
            print(f"  🎯 OCR 点击【元宝中心】@({target_x},{target_y})")
            device.click(target_x, target_y)
            time.sleep(CENTER_OCR_CLICK_WAIT_SECONDS)
            return handle_yuanbao_live_popups(device)

        print(
            f"  ⚠️ OCR 未找到【元宝中心】（第 "
            f"{scan_index}/{CENTER_OCR_SCAN_ATTEMPTS} 次）"
        )
        if scan_index < CENTER_OCR_SCAN_ATTEMPTS:
            time.sleep(CENTER_OCR_RETRY_DELAY_SECONDS)

    return False


def _ocr_click_target(device, keyword, label=None, attempts=OCR_SCAN_ATTEMPTS,
                      click_wait=OCR_CLICK_WAIT_SECONDS):
    """OCR 查找入口文本并点击其识别坐标。"""
    label = label or keyword
    print(f"  🔍 OCR 查找【{label}】...")
    time.sleep(OCR_PRE_SCAN_DELAY_SECONDS)

    for attempt in range(1, attempts + 1):
        try:
            blocks = get_ocr_text_blocks(device)
        except Exception as exc:
            blocks = []
            print(f"  ⚠️ OCR 扫描【{label}】失败：{exc}")

        normalized_keyword = _normalize_ocr_text(keyword)
        target = next(
            (
                b for b in blocks
                if normalized_keyword in _normalize_ocr_text(b.get("text", ""))
            ),
            None,
        )
        if target:
            target_x, target_y = int(target["cx"]), int(target["cy"])
            # 记录命中文本、坐标与附近文本；落地页校验失败时可回溯是否
            # 点击了页面其他同名文本，而不是真正的入口卡片/按钮。
            nearby = _nearby_ocr_text(blocks, target)
            print(f"  🎯 OCR 点击【{target['text']}】@({target_x},{target_y})")
            print(f"  🧾 点击证据：text={target.get('text', '')!r}, "
                  f"xy=({target_x},{target_y}), nearby={nearby!r}")
            device.click(target_x, target_y)
            time.sleep(click_wait)
            return True

        print(f"  ⚠️ OCR 未找到【{label}】（第 {attempt}/{attempts} 次）")
        if attempt < attempts:
            time.sleep(OCR_RETRY_DELAY_SECONDS)

    print(f"  ⚠️ 未能通过 OCR 进入【{label}】")
    return False


def _nav_to_dagong(device):
    """OCR 查找并点击打工赚元宝入口，校验落地页。"""
    return _navigate_and_verify(
        device, "打工赚元宝",
        lambda dev: _ocr_click_target(dev, "打工赚元宝"),
    )


def _nav_to_sleep(device):
    """OCR 查找并点击睡觉赚元宝入口，校验落地页。"""
    return _navigate_and_verify(
        device, "睡觉赚元宝",
        lambda dev: _ocr_click_target(dev, "睡觉赚元宝"),
    )


def _nav_to_signin(device):
    """OCR 找今日签到 + 同行动作按钮；找不到按钮绝不盲点右侧广告。"""
    print("  📜 下滑找今日签到...")
    time.sleep(OCR_PRE_SCAN_DELAY_SECONDS)

    def click_signin(dev):
        for scan_index in range(1, 9):
            try:
                blocks = get_ocr_text_blocks(dev)
            except Exception as exc:
                blocks = []
                print(f"  ⚠️ 签到 OCR 扫描失败：{exc}")

            sign_block = _find_ocr_block(blocks, "今日签到")
            if sign_block:
                sign_x, sign_y = int(sign_block["cx"]), int(sign_block["cy"])
                go_block = _find_ocr_block(
                    blocks, ("去看看", "去签到", "立即签到"),
                    near=(sign_x, sign_y), max_dy=200,
                )
                if not go_block:
                    print("  ⚠️ 找到【今日签到】但未找到同行动作按钮，跳过本轮")
                    return False
                target_x, target_y = int(go_block["cx"]), int(go_block["cy"])
                print(f"  🎯 OCR 点击【{go_block.get('text', '')}】@({target_x},{target_y})")
                dev.click(target_x, target_y)
                time.sleep(OCR_CLICK_WAIT_SECONDS)
                return True

            print(f"  ⚠️ OCR 未找到【今日签到】（第 {scan_index}/8 次）")
            dev.swipe(screen_width // 2, int(screen_height * 0.70),
                      screen_width // 2, int(screen_height * 0.25),
                      duration=SWIPE_DURATION_SECONDS)
            time.sleep(OCR_RETRY_DELAY_SECONDS)

        print("  ⚠️ 未找到今日签到")
        return False

    return _navigate_and_verify(device, "签到赢元宝", click_signin)


def _nav_to_shop(device):
    """OCR 定位购物入口并校验落地页，替代会命中广告的固定坐标。"""
    print("  🔍 OCR 查找购物入口...")

    def click_shop(dev):
        for attempt in range(1, OCR_SCAN_ATTEMPTS + 1):
            try:
                blocks = get_ocr_text_blocks(dev)
            except Exception as exc:
                blocks = []
                print(f"  ⚠️ 购物入口 OCR 扫描失败：{exc}")

            # 当前活动页实测文字：额外福利 / 查看3个精选宝贝 / 去完成；
            # 历史/回退文案：购物赚钱、做任务领元宝。优先匹配入口文本，
            # 并只点击与入口同一行的动作按钮，绝不点击固定坐标。
            entry = _find_ocr_block(
                blocks, ("购物赚钱", "查看3个精选", "精选宝", "做任务领元宝"))
            action = _find_ocr_block(blocks, ("去完成", "去逛逛", "去购物"))
            if entry and action:
                try:
                    ex, ey = int(entry["cx"]), int(entry["cy"])
                    ax, ay = int(action["cx"]), int(action["cy"])
                except (KeyError, TypeError, ValueError):
                    print("  ⚠️ 购物入口 OCR 坐标无效，跳过本轮")
                    return False
                if abs(ay - ey) > 180:
                    print("  ⚠️ 购物入口与动作按钮不在同一区域，跳过本轮")
                    return False
                print(f"  🎯 OCR 购物入口【{entry.get('text', '')}】@({ex},{ey})")
                print(f"  🎯 OCR 点击【{action.get('text', '')}】@({ax},{ay})")
                dev.click(ax, ay)
                time.sleep(OCR_CLICK_WAIT_SECONDS)
                return True

            print(f"  ⚠️ OCR 未找到购物入口（第 {attempt}/{OCR_SCAN_ATTEMPTS} 次）")
            if attempt < OCR_SCAN_ATTEMPTS:
                time.sleep(OCR_RETRY_DELAY_SECONDS)
        print("  ⚠️ 未能通过 OCR 进入购物赚钱")
        return False

    return _navigate_and_verify(device, "购物赚钱", click_shop)


def _nav_to_walk(device):
    """OCR 查找并点击走路赚元宝入口，校验落地页。"""
    return _navigate_and_verify(
        device, "走路赚元宝",
        lambda dev: _ocr_click_target(dev, "走路赚元宝"),
    )


def _nav_to_yaoyiyao(device):
    """
    导航：元宝中心 → 点淘鸭家园 → 右滑2次 → OCR找去摇一摇
    （复用点淘鸭摇一摇.py 的导航逻辑，5次 OCR 重试）

    Trail e-diantao-169：整条导航链封装为 click_target，落点校验失败时
    由 _navigate_and_verify 回到元宝中心后重新执行完整导航，而不是只重试
    最后一步或直接跳过。
    """
    def enter_yaoyiyao(dev):
        # Step 1: OCR 定位并点击点淘鸭家园
        if not _ocr_click_target(dev, "点淘鸭家园", "点淘鸭家园"):
            print("  ⚠️ 未能进入点淘鸭家园，跳过该轮")
            return False

        print(f"  ⏳ 等待家园加载 {DUCK_OPEN_WAIT_SECONDS}s...")
        time.sleep(DUCK_OPEN_WAIT_SECONDS)

        # Step 2: 右滑2次找摇一摇入口
        for i in range(2):
            print(f"  👉 第 {i+1} 次右滑找摇一摇...")
            dev.swipe(int(screen_width * 0.2), int(screen_height * 0.5),
                      int(screen_width * 0.8), int(screen_height * 0.5),
                      duration=SWIPE_DURATION_SECONDS)
            time.sleep(2)

        for attempt in range(1, 6):
            blocks = _ocr_blocks(dev, "摇一摇")
            target = _find_ocr_block(blocks, ("去摇一摇", "摇一摇"))
            if target:
                target_x, target_y = int(target["cx"]), int(target["cy"])
                nearby = _nearby_ocr_text(blocks, target)
                print(f"  🎯 OCR 点击【{target.get('text', '')}】@({target_x},{target_y})")
                print(f"  🧾 点击证据：nearby={nearby!r}")
                dev.click(target_x, target_y)
                time.sleep(OCR_CLICK_WAIT_SECONDS)
                return True

            print(f"  ⚠️ OCR 未找到【去摇一摇】（第 {attempt}/5 次）")
            if attempt < 5:
                time.sleep(OCR_RETRY_DELAY_SECONDS)

        print("  ⚠️ 未能进入摇一摇页面")
        _safe_back(dev)
        return False

    return _navigate_and_verify(device, "摇一摇", enter_yaoyiyao)


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
def _wrong_page_detected(device):
    """识别误入的「同款好物」商品页；OCR 不可用时不臆判。"""
    blocks = _ocr_blocks(device, "商品页识别")
    return _wrong_page_in_blocks(blocks)


def _recover_after_wrong_page(device, expected_markers,
                              *, max_attempts=WRONG_PAGE_MAX_RECOVERIES):
    """有界恢复：安全返回后确认回到本轮任务页；恢复失败达到上限才放弃。"""
    for attempt in range(1, max_attempts + 1):
        _safe_back(device)
        package, activity = _read_current_app(device, "恢复后")
        if package != DT_APP:
            print(
                f"  ⚠️ 恢复后前台应用为 {package!r}，预期 {DT_APP!r}"
                f"（第 {attempt}/{max_attempts} 次）")
            return False
        blocks = _ocr_blocks(device, "恢复后")
        if _wrong_page_in_blocks(blocks):
            print(f"  ⚠️ 回退后仍在错误商品页（第 {attempt}/{max_attempts} 次）")
            continue
        if expected_markers and _find_ocr_block(blocks, expected_markers):
            print("  ✅ 已回到任务页，继续剩余下滑")
            return True
        print(
            f"  ⚠️ 回退后未确认任务标记（第 {attempt}/{max_attempts} 次，"
            f"Activity={activity!r}）")
    return False


def swipe_browse(seconds, expected_markers=None):
    """保留入口导航后的下滑浏览；错误页有界恢复，恢复失败才判本轮失败。"""
    if seconds <= 0:
        print("  ⏭️ 跳过下滑（swipe_seconds <= 0）")
        return True

    print(f"  📋 下滑浏览 {seconds}s")
    sw, sh = screen_width, screen_height
    expected_markers = tuple(expected_markers or ())

    expected_package, expected_activity = _read_current_app(d, "下滑前", attempts=3)
    if expected_package != DT_APP:
        print("  ⚠️ 下滑前未确认在点淘，跳过本轮")
        return False

    # 下滑前先确认页面：错误商品页或“直播 H5 容器 + 无任务标记”都要先
    # 返回任务页，绝不带着错误页面继续下滑。
    blocks = _ocr_blocks(d, "下滑前")
    wrong_before = _wrong_page_in_blocks(blocks)
    marker_before = _find_ocr_block(blocks, expected_markers) if expected_markers else None
    if wrong_before or (_is_live_h5_activity(expected_activity) and not marker_before):
        print("  ⚠️ 下滑前页面不是本轮任务页，先回退恢复")
        if not _recover_after_wrong_page(d, expected_markers):
            print("  ⚠️ 下滑前错误页恢复失败，跳过本轮")
            return False
        expected_package, expected_activity = _read_current_app(d, "恢复后")

    start = time.time()
    count = 0
    recoveries = 0
    while time.time() - start < seconds + 10:
        start_y = random.randint(
            int(sh * SAFE_SWIPE_START_MIN_RATIO),
            int(sh * SAFE_SWIPE_START_MAX_RATIO))
        end_y = random.randint(
            int(sh * SAFE_SWIPE_END_MIN_RATIO),
            int(sh * SAFE_SWIPE_END_MAX_RATIO))
        # 起点放在左侧安全边带，避开商品卡片点击热区；0.9s 长拖动确保
        # WebView 将其识别为滚动而不是一次点击。
        swipe_x = random.randint(int(sw * SWIPE_X_MIN_RATIO),
                                int(sw * SWIPE_X_MAX_RATIO))
        d.swipe(swipe_x, start_y, swipe_x, end_y,
                duration=BROWSE_SWIPE_DURATION_SECONDS)
        count += 1
        time.sleep(random.uniform(2, 4))

        package, activity = _read_current_app(d, "下滑后")
        if package != expected_package:
            print(
                f"  ⚠️ 下滑后前台应用变为 {package!r}，预期 {expected_package!r}，"
                "停止本轮下滑")
            _safe_back(d)
            return False

        blocks = _ocr_blocks(d, "下滑后")
        wrong_after = _wrong_page_in_blocks(blocks)
        marker_after = _find_ocr_block(blocks, expected_markers) if expected_markers else None
        if wrong_after or (_is_live_h5_activity(activity) and not marker_after):
            reason = ("误入「同款好物」商品页" if wrong_after
                      else "滑入直播 H5 容器且任务标记消失")
            print(f"  ⚠️ 下滑后{reason}，尝试回退任务页")
            if (recoveries >= WRONG_PAGE_RECOVERY_LIMIT_TOTAL
                    or not _recover_after_wrong_page(d, expected_markers)):
                print("  ⚠️ 错误页恢复失败达到上限，停止本轮下滑")
                return False
            recoveries += 1
            expected_package, expected_activity = _read_current_app(d, "恢复后")
            continue
        if activity != expected_activity:
            print(f"  ↪️ 同包页面切换：{activity!r}（任务标记仍在，继续下滑）")
        expected_activity = activity

    print(f"  ✅ 浏览完成 ({count}次下滑)")
    return True


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
    if not _enter_yuanbao_center_ocr(d):
        print("  ⚠️ 元宝中心导航或活动弹窗未完成，停止本轮")
        return False

    # Step 3: 使用该轮次自己的导航函数进入目标页面
    if not nav_func(d):
        reason = f"第 {label} 轮【{name}】导航未确认"
        print(f"  ⚠️ {reason}，跳过本轮下滑")
        print(json.dumps({"event": "round_skipped", "round": label,
                          "name": name, "reason": reason}, ensure_ascii=False), flush=True)
        return False

    # Step 4: 下滑浏览（携带本轮预期页面标记，误跳立即停止）
    result = swipe_browse(swipe_seconds, NAV_PAGE_MARKERS.get(name, (name,)))
    if not result:
        reason = f"第 {label} 轮【{name}】下滑未完成"
        print(f"  ⚠️ {reason}，不计为成功")
        print(json.dumps({"event": "round_failed", "round": label,
                          "name": name, "reason": reason}, ensure_ascii=False), flush=True)
        return False

    print(f"  ✅ 第 {label} 轮完成")
    return True


# ========================================================
# 主函数
# ========================================================
def _round_choices():
    return "、".join(
        f"{r['label']}={r['name']}" for r in ROUNDS_CONFIG
    )


def main():
    if sys.stdout.encoding == 'gbk':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--round", type=int, choices=range(1, len(ROUNDS_CONFIG) + 1),
        help=f"只执行指定轮次（{_round_choices()}）；不传则执行全部轮次",
    )
    args = parser.parse_args()
    rounds = [
        r for r in ROUNDS_CONFIG
        if args.round is None or int(r["label"]) == args.round
    ]

    print("=" * 60)
    print(" 🎮 一键下滑")
    print("   流程: 打工 → 睡觉 → 签到 → 购物赚钱 → 摇一摇 → 走路赚元宝")
    print("   每轮配置如下：")
    for r in rounds:
        print(f"     {r['label']}. {r['name']}: 下滑 {r['swipe_seconds']}s")
    print("=" * 60)

    failed_rounds = []
    for r in rounds:
        ok = run_step(
            f"swipe-{r['label']}", r["name"],
            run_round,
            r["label"], r["name"], r["swipe_seconds"], r["nav_func"],
        )
        if not ok:
            failed_rounds.append(f"{r['label']}={r['name']}")
    if failed_rounds:
        print(f"FAILED_ROUNDS: {','.join(failed_rounds)}", flush=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
