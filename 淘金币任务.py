"""双十一淘金币：淘宝首页 -> 领淘金币 -> 去赚淘金币，使用 OCR 识别。"""

import argparse
import re
import sys
import time
import unicodedata

from task_exclusions import is_blocked_boutique_task
from u2_scanner import (
    execute_browse_task, execute_live_task, execute_video_task,
    is_blacklisted, scan_page,
)
from utils import TB_APP, _cloud_ocr, connect_device


d = None
screen_width, screen_height = 0, 0
_verify_seen_keys = set()
ENTRY_TEXTS = ("去赚淘金币", "去赚金币")
ACTION_TEXTS = ("去完成", "去浏览", "去观看", "去逛逛", "逛一逛", "去领取", "立即领取")
CLAIM_TEXTS = ("去领取", "立即领取", "领取", "领取奖励")
ROW_ACTION_TEXTS = ACTION_TEXTS + CLAIM_TEXTS
MAX_ATTEMPTS = 2
SCAN_VIEWS = 6


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text)))


def progress(text):
    match = re.search(r"(\d+)\s*/\s*(\d+)", normalize(text))
    return tuple(map(int, match.groups())) if match else None


def key_text(text):
    """任务名比较忽略进度、空格和标点，容忍 OCR 在轮换后改变标点。"""
    return re.sub(r"[\W_]+", "", re.sub(r"\(\d+/\d+\)", "", normalize(text)))


def task_key(task):
    return key_text(task["name"])


def match_task_type(task_name, detail=""):
    """未知任务不默认执行；标题无法判断时只接受明确的媒体说明。"""
    if is_blocked_boutique_task(task_name) or is_blacklisted(task_name):
        return "skip"
    if any(word in task_name for word in (
        "答题", "课堂", "考试", "下单", "购买", "支付", "开通", "授权",
        "邀请", "分享", "订阅", "去关注", "关注店铺", "关注主播", "关注领",
        "蚂蚁", "支付宝", "抽奖", "猜价格",
    )):
        return "skip"
    if "直播" in task_name:
        return "live"
    if "视频" in task_name:
        return "video"
    if "任务到访" in task_name:
        return "visit"
    if any(word in task_name for word in (
        "浏览", "逛", "精选好物", "商品都可抵", "签到", "看看", "瞧瞧",
    )):
        return "browse"
    # 活动会轮换任务标题（如“看看#固态硬盘”）；只按说明行中的明确时长类型兜底，
    # 不使用“点击去逛”等泛化文案，避免把蚂蚁庄园等外部任务误判为浏览。
    if re.search(r"(?:滑动)?浏览\s*\d+\s*秒", detail):
        return "browse"
    if re.search(r"看直播\s*\d*\s*秒?", detail):
        return "live"
    if re.search(r"看视频\s*\d*\s*秒?", detail):
        return "video"
    return "skip"


def is_task_page(nodes):
    texts = [normalize(n["text"]) for n in nodes]
    if any("做任务赚能量" in text for text in texts):
        return False
    # OCR 可能把标题拆成“今日速赚240”“淘金币”两个文本块，分开判断。
    if any("今日速赚" in text for text in texts) and any("淘金币" in text for text in texts):
        return True
    if any(text in ("赚淘金币", "做任务赚金币", "做任务赚淘金币") for text in texts):
        return True
    # 标题滚出屏幕后，用面板特征或成组的操作按钮确认仍在任务列表。
    return looks_like_task_panel(nodes)


def click_node(node):
    cx, cy = int(node.get("cx", 0)), int(node.get("cy", 0))
    if not (0 < cx < screen_width and 0 < cy < screen_height):
        return False
    d.click(cx, cy)
    time.sleep(2)
    return True


def click_unique(nodes, labels):
    matches = [n for n in nodes if normalize(n["text"]) in labels]
    return len(matches) == 1 and click_node(matches[0])


def read_page():
    return scan_page(d) if d.app_current().get("package") == TB_APP else []


