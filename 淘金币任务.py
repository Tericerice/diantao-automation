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
ENTRY_TEXTS = ("去赚淘金币", "去赚金币")
ACTION_TEXTS = ("去完成", "去浏览", "去观看", "去逛逛", "逛一逛", "去领取", "立即领取")
CLAIM_TEXTS = ("去领取", "立即领取", "领取")
MAX_ATTEMPTS = 2
EMPTY_LIMIT = 3


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text)))


def progress(text):
    match = re.search(r"(\d+)\s*/\s*(\d+)", normalize(text))
    return tuple(map(int, match.groups())) if match else None


def task_key(task):
    return re.sub(r"\(\d+/\d+\)", "", normalize(task["name"]))


def match_task_type(task_name):
    """未知任务不默认执行，保留商品三次点击任务的统一屏蔽规则。"""
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
    if any(word in task_name for word in ("浏览", "逛", "精选好物", "商品都可抵", "签到")):
        return "browse"
    return "skip"


def is_task_page(nodes):
    texts = [normalize(n["text"]) for n in nodes]
    if any("做任务赚能量" in text for text in texts):
        return False
    return any(
        ("今日速赚" in text and "淘金币" in text)
        or text in ("赚淘金币", "做任务赚金币", "做任务赚淘金币")
        for text in texts
    )


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
        if dismiss_notice(nodes):
            continue
        if click_unique(nodes, ENTRY_TEXTS):
            break
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
        kind = match_task_type(name)
        if task_progress and task_progress[0] >= task_progress[1]:
            kind = "skip"
        if kind != "skip" and button["text"] in CLAIM_TEXTS:
            kind = "claim"
        duration = re.search(r"(\d+)(秒|分钟)", details)
        seconds = int(duration[1]) * (60 if duration[2] == "分钟" else 1) if duration else 60
        task = dict(name=name, type=kind, cx=button["cx"], cy=button["cy"],
                    progress=task_progress, seconds=seconds, click_text=button["text"])
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
    if kind not in ("browse", "live", "video", "claim", "visit") or match_task_type(name) == "skip":
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


def verify_task(before):
    """仅有进度增长或同一任务行的明确完成状态才计入已确认。"""
    for _ in range(2):
        nodes = read_page()
        if not is_task_page(nodes):
            return False
        matches = [task for task in parse_task_list(nodes, include_skipped=True)
                   if task_key(task) == task_key(before)]
        if len(matches) == 1:
            after = matches[0]["progress"]
            if before.get("progress") and after and after[0] > before["progress"][0]:
                return True
        title = [n for n in nodes
                 if re.sub(r"\(\d+/\d+\)", "", normalize(n["text"])) == task_key(before)]
        if len(title) == 1:
            # 完成后金币入口会消失，但标题仍显示 (2/2)，不能依赖可点击行解析。
            after = progress(title[0]["text"])
            if before.get("progress") and after and after[0] > before["progress"][0]:
                return True
            if any(normalize(n["text"]) in ("已完成", "已领取")
                   and n["cx"] > screen_width * .7
                   and abs(n["cy"] - title[0]["cy"]) < screen_height * .045 for n in nodes):
                return True
        time.sleep(2)
    return False


def scroll_list():
    d.swipe(screen_width // 2, int(screen_height * .75),
            screen_width // 2, int(screen_height * .48), duration=.4)
    time.sleep(2)


def run_tasks(max_tasks=30):
    attempts, finished = {}, set()
    confirmed_progress = {}
    total, confirmed, empty_times = 0, 0, 0
    expanded = False
    while total < max_tasks:
        nodes = read_page()
        if not is_task_page(nodes):
            print("  当前页面无法确认为金币任务列表，停止")
            break
        tasks = [t for t in parse_task_list(nodes)
                 if task_key(t) not in finished
                 and attempts.get(task_key(t), 0) < MAX_ATTEMPTS
                 and (not t["progress"] or t["progress"][0] >= confirmed_progress.get(task_key(t), 0))]
        if not tasks:
            empty_times += 1
            if empty_times >= EMPTY_LIMIT:
                break
            if not expanded and any(normalize(n["text"]) == "更多专享福利" for n in nodes):
                expand = [n for n in nodes if normalize(n["text"]) == "展开"
                          and n["cy"] > screen_height * .5]
                if len(expand) == 1 and click_node(expand[0]):
                    expanded = True
                    empty_times = 0
                    continue
            scroll_list()
            continue
        empty_times = 0
        task = tasks[0]
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
            print("  未确认进度或到账；同项最多尝试两次")
    print(f"  共尝试 {total} 次，确认完成/进度增长 {confirmed} 次")
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
