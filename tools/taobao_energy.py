"""淘金币双11赚能量：U2 优先扫描，OCR 后备，逐项浏览并复查。

uv run --no-project --with uiautomator2 --with rapidocr-onnxruntime python tools/taobao_energy.py scan
uv run --no-project --with uiautomator2 --with rapidocr-onnxruntime python tools/taobao_energy.py browse 好物随心逛 --seconds 25
默认不批量点击未知任务，不升级赛车、不花积分、不购买、不发送邀请。
"""
import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uiautomator2 as u2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from device_connection import connect_with_retry

TB = "com.taobao.taobao"
SKIP = ("升级赛车", "小游戏", "积分", "拍立淘", "邀请", "下单", "购买", "开通", "订阅", "预约")
BROWSE = ("好物随心逛", "好物沉浸看", "去省钱卡领红包", "去芭芭农场领水果", "去签到领红包",
          "搜一搜你心仪的宝贝", "天天签到免费拿IP周边")
# 仅访问已实测的页面，不操作目的应用内的消费、抽奖、授权或邀请。
VISIT = {
    "领闪购红包下单直接省": TB,
    "看淘宝视频领红包": TB,
    "去微博看看热搜": "com.sina.weibo",
    "去闲鱼签到省钱": "com.taobao.idlefish",
    "去快手打卡领手机": "com.kuaishou.nebula",
    "去一淘签到领现金": "com.taobao.etao",
    "去淘宝特价版0元购": "com.taobao.litetao",
    "去蚂蚁森林收能量": "com.eg.android.AlipayGphone",
    "逛一逛支付宝金豆夺宝": "com.eg.android.AlipayGphone",
    "去支付宝抽1000元红包": "com.eg.android.AlipayGphone",
    "去百度App领现金": "com.baidu.searchbox",
}
OUT = Path(__file__).resolve().parents[1] / "screenshots" / "taobao_energy"
_ocr = None


def guard(deadline):
    if datetime.now(timezone(timedelta(hours=8))) >= deadline:
        raise RuntimeError("手机控制授权已到期")