def dismiss_notice(nodes):
    return click_unique(nodes, ("我知道了", "稍后再说", "暂不", "关闭弹窗"))


def is_promo_modal(nodes):
    """识别“消费券待使用”这类居中弹窗；底部常驻横幅不在此列。"""
    texts = [normalize(n["text"]) for n in nodes]
    return any(text == "消费券待使用" or "消费券快到期" in text for text in texts)


def dismiss_promo_modal(nodes):
    """弹窗没有可识别关闭文案时用返回键退出；底部横幅不会触发。"""
    if not is_promo_modal(nodes):
        return False
    d.press("back")
    time.sleep(2)
    return True


def home_entry(nodes):
    entries = [n for n in nodes if normalize(n["text"]) == "领淘金币"]
    if entries:
        return entries[0] if len(entries) == 1 else None
    merged = [n for n in nodes if "领淘金币" in normalize(n["text"])]
    if len(merged) != 1:
        return None
    # 首页宫格文案会被 OCR 合并成一行；分块重新识别，使用局部识别的真实坐标。
    image = d.screenshot()
    top = max(0, int(merged[0]["cy"] - screen_width * .05))
    bottom = min(screen_height, int(merged[0]["cy"] + screen_width * .05))
    step = max(1, screen_width // 6)
    for left in range(0, screen_width, step):
        right = min(screen_width, left + int(step * 1.2))
        blocks = _cloud_ocr(image.crop((left, top, right, bottom)), retries=0)
        matches = [n for n in blocks if normalize(n["text"]) == "领淘金币"]
        if len(matches) == 1:
            return dict(matches[0], cx=matches[0]["cx"] + left, cy=matches[0]["cy"] + top)
    return None


def is_home_page(nodes):
    bottom = {normalize(n["text"]) for n in nodes if n["cy"] > screen_height * .85}
    return len(bottom & {"视频", "消息", "购物车", "我的淘宝"}) >= 3 and any(
        normalize(n["text"]) == "推荐" and n["cy"] < screen_height * .15 for n in nodes)


def navigate_to_task_list():
    """重新启动淘宝，从首页逐步确认入口；不使用固定坐标。"""
    d.app_start(TB_APP, stop=True)
    time.sleep(5)
    for _ in range(8):
        nodes = read_page()
        if dismiss_notice(nodes):
            continue
        entry = home_entry(nodes)
        if entry:
            break
        home = [n for n in nodes if normalize(n["text"]) == "首页"
                and n["cy"] > screen_height * .85]
        if len(home) == 1:
            if not click_node(home[0]):
                return False
        elif is_home_page(nodes):
            d.swipe(screen_width // 2, int(screen_height * .3),
                    screen_width // 2, int(screen_height * .8), duration=.4)
            time.sleep(2)
        else:
            d.press("back")
            time.sleep(2)
    else:
        print("  未确认淘宝首页的【领淘金币】入口，停止")
        return False

    if not click_node(entry):
        return False
    for _ in range(4):
        nodes = read_page()
        if dismiss_notice(nodes) or dismiss_promo_modal(nodes):
            continue
        if click_unique(nodes, ENTRY_TEXTS):
            break
        # 弹窗/返回键把页面带回首页时，重新点击【领淘金币】再试。
        entry = home_entry(nodes)
        if entry and click_node(entry):
            continue
        time.sleep(2)
    else:
        print("  未找到唯一的【去赚淘金币 / 去赚金币】入口，停止")
        return False
    for _ in range(3):
        if is_task_page(read_page()):
            print("  已进入淘金币任务列表")
            return True
        time.sleep(2)
    print("  点击入口后未确认金币任务列表，停止")
    return False


def parse_task_list(nodes, include_skipped=False):
    """匹配金币图标或文字按钮与所在任务行，拒绝纯数字及未定位标题的按钮。"""
    if not is_task_page(nodes):
        return []
    nodes = [dict(n, text=normalize(n["text"])) for n in nodes]
    split = next((n["cy"] for n in nodes if n["text"] == "更多专享福利"), screen_height)
    buttons = [n for n in nodes if n["cx"] > screen_width * .7
               and (n["text"] in ACTION_TEXTS + CLAIM_TEXTS
                    or (n["cy"] < split and re.fullmatch(r"\+\d+", n["text"])))]
    results = []
    seen = set()
    for button in buttons:
        # 标题位于奖励图标左上方；下方的“浏览15秒”等小字只作为任务说明。
        titles = [
            n for n in nodes
            if screen_width * .15 < n["cx"] < screen_width * .75
            and -.008 * screen_height <= button["cy"] - n["cy"] <= .045 * screen_height
            and len(n["text"]) >= 2
            and n["text"] not in ACTION_TEXTS + CLAIM_TEXTS
            and not re.fullmatch(r"[\d+()/]+", n["text"])
            and not any(word in n["text"] for word in (
                "额外", "今日速赚", "更多专享", "更多金币", "点击去逛", "参与答题",
            ))
        ]
        titles = [n for n in titles if not re.fullmatch(r"(?:滑动)?浏览\d+秒", n["text"])]
        if not titles:
            continue
        titles.sort(key=lambda n: abs(n["cy"] - button["cy"]))
        if len(titles) > 1 and abs(titles[0]["cy"] - titles[1]["cy"]) < screen_height * .008:
            # 同行拆分标题必须合并，避免漏掉三商品任务的后半段。
            row = sorted([n for n in titles if abs(n["cy"] - titles[0]["cy"]) < screen_height * .008],
                         key=lambda n: n["cx"])
            name = "".join(n["text"] for n in row)
        else:
            name = titles[0]["text"]
        title_y = titles[0]["cy"]
        details = " ".join(n["text"] for n in nodes
                           if n["cx"] < screen_width * .75
                           and 0 <= n["cy"] - title_y <= screen_height * .03)
        task_progress = progress(details)
        kind = match_task_type(name, details)
        if task_progress and task_progress[0] >= task_progress[1]:
            kind = "skip"
        if kind != "skip" and button["text"] in CLAIM_TEXTS:
            kind = "claim"
        duration = re.search(r"(\d+)(秒|分钟)", details)
        seconds = int(duration[1]) * (60 if duration[2] == "分钟" else 1) if duration else 60
        task = dict(name=name, type=kind, cx=button["cx"], cy=button["cy"],
                    progress=task_progress, seconds=seconds, click_text=button["text"],
                    detail=details)
        key = task_key(task)
        if key not in seen and (include_skipped or kind != "skip"):
            seen.add(key)
            results.append(task)
    return results


def exec_task(task_def):
    """执行器保留独立屏蔽门禁，调用者不得绕过解析器的限制。"""
    kind, name = task_def["type"], task_def["name"]
    if kind == "click_three" or is_blocked_boutique_task(name):
        return False
    if kind not in ("browse", "live", "video", "claim", "visit"):
        return False
    if match_task_type(name, task_def.get("detail", "")) == "skip":
        return False
    # 重新识别并定位，避免点击上一轮扫描留下的过期坐标。
    fresh = [task for task in parse_task_list(read_page())
             if task_key(task) == task_key(task_def)
             and task["type"] == kind and task["progress"] == task_def.get("progress")]
    if len(fresh) != 1 or not click_node(fresh[0]):
        return False
    if kind in ("claim", "visit"):
        return True
    # 外部跳转不滑动；返回和到账检查统一由主循环负责。
    if d.app_current().get("package") != TB_APP:
        return False
    landed = read_page()
    if not landed or is_task_page(landed):
        return False
    seconds = fresh[0]["seconds"]
    if kind == "live":
        return execute_live_task(d, name, fresh[0]["cx"], fresh[0]["cy"], duration=seconds + 5)
    if kind == "video":
        return execute_video_task(d, name, fresh[0]["cx"], fresh[0]["cy"],
                                  duration=seconds, verify_media_page=True)
    return execute_browse_task(d, min_duration=seconds, max_wait=max(120, seconds + 60))


def back_to_task_page():
    """每次回退后重读；回退耗尽必须返回失败。"""
    for attempt in range(6):
        if is_task_page(read_page()):
            return True
        if attempt < 5:
            d.press("back")
            time.sleep(2)
    print("  未能返回淘金币任务列表，停止本轮执行")
    return False


def row_action_buttons(nodes, title):
    """返回任务标题同一行的奖励/操作按钮，用于复核领奖类任务。"""
    return [n for n in nodes
            if n["cx"] > screen_width * .7
            and abs(n["cy"] - title["cy"]) < screen_height * .045
            and (normalize(n["text"]) in ROW_ACTION_TEXTS
                 or re.fullmatch(r"\+\d+", normalize(n["text"])))]


def verify_task(before):
    """从列表顶部逐屏复核；屏幕滚动或任务轮换时才不会误判失败。"""
    global _verify_seen_keys
    _verify_seen_keys = set()
    nodes = list_top()
    key = task_key(before)
    original_button = normalize(before.get("click_text", ""))
    for view in range(SCAN_VIEWS):
        if not is_task_page(nodes):
            return False
        _verify_seen_keys.update(key_text(n["text"]) for n in nodes)
        matches = [task for task in parse_task_list(nodes, include_skipped=True)
                   if task_key(task) == key]
        if len(matches) == 1:
            after = matches[0]["progress"]
            if before.get("progress") and after and after[0] > before["progress"][0]:
                return True
        # 同一任务可能在主列表和“更多专享福利”重复展示，按全部同名标题复核。
        titles = [n for n in nodes if key_text(n["text"]) == key]
        if titles:
            # 完成后金币入口会消失，但标题仍显示 (2/2)，不能依赖可点击行解析。
            if any(before.get("progress") and (after := progress(n["text"]))
                   and after[0] > before["progress"][0] for n in titles):
                return True
            if any(normalize(n["text"]) in ("已完成", "已领取")
                   and n["cx"] > screen_width * .7
                   and any(abs(n["cy"] - title["cy"]) < screen_height * .045 for title in titles)
                   for n in nodes):
                return True
            # 到访/领奖类任务领取成功后按钮会消失；原按钮文案不在任何同名行即视为到账。
            if before.get("type") in ("claim", "visit"):
                if original_button:
                    remaining = [
                        n for n in nodes
                        if normalize(n["text"]) == original_button
                        and any(abs(n["cy"] - title["cy"]) < screen_height * .045
                                for title in titles)
                    ]
                else:
                    remaining = [n for title in titles
                                 for n in row_action_buttons(nodes, title)]
                if not remaining:
                    return True
            # 已定位到任务行但没有进度增长，直接判定本次未到账。
            return False
        if view == SCAN_VIEWS - 1:
            break
        scroll_list()
        nodes = read_page()
    return False


def scroll_list():
    d.swipe(screen_width // 2, int(screen_height * .75),
            screen_width // 2, int(screen_height * .48), duration=.4)
    time.sleep(2)


def looks_like_task_panel(nodes):
    """顶部标题滚出屏幕后仍能确认当前是金币任务面板。"""
    texts = [normalize(n["text"]) for n in nodes]
    if any(
        "今日速赚" in text or "更多专享福利" in text
        or "完成下方任务得额外金币" in text
        or text in ("换一换", "更多金币等你赚")
        for text in texts
    ):
        return True
    # 列表深处可能只剩任务行；至少两个操作/奖励入口才判定为面板。
    actions = [text for text in texts
               if text in ROW_ACTION_TEXTS or re.fullmatch(r"\+\d+", text)]
    return len(actions) >= 2


def list_top():
    """任务面板会因执行/轮换停在半屏；核验与选择前回到顶部基准。"""
    nodes = read_page()
    top_texts = ("今日速赚", "完成下方任务得额外金币")
    for _ in range(SCAN_VIEWS - 1):
        if any(marker in normalize(n["text"]) for marker in top_texts for n in nodes):
            return nodes
        # 未知页面禁止盲滑，交给调用方按“任务页丢失”停止。
        if not looks_like_task_panel(nodes):
            return nodes
        d.swipe(screen_width // 2, int(screen_height * .32),
                screen_width // 2, int(screen_height * .72), duration=.3)
        time.sleep(1)
        nodes = read_page()
    return nodes


def next_task(attempts, finished, confirmed_progress, expanded):
    """从顶部逐屏查找第一个未完成的白名单任务。"""
    nodes = list_top()
    for view in range(SCAN_VIEWS):
        if not is_task_page(nodes):
            return None, nodes, expanded
        tasks = [t for t in parse_task_list(nodes)
                 if task_key(t) not in finished
                 and attempts.get(task_key(t), 0) < MAX_ATTEMPTS
                 and (not t["progress"]
                      or t["progress"][0] >= confirmed_progress.get(task_key(t), 0))]
        if tasks:
            return tasks[0], nodes, expanded
        if not expanded and any(normalize(n["text"]) == "更多专享福利" for n in nodes):
            # OCR 可能带出“展开v/展开∨”等后缀，按前缀匹配。
            expand = [n for n in nodes if normalize(n["text"]).startswith("展开")
                      and n["cy"] > screen_height * .5]
            if len(expand) == 1 and click_node(expand[0]):
                expanded = True
                nodes = read_page()
                continue
        if view == SCAN_VIEWS - 1:
            break
        scroll_list()
        nodes = read_page()
    return None, nodes, expanded


def run_tasks(max_tasks=30):
    attempts, finished = {}, set()
    confirmed_progress = {}
    total, confirmed = 0, 0
    expanded = False
    while total < max_tasks:
        task, nodes, expanded = next_task(
            attempts, finished, confirmed_progress, expanded)
        if task is None:
            if not is_task_page(nodes):
                print("  当前页面无法确认为金币任务列表，停止")
            else:
                print("  未再找到可执行的白名单任务，停止")
            break
        key = task_key(task)
        attempts[key] = attempts.get(key, 0) + 1
        total += 1
        print(f"  [{total}] {task['name']} ({task['type']}, {task['seconds']}秒)")
        try:
            exec_task(task)
        except Exception as exc:
            print(f"  任务执行异常：{exc}")
        if not back_to_task_page():
            break
        if verify_task(task):
            confirmed += 1
            if task["progress"]:
                confirmed_progress[key] = task["progress"][0] + 1
            if not task["progress"] or task["progress"][0] + 1 >= task["progress"][1]:
                finished.add(key)
            else:
                attempts[key] = 0
        else:
            if key not in _verify_seen_keys:
                # 任务被轮换离场时不能记作失败，否则它稍后带进度回来会被永久排除。
                attempts[key] = 0
                print("  任务已离开当前列表，稍后复查")
            else:
                print("  未确认进度或到账；同项最多尝试两次")
    print(f"  共尝试 {total} 次，确认完成/进度增长 {confirmed} 次；"
          "面板轮换或进度重置时以实际金币到账为准")
    return dict(attempted=total, confirmed=confirmed)


def main(argv=None):
    global d, screen_width, screen_height
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "enter", "scan"))
    parser.add_argument("--max-tasks", type=int, default=30)
    args = parser.parse_args(argv)
    if args.max_tasks <= 0:
        parser.error("--max-tasks 必须大于 0")
    d = connect_device()
    screen_width, screen_height = d.window_size()
    print("  淘金币任务：首页 -> 领淘金币 -> 去赚淘金币")
    if args.command == "scan":
        nodes = read_page()
        print(f"  金币任务列表：{is_task_page(nodes)}")
        for task in parse_task_list(nodes, include_skipped=True):
            print(task)
        return 0 if is_task_page(nodes) else 1
    if not navigate_to_task_list():
        return 1
    if args.command == "run":
        run_tasks(args.max_tasks)
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("  手动停止")
        sys.exit(130)
