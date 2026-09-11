"""
========================================================
纯 U2 通用扫描框架（零 OCR）
仿 2026淘宝618.py 写法，适配点淘 WebView 场景
========================================================
"""
import time
import re
import random
import math
import os
import cv2
import numpy as np
from xml.etree import ElementTree
import uiautomator2 as u2
from utils import click_u2_control
from utils import pause_global_watcher, resume_global_watcher


# ========================================================
# 包名常量
# ========================================================
DT_APP = "com.taobao.live"


# ========================================================
# 设备连接
# ========================================================
def get_connected_devices():
    import subprocess
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
        output = result.stdout
        devices = []
        for line in output.splitlines():
            if line.strip() == "" or line.startswith("List of devices attached"):
                continue
            match = re.match(r"^([^\s]+)\s+device$", line)
            if match:
                devices.append(match.group(1))
        return devices
    except:
        return []


def select_device():
    devices = get_connected_devices()
    if not devices:
        raise Exception("未检测到任何连接的安卓设备")

    # 优先选择普通 ADB TCP 连接（排除 TLS 无线调试的 mDNS 地址）
    preferred = [d for d in devices if "_adb-tls" not in d and ".tcp" not in d.split("_")[-1:]]
    if preferred:
        # 有可控选项时，以此为准
        usable = preferred
    else:
        usable = devices

    if len(usable) == 1:
        print(f"自动选择设备: {usable[0]}")
        return usable[0]

    print("当前连接多个设备，请输入要执行的设备序号：")
    for i, dev in enumerate(usable, 1):
        print(f"  {i}: {dev}")
    # 无终端环境（pythonw）下 input() 会抛 EOFError，自动选第一个可用设备
    try:
        choice = input("请输入设备序号：")
        index = int(choice) - 1
        if 0 <= index < len(usable):
            return usable[index]
        print(f"输入错误，自动选择第一个可用设备")
        return usable[0]
    except (EOFError, OSError):
        print(f"无终端输入，自动选择第一个可用设备: {usable[0]}")
        return usable[0]
    except ValueError:
        print(f"输入错误，自动选择第一个可用设备: {usable[0]}")
        return usable[0]


def connect_device():
    """连接设备 + 启动全局弹窗监控（纯 U2，不启动 OCR）"""
    selected = select_device()
    d = u2.connect(selected)
    print(f"[OK] 已连接设备：{selected}")

    # 强制关闭 u2 触摸调试覆盖层（若有），否则会挡住所有 UI 内容
    # 特征：屏幕顶部显示 P:0/1, dx:0.0, dY:0.0, Xv:0.0, Yv:0.0, Prs, Size 等调试数据
    try:
        d.settings["uiautomator"] = {}
        print(f"  [设置] 已关闭 uiautomator 调试覆盖")
    except Exception:
        pass
    try:
        d.settings.pop("debug", None)
    except Exception:
        pass

    # 禁用设备级指针位置（开发者选项中的"指针位置"覆盖层）
    try:
        d.shell("settings put system pointer_location 0 2>/dev/null")
    except Exception:
        pass

    # 禁用显示触摸操作（开发者选项中的"显示触摸操作"覆盖层）
    try:
        d.shell("settings put system show_touches 0 2>/dev/null")
    except Exception:
        pass

    # 设置合理的操作延迟（新版 uiautomator2 已移除 operation_delay_ms，统一用 operation_delay）
    d.settings["operation_delay"] = 0.5

    # 启动全局弹窗监控
    ctx = d.watch_context()
    ctx.when("确认").click()
    ctx.when("确定").click()
    ctx.when("关闭").click()
    ctx.when("刷新").click()
    ctx.when("点击刷新").click()
    ctx.when("领取今日奖励").click()
    ctx.when(xpath="//android.app.Dialog//android.widget.Button[@text='关闭']").click()
    ctx.when(xpath="//android.widget.Image[@text='关闭']").click()
    ctx.start()
    d._global_watcher_ctx = ctx

    w, h = d.window_size()
    print(f"   屏幕分辨率: {w} x {h}")
    return d


# ========================================================
# UI 控件查找（纯 U2）
# ========================================================
def u2_find_text(device, text, contains=True):
    """通过 U2 textContains 或 text 精确匹配查找控件"""
    if contains:
        try:
            btn = device(textContains=text)
            if btn.exists:
                return btn
        except:
            pass
    try:
        btn = device(text=text)
        if btn.exists:
            return btn
    except:
        pass
    return None


def u2_click_text(device, text, contains=True):
    """通过 U2 查找并点击包含文字的控件"""
    try:
        if contains:
            btn = device(textContains=text)
            if btn.exists:
                return click_u2_control(device, btn, text)
        btn = device(text=text)
        if btn.exists:
            return click_u2_control(device, btn, text)
    except:
        pass
    return False


def handle_open_allow_popup(device):
    """处理"打开/允许/始终允许"弹窗"""
    try:
        btn = device(className="android.widget.Button", textMatches=r"打开|允许|始终允许")
        if btn.exists:
            click_u2_control(device, btn, "打开/允许")
            time.sleep(1)
            return True
    except:
        pass
    return False