def scan(d):
    global _ocr
    OUT.mkdir(parents=True, exist_ok=True)
    shot = d.screenshot()
    shot.save(OUT / "current.png")
    nodes = []
    app = d.app_current()
    # 实测此活动的 Themis WebView 不暴露文本，倒计时页面的 dump 还会长时间等待空闲。
    tree = "<hierarchy/>" if "TMSActivity" in app["activity"] else d.dump_hierarchy()
    for n in ET.fromstring(tree).iter("node"):
        if n.get("package") != app["package"]:
            continue
        text = n.get("text") or n.get("content-desc")
        bounds = list(map(int, re.findall(r"\d+", n.get("bounds", ""))))
        if text and len(bounds) == 4:
            x1, y1, x2, y2 = bounds
            nodes.append(dict(text=text, cx=(x1+x2)//2, cy=(y1+y2)//2))
    if not any("做任务赚能量" in n["text"] for n in nodes):
        from rapidocr_onnxruntime import RapidOCR
        if _ocr is None:
            _ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        rows, _ = _ocr(str(OUT / "current.png"))
        source = "U2+OCR" if nodes else "OCR"
        for box, text, score in rows or []:
            node = dict(text=text, cx=round(sum(p[0] for p in box)/4),
                        cy=round(sum(p[1] for p in box)/4))
            if score >= .4 and not any(n["text"] == text and abs(n["cx"]-node["cx"]) < 30
                                      and abs(n["cy"]-node["cy"]) < 30 for n in nodes):
                nodes.append(node)
    else:
        source = "U2"
    result = dict(app=app, source=source, blocks=sorted(nodes, key=lambda n: (n["cy"], n["cx"])))
    (OUT / "current.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return nodes


def task_button(nodes, title, width):
    if any(s in title for s in SKIP) and title != "领闪购红包下单直接省":
        raise RuntimeError("此任务按约定跳过: " + title)
    if not any("做任务赚能量" in n["text"] for n in nodes):
        raise RuntimeError("当前不是赚能量任务列表")
    matches = [n for n in nodes if title in n["text"]]
    if len(matches) != 1:
        raise RuntimeError("任务未唯一定位: " + title)
    row = matches[0]
    progress = re.search(r"[(（](\d+)\s*/\s*(\d+)[)）]", row["text"])
    if progress and int(progress[1]) >= int(progress[2]):
        raise RuntimeError("任务已经完成: " + title)
    buttons = [n for n in nodes if n["text"] == "去完成" and n["cx"] > width*.7
               and abs(n["cy"]-row["cy"]) < width*.075]
    if len(buttons) != 1:
        raise RuntimeError("任务按钮未唯一定位: " + title)
    return buttons[0]


def task_progress(nodes):
    for n in nodes:
        if n["cx"] < 250 and re.fullmatch(r"\d+/50", n["text"]):
            return int(n["text"].split("/")[0])
    return None


def energy_balance(nodes):
    for n in nodes:
        if n["cx"] < 300 and 300 < n["cy"] < 390 and re.fullmatch(r"\d+>?", n["text"]):
            return int(n["text"].rstrip(">"))
    return None


def allowed_browse(title):
    return not any(s in title for s in SKIP) and (title in BROWSE or title.startswith("看看#"))


def task_kind(title):
    if allowed_browse(title):
        return "taobao"
    if title in VISIT:
        if VISIT[title] == TB:
            return "taobao"
        return "alipay" if VISIT[title] == "com.eg.android.AlipayGphone" else "external"
    return "skip"


def verify_gain(d, nodes, before, before_energy, deadline):
    # 回到列表后，金币动画可能暂时遮住累计次数；只重读，不重复做任务。
    for attempt in range(3):
        after, balance = task_progress(nodes), energy_balance(nodes)
        if (after is not None and before is not None and after > before) or (
                after == before and after is not None and after >= 50
                and balance is not None and before_energy is not None and balance > before_energy):
            print(f"已确认任务进度 {before} -> {after}；能量 {before_energy} -> {balance}", flush=True)
            return nodes
        if attempt < 2:
            if task_progress(nodes) is None and any("做任务赚能量" in n["text"] for n in nodes):
                w, h = d.window_size()
                guard(deadline)
                d.swipe(w*.5, h*.4, w*.5, h*.9, duration=.5)
            time.sleep(3)
            nodes = scan(d)
    raise RuntimeError("未确认任务奖励增加，保留现场")


def visit(d, title, deadline, nodes):
    before, balance = task_progress(nodes), energy_balance(nodes)
    if before is None or balance is None:
        raise RuntimeError("请将任务列表滚到顶部，确保累计次数和能量可见")
    package = VISIT[title]
    installed = package == TB or bool(d.adb_device.shell(["pm", "path", package]).strip())
    button = task_button(nodes, title, d.window_size()[0])
    guard(deadline)
    d.click(button["cx"], button["cy"])
    # 初次冷启动/登录后的跳转较慢，不能把前几秒空白当成失败。
    for second in range(30 if installed else 5):
        guard(deadline)
        time.sleep(1)
        if second in (4, 14, 24):
            current = d.app_current()["package"]
            if not installed:
                break
            if current == "com.oplus.securitypermission":
                dialog = scan(d)
                once = [n for n in dialog if n["text"] == "仅本次允许"]
                opening = [n for n in dialog if n["text"] == "打开"]
                if not any("淘宝" in n["text"] and "想要打开" in n["text"] for n in dialog):
                    raise RuntimeError("遇到未知应用授权，停止")
                buttons = once or opening
                if len(buttons) != 1:
                    raise RuntimeError("未识别一次性打开按钮，停止")
                guard(deadline)
                d.click(buttons[0]["cx"], buttons[0]["cy"])
            elif current in ("com.android.chrome", "com.heytap.market", "com.android.packageinstaller"):
                print(f"{title} 进入下载/安装页面，直接返回", flush=True)
                break
            elif current not in (TB, package):
                raise RuntimeError("访问任务跳转到未知应用: " + current)
    if not installed:
        print(f"{title}：已查看任务入口，未安装应用，不点击下载", flush=True)
    guard(deadline)
    if d.app_current()["package"] == TB:
        d.press("back")
    else:
        d.app_start(TB)
    time.sleep(4)
    nodes = scan(d)
    if not any("做任务赚能量" in n["text"] for n in nodes):
        if d.app_current()["package"] == TB and "BrowserActivity" in d.app_current()["activity"]:
            guard(deadline)
            d.press("back")
            time.sleep(3)
        nodes = enter(d, deadline)
    try:
        return verify_gain(d, nodes, before, balance, deadline)
    except RuntimeError:
        nodes = scan(d)
        if not any("做任务赚能量" in n["text"] for n in nodes):
            raise
        print(f"{title} 未确认到账，本轮不再重复尝试", flush=True)
        return nodes


def next_task(d, nodes, attempted, deadline):
    """先扫描列表各页，再按淘宝、支付宝、其他应用的顺序选择。"""
    header = [n for n in nodes if n["cx"] < 250 and re.fullmatch(r"\d+/50", n["text"])]
    candidates = {}
    w, h = d.window_size()
    for _ in range(4):
        for n in nodes:
            title = re.split(r"[(（]", n["text"])[0]
            if task_kind(title) == "skip" or title in attempted:
                continue
            try:
                task_button(nodes, title, w)
            except RuntimeError:
                continue
            candidates[title] = {"taobao": 0, "alipay": 1, "external": 2}[task_kind(title)]
        if any("以上奖励均为最高奖励" in n["text"] for n in nodes):
            break
        guard(deadline)
        d.swipe(w*.5, h*.87, w*.5, h*.43, duration=.5)
        time.sleep(2)
        nodes = scan(d)
    selected = min(candidates, key=candidates.get) if candidates else None
    for _ in range(4):
        guard(deadline)
        d.swipe(w*.5, h*.4, w*.5, h*.9, duration=.5)
        time.sleep(1)
    nodes = scan(d)
    header = [n for n in nodes if n["cx"] < 250 and re.fullmatch(r"\d+/50", n["text"])] or header
    if selected:
        for _ in range(4):
            try:
                task_button(nodes, selected, w)
                return selected, nodes if task_progress(nodes) is not None else nodes + header
            except RuntimeError:
                guard(deadline)
                d.swipe(w*.5, h*.87, w*.5, h*.43, duration=.5)
                time.sleep(2)
                nodes = scan(d)
        raise RuntimeError("任务换页后未能重新定位: " + selected)
    return None, nodes


def enter(d, deadline):
    """复用农场库的首页 U2 入口；活动内部用实测可读的 OCR。"""
    if d.app_current()["package"] != TB:
        guard(deadline)
        d.app_start(TB)
        time.sleep(3)
    if any(name in d.app_current()["activity"] for name in ("Welcome", "TBMainActivity")):
        entry = d(description="领淘金币")
        if entry.exists:
            guard(deadline)
            entry.click()
            time.sleep(5)
    nodes = scan(d)
    if any("做任务赚能量" in n["text"] for n in nodes):
        return nodes
    if not any("淘金币双11" in n["text"] for n in nodes):
        raise RuntimeError("请先回到淘宝首页，确认领淘金币入口；未点击未知页面")
    buttons = [n for n in nodes if n["text"] == "赚能量"]
    if len(buttons) != 1:
        raise RuntimeError("未唯一识别赚能量按钮")
    guard(deadline)
    d.click(buttons[0]["cx"], buttons[0]["cy"])
    time.sleep(2)
    return scan(d)


def browse(d, title, seconds, deadline, nodes):
    if d.app_current()["package"] != TB:
        raise RuntimeError("浏览任务必须从淘宝开始")
    before = task_progress(nodes)
    if before is None:
        raise RuntimeError("请将任务列表滚到顶部，确保累计次数可见")
    before_energy = energy_balance(nodes)
    button = task_button(nodes, title, d.window_size()[0])
    guard(deadline)
    d.click(button["cx"], button["cy"])
    time.sleep(4)
    current = d.app_current()["package"]
    if current != TB:
        guard(deadline)
        d.app_start(TB)
        raise RuntimeError("任务跳转到其他应用，请先分类: " + current)
    if "搜一搜" in title:
        search_nodes = scan(d)
        if not any("搜索有福利" in n["text"] for n in search_nodes):
            raise RuntimeError("未识别到任务专用搜索页")
        topics = [n for n in search_nodes if n["text"] in ("牙刷", "牛肉", "u盘", "移动硬盘", "固态硬盘")]
        if not topics:
            raise RuntimeError("未识别到可点击的搜索推荐词")
        topic = topics[(before or 0) % len(topics)]
        guard(deadline)
        d.click(topic["cx"], topic["cy"])
        time.sleep(3)
    w, h = d.window_size()
    for second in range(min(max(seconds, 5), 60)):
        guard(deadline)
        if second % 6 == 0:
            d.swipe(w*.5, h*.78, w*.5, h*.4, duration=.5)
        time.sleep(1)
    d.screenshot().save(OUT / "browse.png")
    guard(deadline)
    d.press("back")
    time.sleep(3)
    after_nodes = scan(d)
    for _ in range(2):
        if any("做任务赚能量" in n["text"] for n in after_nodes):
            break
        if not any("搜索有福利" in n["text"] or "系统出了点问题" in n["text"] or "已得400" in n["text"]
                   for n in after_nodes):
            raise RuntimeError("返回了未知页面，请检查截图")
        guard(deadline)
        d.press("back")
        time.sleep(2)
        after_nodes = scan(d)
    return verify_gain(d, after_nodes, before, before_energy, deadline)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "enter", "scan", "auto", "browse", "tap", "back", "swipe", "text"])
    parser.add_argument("values", nargs="*")
    parser.add_argument("--serial")
    parser.add_argument("--seconds", type=int, default=25)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--deadline", default="2026-10-19T00:00:00+08:00")
    args = parser.parse_args()
    deadline = datetime.fromisoformat(args.deadline)
    guard(deadline)
    serial = args.serial
    if not serial:
        devices = u2.adbutils.adb.device_list()
        if len(devices) != 1:
            raise RuntimeError("请用 --serial 明确选择设备")
        serial = devices[0].serial
    d = connect_with_retry(serial)
    if args.action == "enter":
        enter(d, deadline)
        return
    elif args.action in ("auto", "run"):
        nodes = enter(d, deadline) if args.action == "run" else scan(d)
        attempted = set()
        for _ in range(min(max(args.repeat, 1), 30)):
            if not any("做任务赚能量" in n["text"] for n in nodes):
                raise RuntimeError("请先进入赚能量任务列表")
            rewards = [n for n in nodes if n["text"] == "立即领取" and n["cy"] < 900]
            for reward in rewards:
                guard(deadline)
                d.click(reward["cx"], reward["cy"])
                time.sleep(2)
            if rewards:
                nodes = scan(d)
            selected, nodes = next_task(d, nodes, attempted, deadline)
            if selected is None:
                print("当前屏幕没有已确认的免费浏览任务，停止并保留现场", flush=True)
                return
            if selected in VISIT:
                attempted.add(selected)
                nodes = visit(d, selected, deadline, nodes)
            else:
                nodes = browse(d, selected, args.seconds, deadline, nodes)
        return
    elif args.action == "browse":
        title = " ".join(args.values)
        if not allowed_browse(title):
            raise RuntimeError("只自动浏览已确认的免费任务；其他任务先 scan 检查")
        nodes = scan(d)
        for _ in range(min(max(args.repeat, 1), 10)):
            nodes = browse(d, title, args.seconds, deadline, nodes)
        return
    elif args.action == "tap":
        if len(args.values) != 2:
            parser.error("tap 需要已检查截图中的 x y 坐标")
        d.click(*map(int, args.values))
        time.sleep(3)
    elif args.action == "swipe":
        d.swipe(*map(int, args.values), duration=.5)
        time.sleep(2)
    elif args.action == "text":
        d.send_keys(" ".join(args.values))
        time.sleep(2)
    elif args.action == "back":
        d.press("back")
        time.sleep(3)
    scan(d)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