def u2_find_task_buttons(device):
    """
    在 hierarchy 中查找可执行的任务按钮。

    策略（2026-06-08 更新）：
    1. 优先按任务名关键词查找（U2 textContains），
       按钮坐标取 (screen_width * 0.84, task_cy)
       —— 因为"去完成"按钮在任务名右侧固定 X 位置
    2. 无结果时回退到找"去完成/去浏览"按钮 + 左匹配任务名
    
    返回: [{"btn": element, "name": str, "cx": int, "cy": int, "found_by": str}, ...]
    """
    screen_w, screen_h = device.window_size()
    button_x = int(screen_w * 0.84)  # "去完成"按钮固定在任务名右侧此 X 位置
    
    results = []
    
    # === 方法1：按任务名关键词查找 ===
    print("  🔍 [u2] 方法1: 按任务名关键词查找...")
    task_keywords = [
        "浏览精选", "精选推荐", "猜你喜欢",
        "看直播", "看视频", "看福利", "看精选直播", "看黄金档",
        "去浏览", "去逛逛", "去观看",
        "省钱", "上新好物",
        "猜价格", "猜价格游戏",
    ]
    exclude_keywords = ["做任务", "领元宝", "元宝商城", "下单", "购买", "付款", "充值"]
    
    for kw in task_keywords:
        try:
            elems = device(textContains=kw)
            if not elems.exists:
                continue
            for elem in elems:
                try:
                    cx, cy = elem.center()
                    cx, cy = int(cx), int(cy)
                except:
                    continue
                task_text = elem.get_text().strip()
                if not task_text:
                    continue
                # 排除标题文案
                if any(ex in task_text for ex in exclude_keywords):
                    print(f"    ⊘ 排除标题: 【{task_text}】")
                    continue
                print(f"    ✅ 任务名: 【{task_text}】 @({cx},{cy}) → 按钮 @({button_x},{cy})")
                results.append({
                    "btn": elem,
                    "name": task_text,
                    "cx": button_x,
                    "cy": cy,
                    "found_by": "u2_taskname"
                })
        except Exception:
            pass
    
    if results:
        # 按 Y 轴去重（每行一个任务）
        seen_y = set()
        unique = []
        for r in sorted(results, key=lambda x: x["cy"]):
            key = r["cy"] // 30
            if key not in seen_y:
                seen_y.add(key)
                unique.append(r)
        print(f"  📊 方法1 找到 {len(unique)} 个任务按钮")
        return unique
    
    # === 方法2：回退 -> 找"去完成/去浏览"按钮 ===
    print("  ⚠️ [u2] 方法1无结果，回退到方法2: 找按钮文本...")
    btn_texts = ["去完成", "去浏览", "去观看", "去领取", "点击得", "去逛逛", "去查看"]
    
    for text in btn_texts:
        try:
            btns = device(textContains=text)
            if btns.exists:
                for btn in btns:
                    try:
                        cx, cy = btn.center()
                        cx, cy = int(cx), int(cy)
                    except:
                        cx, cy = 0, 0
                    
                    # 尝试获取任务名：parent/sibling
                    task_name = ""
                    try:
                        parent = btn.parent()
                        if parent.exists:
                            for child in parent.child(className="android.widget.TextView"):
                                t = child.get_text().strip()
                                if t and t not in btn_texts:
                                    task_name += t + " "
                    except:
                        pass
                    if not task_name:
                        try:
                            siblings = btn.sibling(className="android.widget.TextView")
                            if siblings.exists:
                                for s in siblings:
                                    t = s.get_text().strip()
                                    if t and t not in btn_texts:
                                        task_name += t + " "
                        except:
                            pass
                    
                    # 坐标邻近搜索兜底（左匹配）
                    if not task_name.strip():
                        try:
                            nodes = scan_page(device)
                            candidates = []
                            for n in nodes:
                                t = n.get("text", "").strip()
                                if not t or t in btn_texts:
                                    continue
                                hdist = cx - n["cx"]
                                vdist = abs(cy - n["cy"])
                                if 30 <= hdist <= 500 and vdist < 80:
                                    candidates.append((hdist, t))
                            if candidates:
                                candidates.sort(key=lambda x: x[0])
                                task_name = candidates[0][1]
                        except:
                            pass
                    
                    print(f"    ✅ 按钮: 【{task_name or text}】 @({cx},{cy})")
                    results.append({
                        "btn": btn,
                        "name": task_name.strip() if task_name.strip() else text,
                        "cx": cx,
                        "cy": cy,
                        "found_by": "u2_text"
                    })
        except:
            pass
    
    # 方法2 无结果 -> hierarchy XML 兜底
    if not results:
        print("  ⚠️ [u2] 方法2无结果，用 hierarchy XML 兜底...")
        results = _find_task_buttons_via_hierarchy(device)
    
    # 去重
    seen = set()
    unique = []
    for r in results:
        key = (r["cx"] // 20, r["cy"] // 20)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    
    return unique


def _find_task_buttons_via_hierarchy(device):
    """通过 hierarchy XML 解析查找任务按钮"""
    btn_texts = ["去完成", "去浏览", "去观看", "去领取", "去玩", "点击得"]
    results = []
    
    try:
        xml_str = device.dump_hierarchy()
        root = ElementTree.fromstring(xml_str)
        
        # 先找所有 text 匹配的节点
        all_nodes = root.findall(".//node")
        for node in all_nodes:
            text = node.attrib.get("text", "")
            desc = node.attrib.get("content-desc", "")
            clickable = node.attrib.get("clickable", "false") == "true"
            bounds = node.attrib.get("bounds", "")
            
            is_btn = any(bt in text or bt in desc for bt in btn_texts)
            if not is_btn:
                continue
            
            # 解析坐标
            match = re.findall(r'\[(\d+),(\d+)\]', bounds)
            if len(match) >= 2:
                x1, y1 = int(match[0][0]), int(match[0][1])
                x2, y2 = int(match[1][0]), int(match[1][1])
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            else:
                continue
            
        # 找关联任务名：父节点下的其他文本
            task_name = text if text else desc
            parent = node.getparent() if hasattr(ElementTree.Element, 'getparent') else None
            if parent is None:
                # 手动找父节点（用 try 避免 text 含特殊字符导致 XPath 崩溃）
                try:
                    escaped_text = text.replace("'", "\\'").replace('"', '\\"')
                    for p in root.findall(f".//node[.//node[@text='{escaped_text}']]"):
                        parent = p
                        break
                except Exception:
                    parent = None
            
            if parent is not None:
                for child in parent.findall(".//node"):
                    ct = child.attrib.get("text", "")
                    if ct and ct not in btn_texts and ct != text:
                        if ct not in task_name or len(ct) > len(task_name) // 2:
                            task_name = ct
                            break
            
            results.append({
                "btn": None,
                "name": task_name[:50] if task_name else text,
                "cx": cx,
                "cy": cy,
                "found_by": "hierarchy"
            })
    except Exception as e:
        print(f"  ⚠️ hierarchy 解析异常: {e}")
    
    return results


# ========================================================
# 黑名单过滤
# ========================================================
BLACKLIST_KEYWORDS = [
    "猜一猜", "猜谜",
    "邀请", "邀请好友", "拉好友", "助力", "分享", "去邀请",
    "下单", "购买", "充值", "付款", "元宝商城",
    "喂鸡", "蚂蚁庄园", "蚂蚁新村", "饿了么", "果园",
    "消消乐", "农场小游戏", "斗地主", "开心消消乐",
    "大众点评", "拍立淘",
    "3元抢3件包邮到家", "1元抢爆款好货",
    "全场3元3件", "好货限时直降",
    "头条极速版", "趣头条",
    "查看并完成", "玩小游戏",
]

def is_blacklisted(text):
    if not text:
        return True
    if '猜' in text and '猜价格' not in text and '猜价格游戏' not in text:
        return True
    for kw in BLACKLIST_KEYWORDS:
        if kw in text:
            return True
    return False


# ========================================================
# 页面扫描（返回结构化数据）
# ========================================================
def scan_page(device):
    """扫描当前页面，返回所有控件的结构化列表"""
    try:
        xml_str = device.dump_hierarchy()
        root = ElementTree.fromstring(xml_str)
        nodes = []
        stack = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            attrs = dict(node.attrib)
            info = {
                "text": attrs.get("text", ""),
                "content_desc": attrs.get("content-desc", ""),
                "class": attrs.get("class", ""),
                "resource_id": attrs.get("resource-id", ""),
                "clickable": attrs.get("clickable", "false") == "true",
                "enabled": attrs.get("enabled", "true") == "true",
                "scrollable": attrs.get("scrollable", "false") == "true",
                "bounds": attrs.get("bounds", ""),
                "depth": depth,
            }
            # 解析坐标
            match = re.findall(r'\[(\d+),(\d+)\]', info["bounds"])
            if len(match) >= 2:
                x1, y1 = int(match[0][0]), int(match[0][1])
                x2, y2 = int(match[1][0]), int(match[1][1])
                info["cx"] = (x1 + x2) // 2
                info["cy"] = (y1 + y2) // 2
            else:
                info["cx"], info["cy"] = 0, 0
            
            nodes.append(info)
            for child in reversed(list(node)):
                stack.append((child, depth + 1))
        return nodes
    except Exception as e:
        print(f"  ⚠️ 扫描异常: {e}")
        return []


def find_clickable_with_text(nodes, keyword):
    """查找可点击且包含文字的关键节点"""
    for n in nodes:
        if n["clickable"] and (keyword in n["text"] or keyword in n["content_desc"]):
            return n
    return None


# ========================================================
# 导航链（通用）
# ========================================================
def navigate_chain(device, steps):
    """
    通用导航链
    steps: [("关键词1", "描述1"), ("关键词2", "描述2"), ...]
    """
    for step_name, keyword in steps:
        print(f"  🧭 导航: {step_name} → 查找【{keyword}】...")
        if not u2_click_text(device, keyword):
            # hierarchy 兜底
            nodes = scan_page(device)
            target = find_clickable_with_text(nodes, keyword)
            if target and target["cx"] > 0:
                print(f"     hierarchy 点击 @({target['cx']},{target['cy']})")
                device.click(target["cx"], target["cy"])
            else:
                print(f"     ⚠️ 未找到【{keyword}】")
        time.sleep(4)


def navigate_to_sleep_page(device):
    """导航：点淘 → 元宝中心 → 睡觉赚元宝"""
    print("🔄 导航到【睡觉赚元宝】...")
    device.app_start(DT_APP, stop=True)
    time.sleep(5)
    
    navigate_chain(device, [
        ("Step 1: 元宝中心", "元宝中心"),
        ("Step 2: 睡觉赚元宝", "睡觉赚元宝"),
    ])
    return True


def navigate_to_dagong_page(device):
    """导航：点淘 → 元宝中心 → 打工赚元宝"""
    print("🔄 导航到【打工赚元宝】...")
    device.app_start(DT_APP, stop=True)
    time.sleep(5)
    
    navigate_chain(device, [
        ("Step 1: 元宝中心", "元宝中心"),
        ("Step 2: 打工赚元宝", "打工赚元宝"),
    ])
    return True


def navigate_to_duck_page(device):
    """导航：点淘 → 元宝中心 → 点淘鸭家园"""
    print("🔄 导航到【点淘鸭家园】...")
    device.app_start(DT_APP, stop=True)
    time.sleep(5)
    
    navigate_chain(device, [
        ("Step 1: 元宝中心", "元宝中心"),
        ("Step 2: 点淘鸭家园", "点淘鸭家园"),
    ])
    
    # Step 3: 点击任务列表
    print("  Step 3: 打开任务列表...")
    time.sleep(2)
    nodes = scan_page(device)
    for n in nodes:
        if "任务" in n["text"] and "去完" not in n["text"] and "完成" not in n["text"]:
            if n["clickable"] or True:
                device.click(n["cx"], n["cy"])
                print(f"    点击【{n['text']}】打开任务列表")
                time.sleep(4)
                return True
    
    if u2_click_text(device, "任务"):
        time.sleep(4)
        return True
    
    return True


# ========================================================
# 返回任务列表
# ========================================================
def back_to_task(device, target_keywords=None, nav_func=None):
    """智能返回任务列表：多次尝试返回 + nav_func 兜底"""
    if target_keywords is None:
        target_keywords = ["去完成", "打工", "任务"]
    
    def _is_on_task_page():
        """检测当前是否在任务列表页"""
        try:
            for kw in target_keywords:
                if device(textContains=kw).exists(timeout=0.5):
                    print(f"  ✅ 已在任务列表页 (检测到【{kw}】)")
                    return True
        except:
            pass
        return False
    
    # 先检测是否已经在任务列表页
    if _is_on_task_page():
        return True
    
    # 多次按 back，每次检测是否回到任务页
    for attempt in range(1, 4):
        print(f"  🔙 back_to_task() 第{attempt}次返回")
        device.press("back")
        time.sleep(1.5)
        if _is_on_task_page():
            return True
    
    # 仍然没回到任务页，使用 nav_func 兜底导航
    if nav_func is not None:
        print(f"  🚀 多次返回未到任务页，调用 nav_func 重新导航...")
        try:
            nav_func(device)
            time.sleep(3)
            if _is_on_task_page():
                return True
        except Exception as e:
            print(f"  ⚠️ nav_func 导航异常: {e}")
    
    print(f"  ⚠️ back_to_task: 最终未能回到任务列表页，继续执行")
    return False


# ========================================================
# 等待任务完成
# ========================================================
def wait_completion(device, timeout=25):
    """等待任务完成（检测"恭喜完成任务"等文字）"""
    print("  ⏳ 等待任务完成...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            if device(textContains="恭喜完成任务").exists or \
               device(textContains="恭喜完成").exists or \
               device(textContains="任务完成").exists or \
               device(textContains="获得奖励").exists or \
               device(textContains="恭喜获得").exists:
                print("  ✅ 检测到完成提示")
                return True
        except:
            pass
        time.sleep(1)
    print(f"  ⏰ 等待超时 ({timeout}s)")
    return False


# ========================================================
# 猜价格游戏处理器（纯 U2）
# ========================================================
def _close_guess_price_popup(device):
    """关闭猜价格游戏结束后的弹窗（用 live_close.png 模板匹配）"""
    screen_w, screen_h = device.window_size()
    
    # 搜索区域：X 固定 1179 ±50，Y 范围 696~795
    search_x1 = 1129
    search_y1 = 696
    search_x2 = 1229
    search_y2 = 795
    
    # 模板路径：AGENT工具脚本/../diantao/img/live_close.png
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, "..", "diantao", "img", "live_close.png")
    
    found = False
    if os.path.exists(template_path):
        try:
            screenshot = device.screenshot(format='opencv')
            if screenshot is not None:
                # 裁剪搜索区域
                roi = screenshot[search_y1:search_y2, search_x1:search_x2]
                template = cv2.imread(template_path)
                if template is not None and roi.shape[0] > 0 and roi.shape[1] > 0:
                    roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                    tpl_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                    
                    res = cv2.matchTemplate(roi_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    
                    if max_val >= 0.6:
                        # 将 ROI 坐标转回屏幕坐标
                        click_x = search_x1 + max_loc[0] + template.shape[1] // 2
                        click_y = search_y1 + max_loc[1] + template.shape[0] // 2
                        print(f"    关闭弹窗: 模板匹配 live_close.png @({click_x},{click_y}) 置信度={max_val:.3f}")
                        device.click(click_x, click_y)
                        found = True
        except Exception as e:
            print(f"    ⚠️ 模板匹配异常: {e}")
    
    if not found:
        # 兜底：点区域中点
        close_x = 1179
        close_y = (search_y1 + search_y2) // 2  # 745
        print(f"    关闭弹窗: 兜底点击 @({close_x},{close_y})")
        device.click(close_x, close_y)
    
    time.sleep(1)
    return True


def handle_guess_price_game(device):
    """
    猜价格游戏处理器（纯 U2）
    固定坐标策略：
      - 3列商品，checkmark X=[225, 633, 1043]
      - Row 1 Y=1609, Row 2 Y=2218
      - 确认按钮 (633, 2520)
    退出策略：先关弹窗（X/关闭）→ 再返回任务列表
    """
    print("\n  ========== 猜价格游戏 (纯U2) ==========")
    screen_w, screen_h = device.window_size()
    
    if screen_w > 1000:
        col_x = [225, 633, 1043]
    else:
        col_w = screen_w // 3
        col_x = [col_w // 2, col_w * 3 // 2, col_w * 5 // 2]
    
    row1_y = int(screen_h * 0.58)
    row2_y = int(screen_h * 0.80)
    confirm_y = int(screen_h * 0.905)
    
    rows = [row1_y, row2_y]
    max_attempts = 6
    
    # 进入游戏页面时，先保存初始页面所有文字，用于排除上一页（如视频流）残留的时间文本
    _initial_texts = set()
    try:
        _init_nodes = scan_page(device)
        for n in _init_nodes:
            if re.search(r'\d{1,2}:\d{2}:\d{2}', n["text"]):
                _initial_texts.add(n["text"])
        if _initial_texts:
            print(f"  初始页面存在时间文本: {_initial_texts}，倒计时检测时将排除")
    except:
        pass
    
    for attempt in range(max_attempts):
        row_idx = attempt // 3
        col_idx = attempt % 3
        check_x = col_x[col_idx]
        check_y = rows[row_idx]
        
        print(f"  --- 第 {attempt+1}/{max_attempts} 次: 点击 @({check_x},{check_y}) ---")
        device.click(check_x, check_y)
        time.sleep(1)
        
        device.click(int(screen_w * 0.5), confirm_y)
        time.sleep(2.5)
        
        # 倒计时结束检测：排除初始页面已存在的时间文本
        # （如上一页视频流残留的"01:33:27后"），仅当新出现的时间文本才算游戏结束
        try:
            nodes = scan_page(device)
            for n in nodes:
                text = n["text"]
                if text in _initial_texts:
                    continue  # 初始页面已存在的文本，不是游戏倒计时
                has_time = re.search(r'\d{1,2}:\d{2}:\d{2}', text)
                if has_time and "后再来玩" in text:
                    print(f"  ✅ 检测到倒计时 [{text}]，游戏结束")
                    time.sleep(1)
                    _close_guess_price_popup(device)
                    print(f"  ========== 猜价格游戏结束 ==========\n")
                    return True
        except:
            pass
        
        try:
            if device(textContains="换一批").exists:
                print(f"  检测到【换一批】, 点击继续尝试")
                click_u2_control(device, device(textContains="换一批"), "换一批")
                time.sleep(1.5)
        except:
            pass
    
    print(f"  ⚠️ 所有尝试结束")
    _close_guess_price_popup(device)
    print(f"  ========== 猜价格游戏结束 ==========\n")
    return False


# ========================================================
# 浮动气泡检测
# ========================================================
def scan_float_bubbles(device):
    """
    扫描浮动 "+数字" 或纯数字气泡
    返回 [{"text": str, "cx": int, "cy": int}, ...]
    """
    nodes = scan_page(device)
    screen_w, screen_h = device.window_size()
    bubbles = []
    
    seen = set()
    for n in nodes:
        text = n["text"].strip()
        if not text:
            continue
        if n["cy"] < int(screen_h * 0.13) or n["cy"] > int(screen_h * 0.40):
            continue
        
        if "+" in text or re.match(r"^\d{1,4}$", text):
            key = (n["cx"] // 30, n["cy"] // 30)
            if key not in seen:
                seen.add(key)
                bubbles.append({"text": text, "cx": n["cx"], "cy": n["cy"]})
    
    return bubbles


def click_float_bubbles(device, max_collect=10):
    """点击浮动气泡（每次只点1个，防止多点导致UI错乱）"""
    bubbles = scan_float_bubbles(device)
    clicked = 0
    for b in bubbles[:max_collect]:
        print(f"      点击浮动气泡: [{b['text']}] @({b['cx']}, {b['cy']})")
        device.click(b["cx"], b["cy"])
        time.sleep(1.5)
        clicked += 1
        break  # 每次只点1个，主循环下次扫描再点下一个
    if clicked > 0:
        print(f"      本次收集 {clicked} 个浮动气泡")
    return clicked


# ========================================================
# 直播相关处理（滑动 + 关弹窗 + 检测完成）
# ========================================================
# 直播弹窗关闭
# ========================================================
# 弹窗关闭关键词库（仅保留明确关闭/跳过意图的词）
# 注意：不要加"领取""红包""福袋""分享"等，直播间的正常UI大量包含这些词，会误点
POPUP_CLOSE_TEXTS = [
    "关闭", "×", "关闭按钮", "取消",
    "我知道了", "朕知道了", "关闭广告",
    "跳过", "跳过广告",
    "不感兴趣",
]

# 关闭弹窗冷却记录：{keyword: last_click_time}，防止同一关键词高频重复点击
_last_popup_click_time = {}
_POPUP_COOLDOWN = 15  # 同一关键词 15 秒内不重复点击


def close_live_popups(device):
    """
    关闭直播间的弹窗（带冷却机制，防止误点正常UI）
    返回 True 表示关掉了至少一个弹窗
    
    策略:
      1. textContains 匹配关闭类关键词（带冷却，同一关键词15秒内不重复点击）
      2. scan_page 扫描 content_desc 找关闭按钮（限制上半屏60%）
      3. 点击左上角区域兜底
    """
    global _last_popup_click_time
    closed = 0
    sw, sh = device.window_size()
    now = time.time()
    upper_limit = int(sh * 0.6)
    
    # 策略1: 匹配文本寻找关闭按钮（带冷却）
    for text in POPUP_CLOSE_TEXTS:
        # 冷却检查：同一关键词 15 秒内不重复点
        last_click = _last_popup_click_time.get(text, 0)
        if now - last_click < _POPUP_COOLDOWN:
            continue
        try:
            btn = device(textContains=text)
            if btn.exists:
                _, btn_cy = btn.center()
                if btn_cy >= upper_limit:
                    continue
                click_u2_control(device, btn, text)
                _last_popup_click_time[text] = time.time()
                closed += 1
                time.sleep(0.3)
        except:
            pass
    
    # 策略2: scan_page 扫描 content_desc 找关闭按钮（限制上半屏60%）
    try:
        nodes = scan_page(device)
        for n in nodes:
            if n["cy"] >= upper_limit:
                continue
            desc = n["content_desc"]
            if desc and any(t in desc for t in ["关闭", "X", "×", "知道", "关闭按钮", "取消"]):
                if n["cx"] > 0 and n["cy"] > 0:
                    # content_desc 也做冷却
                    key = f"desc:{desc}"
                    last_click = _last_popup_click_time.get(key, 0)
                    if now - last_click < _POPUP_COOLDOWN:
                        continue
                    device.click(n["cx"], n["cy"])
                    _last_popup_click_time[key] = time.time()
                    closed += 1
                    time.sleep(0.3)
    except:
        pass
    
    # 策略3已移除：左上角点击在直播间里等价于返回键，会导致误退直播间
    
    if closed > 0:
        time.sleep(0.5)
    return closed > 0


def detect_live_completion(device):
    """
    检测直播任务是否完成（先 U2 快速检测，再用 scan_page 全 hierarchy 兜底）
    返回 True 表示任务已完成
    """
    completion_texts = [
        "恭喜完成任务", "恭喜完成", "任务完成",
        "获得奖励", "恭喜获得", "已完成",
        "任务进度已完成", "进度已完成",
        "已看", "任务已",
        "谢谢观看", "感谢观看", "直播已结束",
        "本场直播已结束", "主播已离开",
    ]
    # 策略1: 用 U2 直接检测完成文字（快速通道）
    for text in completion_texts:
        try:
            if device(textContains=text).exists:
                return True
        except:
            pass
    
    # 策略2: 用 scan_page 全 hierarchy 扫描（能抓到 WebView 露出的文字）
    try:
        nodes = scan_page(device)
        all_text = " ".join(n.get("text", "") for n in nodes)
        for kw in completion_texts:
            if kw in all_text:
                return True
    except:
        pass
    
    return False


def execute_live_task(device, task_name, btn_cx, btn_cy, duration=None):
    """
    统一直播任务执行器（纯 U2，含弹窗关闭）
    
    功能：
      - 进入直播间
      - 每 5-10 秒随机滑动一次
      - 实时检测并关闭弹窗（带冷却机制，不影响正常UI）
      - 实时检测完成提示 立即退出返回任务列表
      - 停留指定时长后自动退出
      - 自动从任务名解析时长（如"看直播60秒" → 60秒）
    
    参数:
      duration: 最长停留时间（秒），None 则从 task_name 自动解析
    """
    # 智能解析：先从任务名提取 XX秒 或 X分钟
    if duration is None:
        match = re.search(r"(\d+)\s*秒", task_name)
        if match:
            duration = int(match.group(1))
        else:
            match = re.search(r"(\d+)\s*分钟", task_name)
            if match:
                duration = int(match.group(1)) * 60
            else:
                duration = 120  # 默认 2 分钟
        # 额外加 5 秒缓冲，确保看够
        duration += 5
    
    print(f"  📺 执行直播任务: 【{task_name}】 → 停留 {duration} 秒")
    sw, sh = device.window_size()
    
    time.sleep(3)
    
    handle_open_allow_popup(device)
    
    time.sleep(2)
    
    # ── 进入直播间后首次扫描：检测是否有"XX秒后完成"倒计时字样 ──
    countdown_active = False
    try:
        init_nodes = scan_page(device)
        init_text = " ".join(n.get("text", "") for n in init_nodes)
        countdown_match = re.search(r"(\d+)\s*秒后完成", init_text)
        if countdown_match:
            countdown_active = True
            remaining_sec = int(countdown_match.group(1))
            print(f"  ⏱️ 检测到倒计时【{remaining_sec}秒后完成】，等待倒计时消失...")
    except:
        pass
    
    print(f"  ⏳ 进入直播间，最长停留 {duration} 秒...")
    start = time.time()
    last_swipe = 0
    completion_detected = False
    
    while True:
        elapsed = int(time.time() - start)
        remain = duration - elapsed
        
        if elapsed >= duration:
            print(f"  ⏰ 停留时间到 ({duration}s)")
            break
        
        # ── 倒计时消失检测（直播类"XX秒后完成"文本消失即完成） ──
        if countdown_active:
            try:
                cur_nodes = scan_page(device)
                cur_text = " ".join(n.get("text", "") for n in cur_nodes)
                cur_match = re.search(r"(\d+)\s*秒后完成", cur_text)
                if not cur_match:
                    print(f"  ✅ 【{remaining_sec}秒后完成】倒计时消失，继续停留到要求时长")
                    completion_detected = True
                    countdown_active = False
                else:
                    remaining_sec = int(cur_match.group(1))
            except:
                pass
        
        # ── 关键词完成检测兜底（已有逻辑） ──
        try:
            if not completion_detected and detect_live_completion(device):
                print(f"  ✅ 检测到任务完成，继续停留到要求时长")
                completion_detected = True
        except:
            pass
        
        # ── 弹窗关闭（带冷却机制，不影响正常UI） ──
        try:
            close_live_popups(device)
        except:
            pass
        
        if elapsed >= last_swipe + random.randint(5, 10):
            swipe_x = random.randint(int(sw * 0.3), int(sw * 0.7))
            s_y = random.randint(int(sh * 0.65), int(sh * 0.80))
            e_y = random.randint(int(sh * 0.15), int(sh * 0.30))
            try:
                device.swipe(swipe_x, s_y, swipe_x, e_y, duration=random.uniform(0.3, 0.6))
            except:
                pass
            last_swipe = elapsed
            if remain > 0:
                print(f"    已过 {elapsed}s / 剩余 {remain}s，上滑一次 ⬆️")
            else:
                print(f"    已过 {elapsed}s，上滑一次 ⬆️")
        
        time.sleep(2)
    
    if completion_detected:
        print(f"  ✅ 直播任务【{task_name}】已完成")
    else:
        print(f"  ⚠️ 直播停留完成")

    time.sleep(2)
    return completion_detected


# ========================================================
# 点击后媒体页面识别
# ========================================================
def classify_media_page(blocks):
    """根据点击后的页面文本判定实际是视频流还是直播间。"""
    all_text = " ".join(
        str(block.get("text", "")).strip()
        for block in (blocks or [])
        if block.get("text")
    )

    video_score = 0
    if "上滑查看更多视频" in all_text or "查看更多视频" in all_text:
        video_score += 5
    if "发放奖励" in all_text:
        video_score += 4
    if "查看详情" in all_text:
        video_score += 1

    live_score = 0
    if "直播间" in all_text:
        live_score += 5
    if "说点什么" in all_text:
        live_score += 4
    if "秒后完成" in all_text:
        live_score += 3
    if "关注" in all_text:
        live_score += 1

    if video_score >= live_score + 2:
        return "video"
    if live_score >= video_score + 2:
        return "live"
    return None


def detect_entered_media_type(device, expected_type, task_name=""):
    """点击任务入口后只做一次识别，返回实际媒体页类型。

    页面切换期间 OCR 可能暂时为空，因此同一轮校验最多取两次页面快照；
    不会在任务执行期间持续扫描。无法确认时保留点击前的预判类型。
    """
    from utils import get_ocr_text_blocks

    for attempt in range(2):
        try:
            detected = classify_media_page(get_ocr_text_blocks(device))
        except Exception as exc:
            detected = None
            if attempt == 1:
                print(f"  ⚠️ 点击后媒体页识别失败: {exc}")

        if detected:
            print(f"  🔎 点击后 OCR 判定实际页面: {detected}")
            return detected

        if attempt == 0:
            time.sleep(1)

    print(
        f"  ⚠️ 点击后 OCR 无法确认页面，保留预判路由: "
        f"{expected_type}（任务: {task_name}）"
    )
    return expected_type


# ========================================================
# 看视频任务执行（翻页风格滑动）
# ========================================================
def video_swipe_count_range(duration: int) -> tuple[int, int]:
    """按视频时长返回基础下滑次数范围；60 秒对应 8–12 次。"""
    if duration <= 0:
        return 0, 0
    minimum = max(1, math.ceil(duration / 7.5))
    maximum = max(minimum, math.ceil(duration / 5))
    return minimum, maximum


DEFAULT_VIDEO_EXTRA_SWIPES_RANGE = (7, 9)


def execute_video_task(
    device, task_name, btn_cx, btn_cy, duration=None,
    extra_time_seconds=0, extra_swipes=None,
    swipe_interval_extra_seconds=0, verify_media_page=False,
    initial_swipe=False, initial_swipe_start_ratio=0.70,
):
    """暂停后台弹窗点击，执行固定次数视频任务，并恢复原暂停层级。"""
    pause_global_watcher(device)
    try:
        return _execute_video_task(
            device, task_name, btn_cx, btn_cy, duration=duration,
            extra_time_seconds=extra_time_seconds, extra_swipes=extra_swipes,
            swipe_interval_extra_seconds=swipe_interval_extra_seconds,
            verify_media_page=verify_media_page, initial_swipe=initial_swipe,
            initial_swipe_start_ratio=initial_swipe_start_ratio,
        )
    finally:
        resume_global_watcher(device)


def _execute_video_task(
    device, task_name, btn_cx, btn_cy, duration=None,
    extra_time_seconds=0, extra_swipes=None,
    swipe_interval_extra_seconds=0, verify_media_page=False,
    initial_swipe=False, initial_swipe_start_ratio=0.70,
):
    """
    看视频任务执行器：完成固定下滑次数，并满足最低停留时间后返回。

    `btn_cx`、`btn_cy` 仅用于兼容调用方。启用 `verify_media_page` 时，
    进入后先做一次视频/直播页面识别；如果实际落地为直播间，则转交直播
    执行器，避免把直播页当成视频流滑动。确认是视频或无法确认后，才按
    时长和下滑计划执行。`initial_swipe` 用于兼容部分任务的首个额外下滑，
    该动作也会在媒体页确认之后执行。未指定额外下滑次数时，从 7–9 次
    范围内随机选择。
    """
    if duration is None:
        match = re.search(r"(\d+)\s*秒", task_name)
        if match:
            duration = int(match.group(1))
        else:
            match = re.search(r"(\d+)\s*分钟", task_name)
            if match:
                duration = int(match.group(1)) * 60
            else:
                duration = 120
    duration += extra_time_seconds

    base_min, base_max = video_swipe_count_range(duration)
    base_swipes = random.randint(base_min, base_max) if base_max else 0
    if extra_swipes is None:
        extra_swipes = random.randint(*DEFAULT_VIDEO_EXTRA_SWIPES_RANGE)
    extra_swipes = max(0, extra_swipes)
    target_swipes = base_swipes + extra_swipes
    swipe_interval_extra_seconds = max(0, swipe_interval_extra_seconds)
    base_interval = duration / target_swipes if target_swipes else 0
    swipe_interval = base_interval + swipe_interval_extra_seconds
    effective_duration = duration + swipe_interval_extra_seconds * max(0, target_swipes - 1)

    print(f"  🎬 执行看视频任务: 【{task_name}】 → 停留 {duration} 秒")
    print(
        f"  🎬 下滑计划: 基础 {base_min}-{base_max} 次，随机 {base_swipes} 次"
        f" + 额外 {extra_swipes} 次 = 共 {target_swipes} 次"
        f"（平均间隔约 {swipe_interval:.1f}s"
        f"，间隔增加 {swipe_interval_extra_seconds:.1f}s）"
    )
    sw, sh = device.window_size()

    # 入口点击已由上层任务执行器完成，这里只等待视频流稳定。
    time.sleep(2)

    if verify_media_page:
        actual_type = detect_entered_media_type(device, "video", task_name)
        print(f"  📋 点击后实际类型: {actual_type}（任务名预判: video）")
        if actual_type == "live":
            print(f"  🔁 实际进入直播间，切换直播任务执行器: 【{task_name}】")
            try:
                return execute_live_task(
                    device, task_name, btn_cx, btn_cy, duration=duration
                )
            finally:
                # 视频入口没有上层直播分支负责返回，切换到直播执行器后
                # 由这里保持视频入口原有的“执行完返回任务页”契约。
                try:
                    device.press("back")
                    time.sleep(1)
                except Exception:
                    pass

    completed = True
    if initial_swipe:
        start_y = int(sh * max(0.0, min(1.0, initial_swipe_start_ratio)))
        end_y = int(sh * 0.30)
        print(f"  🎬 视频首滑：({sw // 2},{start_y}) → ({sw // 2},{end_y})")
        try:
            device.swipe(
                sw // 2,
                start_y,
                sw // 2,
                end_y,
                duration=random.uniform(0.08, 0.15),
            )
        except Exception as exc:
            print(f"  ⚠️ 视频首滑指令异常：{exc}")
            completed = False
        time.sleep(1)

    print(
        f"  ⏳ 进入视频流，任务时长 {duration} 秒，"
        f"最低停留 {effective_duration:.1f} 秒，完成全部下滑后返回..."
    )
    start = time.time()
    swipe_index = 0
    next_swipe_at = 0.0

    while completed:
        elapsed = time.time() - start
        if swipe_index >= target_swipes and elapsed >= effective_duration:
            print(f"  ⏰ 视频调度完成 ({effective_duration:.1f}s)")
            break

        # 只执行翻页风格上滑，不读取页面、不处理弹窗、不检测完成提示。
        if swipe_index < target_swipes and elapsed >= next_swipe_at:
            swipe_x = sw // 2
            s_y = int(sh * 0.70)
            e_y = int(sh * 0.30)
            print(f"    🎬 视频滑动：({swipe_x},{s_y}) → ({swipe_x},{e_y})")
            try:
                device.swipe(swipe_x, s_y, swipe_x, e_y, duration=random.uniform(0.08, 0.15))
                print("    ✅ 视频滑动指令已发出")
            except Exception as exc:
                print(f"    ⚠️ 视频滑动指令异常：{exc}")
                completed = False
                break
            swipe_index += 1
            # 以本次实际发起时间安排下一次，延迟后不追赶旧时间表。
            next_swipe_at = elapsed + swipe_interval
            print(f"    已过 {elapsed:.1f}s，翻页 ⬆️ ({swipe_index}/{target_swipes})")
            continue

        wake_at = next_swipe_at if swipe_index < target_swipes else effective_duration
        time.sleep(min(0.5, max(0.001, wake_at - elapsed)))

    print(f"  {'✅' if completed else '⚠️'} 看视频任务【{task_name}】退出，完成下滑 {swipe_index}/{target_swipes}")
    try:
        device.press("back")
        time.sleep(1)
    except:
        pass

    return completed


# ========================================================
# 浏览任务执行
# ========================================================
def execute_browse_task(device, min_duration=0, max_wait=120, extra_seconds=5):
    """
    通用浏览任务：实时扫描"滑动浏览XX秒"字样，消失即任务完成
    适用于：签到赢元宝、点淘购物赚钱、睡觉赚元宝等所有浏览类任务
    
    策略：
      1. 先实时扫描"滑动浏览XX秒"字样，如果找到 → 提取秒数N，至少滑动N秒后再退出
      2. 如果未找到滑动字样 → 按 min_duration 秒固定下滑浏览 + 完成提示检测
      3. 兜底 max_wait 秒超时退出
      4. 下滑间隔缩短，防止文字提前滑出屏幕导致误判完成
    
    参数:
        min_duration: 未检测到滑动字样时的最小浏览时间（秒）
        max_wait: 超时上限（秒）
        extra_seconds: 识别到倒计时后追加的保险时间（秒），30秒短任务自动翻倍为10秒
    返回:
        True 正常完成, False 超时
    """
    sw, sh = device.window_size()
    swipe_count = 0
    start = time.time()

    # ── 自动适配短任务（30秒以内）的追加时间 ──
    # 如果 min_duration <= 30s 或 detected <= 30s，额外加 10s 而非 5s
    effective_extra = extra_seconds
    task_ref_duration = min_duration if min_duration > 0 else 999
    if task_ref_duration <= 30:
        effective_extra = 10
        print(f"  ⏱️ 检测到30秒短任务，追加保险时间 {effective_extra}s")

    # 立即下滑一次，不等页面扫描
    swipe_x = int(sw * 0.5)
    s_y = random.randint(int(sh * 0.65), int(sh * 0.75))
    e_y = random.randint(int(sh * 0.15), int(sh * 0.25))
    try:
        device.swipe(swipe_x, s_y, swipe_x, e_y, duration=0.3)
    except:
        pass
    time.sleep(1.5)

    # 再检测"滑动浏览XX秒"字样，兼容"秒"字未被控件树收录
    nodes = scan_page(device)
    has_sliding_text = False
    sliding_min_seconds = 0
    for n in nodes:
        text = n["text"]
        match = re.search(r"滑动浏览\s*(\d+)", text)
        if match:
            detected_sec = int(match.group(1))
            # 滑动文本检测到 <= 30s 也自动追加 10s
            if detected_sec <= 30:
                effective_extra = 10
            has_sliding_text = True
            sliding_min_seconds = detected_sec + effective_extra
            print(f"  📋 检测到【{text}】，至少浏览 {sliding_min_seconds} 秒，使用滑动文本监控模式")
            break
    
    if has_sliding_text:
        # 模式A：实时监控"滑动浏览XX秒"直到消失，但至少满足提取的秒数
        print(f"  📋 实时监控【滑动浏览XX秒】字样...")
        while time.time() - start < max_wait:
            elapsed = int(time.time() - start)
            
            nodes = scan_page(device)
            found_sliding = False
            remaining = -1
            for n in nodes:
                text = n["text"]
                match = re.search(r"滑动浏览\s*(\d+)", text)
                if match:
                    found_sliding = True
                    remaining = int(match.group(1))
                    if swipe_count == 0 or swipe_count % 3 == 0 or remaining <= 5:
                        print(f"    检测到【{text}】剩余 {remaining}s... (已过{elapsed}s)")
                    break

            if found_sliding and 0 <= remaining <= 3 and elapsed >= sliding_min_seconds:
                print(f"  ✅ 滑动剩余 {remaining}s，即将完成，下滑收尾...")
                for _ in range(4):
                    swipe_count += 1
                    s_y = random.randint(int(sh * 0.15), int(sh * 0.25))
                    e_y = random.randint(int(sh * 0.65), int(sh * 0.75))
                    try:
                        device.swipe(swipe_x, s_y, swipe_x, e_y, duration=0.3)
                    except:
                        pass
                    time.sleep(0.5)
                time.sleep(1)
                return True

            if not found_sliding and elapsed >= sliding_min_seconds:
                print(f"  ✅ 【滑动浏览XX秒】字样消失，已达 {sliding_min_seconds}s 要求 (共滑动{swipe_count}次)")
                for _ in range(4):
                    swipe_count += 1
                    s_y = random.randint(int(sh * 0.15), int(sh * 0.25))
                    e_y = random.randint(int(sh * 0.65), int(sh * 0.75))
                    try:
                        device.swipe(swipe_x, s_y, swipe_x, e_y, duration=0.3)
                    except:
                        pass
                    time.sleep(0.5)
                time.sleep(1)
                return True
            if not found_sliding:
                print(f"  ⚠️ 字样已消失但仅过 {elapsed}s < {sliding_min_seconds}s，继续滑动等候...")

            # 每次页面扫描之间连续滑动，提升浏览任务完成效率
            for _ in range(5):
                swipe_count += 1
                if swipe_count % 2 == 1:
                    s_y = random.randint(int(sh * 0.65), int(sh * 0.75))
                    e_y = random.randint(int(sh * 0.15), int(sh * 0.25))
                else:
                    s_y = random.randint(int(sh * 0.15), int(sh * 0.25))
                    e_y = random.randint(int(sh * 0.65), int(sh * 0.75))
                try:
                    device.swipe(swipe_x, s_y, swipe_x, e_y, duration=0.3)
                except:
                    pass
                time.sleep(0.5)
        
        print(f"  ⏰ 浏览超时 ({max_wait}s)，共滑动{swipe_count}次")
        time.sleep(1)
        return False
    
    # 模式B：未检测到滑动字样，按固定时长下滑浏览 + 实时完成检测
    if min_duration > 0:
        print(f"  📋 未检测到滑动字样，按固定时长 {min_duration} 秒浏览...")
        while time.time() - start < min_duration and time.time() - start < max_wait:
            elapsed = int(time.time() - start)
            # 实时检测完成提示
            try:
                if elapsed >= min_duration and (
                    device(textContains="恭喜完成任务").exists
                    or device(textContains="恭喜完成").exists
                    or device(textContains="任务完成").exists
                    or device(textContains="获得奖励").exists
                ):
                    print(f"  ✅ 检测到完成提示！(已过{elapsed}s)")
                    for _ in range(4):
                        swipe_count += 1
                        s_y = random.randint(int(sh * 0.15), int(sh * 0.25))
                        e_y = random.randint(int(sh * 0.65), int(sh * 0.75))
                        try:
                            device.swipe(swipe_x, s_y, swipe_x, e_y, duration=0.3)
                        except:
                            pass
                        time.sleep(0.5)
                    time.sleep(1)
                    return True
            except:
                pass
            # 交替上下滑
            swipe_count += 1
            swipe_x = int(sw * 0.5)
            if swipe_count % 2 == 1:
                s_y = random.randint(int(sh * 0.65), int(sh * 0.75))
                e_y = random.randint(int(sh * 0.15), int(sh * 0.25))
            else:
                s_y = random.randint(int(sh * 0.15), int(sh * 0.25))
                e_y = random.randint(int(sh * 0.65), int(sh * 0.75))
            try:
                device.swipe(swipe_x, s_y, swipe_x, e_y, duration=0.3)
            except:
                pass
            time.sleep(0.8)
        if time.time() - start < min_duration:
            print(f"  ⏰ 浏览超时 ({max_wait}s)，未达到 {min_duration}s 要求")
            return False
        print(f"  浏览完成，滑动 {swipe_count} 次")
    else:
        print(f"  📋 未检测到滑动字样，min_duration=0，快速返回")
    
    time.sleep(1)
    return True


# ========================================================
# 通用执行任务入口
# ========================================================
def execute_task(device, task_name, btn_cx, btn_cy, browse_duration=20, guess_price_enabled=True):
    """通用任务执行：点击 → 等待 → 返回"""
    print(f"  🎯 执行任务: 【{task_name}】")
    device.click(btn_cx, btn_cy)
    time.sleep(3)
    
    handle_open_allow_popup(device)
    
    if guess_price_enabled and ("猜价格" in task_name):
        print(f"  检测到猜价格任务")
        handle_guess_price_game(device)
        return True
    
    # 浏览任务（含完成检测）
    execute_browse_task(device, browse_duration)
    return True


# ========================================================
# 点击3个精选宝贝（屏幕比例坐标盲点法）
# ========================================================
def click_three_selected_items(device):
    """
    点击3个商品 / 查看3个精选宝贝：
    屏幕比例坐标盲点法 —— 不依赖 OCR，按固定屏幕比例点击 3 个商品卡片。
    间隔 10 秒冷却，避免连续点击过快导致闪退。
    """
    CLICK_COOLDOWN = 10  # 每次点击之间的冷却秒数
    sw, sh = device.window_size()

    # 2 列商品网格的盲点坐标（屏幕比例），3 个不同卡片
    # 左上 / 右上 / 左下，避开顶部 tab 与底部按钮
    click_points = [
        (0.27, 0.46),
        (0.73, 0.46),
        (0.27, 0.70),
    ]

    print(f"  ✅ 放开点击3次任务：共 {len(click_points)} 次点击，每次间隔 {CLICK_COOLDOWN}s 冷却")

    for i, (rx, ry) in enumerate(click_points, start=1):
        # 在比例附近小幅抖动，避免命中卡片间隔
        cx = int(sw * (rx + random.uniform(-0.02, 0.02)))
        cy = int(sh * (ry + random.uniform(-0.015, 0.015)))

        print(f"  👆 第 {i}/{len(click_points)} 次点击商品 @({cx},{cy})")
        try:
            device.click(cx, cy)
        except Exception as e:
            print(f"  ⚠️ 第 {i} 次点击异常：{e}")

        # 进入商品详情页后停留几秒再返回，回到商品列表
        time.sleep(3)
        try:
            device.press("back")
        except Exception as e:
            print(f"  ⚠️ 返回异常：{e}")
        time.sleep(1.5)

        # 与下一次点击之间保持 10s 冷却（最后一次无需再等）
        if i < len(click_points):
            print(f"  ⏱️ 冷却 {CLICK_COOLDOWN}s 再点下一次...")
            time.sleep(CLICK_COOLDOWN)

    print(f"  ✅ 点击3次任务完成")


# ========================================================
# 结束判断：连续N轮相同任务列表 + 下滑
# ========================================================
def is_stale_task_list(prev_snapshots, current_buttons, max_same=3):
    """
    判断任务列表是否已经耗尽（连续 max_same 轮快照相同）
    
    用法：
      prev = []  # 在 while 循环外初始化
      while True:
          stale, current = is_stale_task_list(prev, u2_find_task_buttons(device), 3)
          if stale: break
          ...
    """
    current_set = frozenset(
        (b["name"][:15], b["cx"] // 60, b["cy"] // 60)
        for b in current_buttons
    )
    prev_snapshots.append(current_set)
    if len(prev_snapshots) > max_same:
        prev_snapshots.pop(0)
    
    if len(prev_snapshots) >= max_same and len(set(prev_snapshots)) == 1:
        return True, current_buttons
    return False, current_buttons


def is_stale_no_buttons(prev_snapshots, current_buttons, max_same=3):
    """
    判断任务列表是否为空 + 连续 max_same 轮无按钮（列表已滑到底）
    用于没找到任何按钮时判断是否真的结束
    """
    no_btn = len(current_buttons) == 0
    prev_snapshots.append(no_btn)
    if len(prev_snapshots) > max_same:
        prev_snapshots.pop(0)
    
    if len(prev_snapshots) >= max_same and all(prev_snapshots):
        return True
    return False
