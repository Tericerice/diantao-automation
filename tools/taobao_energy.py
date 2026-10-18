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
          "搜一搜你心仪的宝贝")
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
        nodes = [dict(text=text, cx=round(sum(p[0] for p in box)/4),
                      cy=round(sum(p[1] for p in box)/4))
                 for box, text, score in (rows or []) if score >= .4]
        source = "OCR"
    else:
        source = "U2"
    result = dict(app=app, source=source, blocks=sorted(nodes, key=lambda n: (n["cy"], n["cx"])))
    (OUT / "current.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return nodes


def task_button(nodes, title, width):
    if any(s in title for s in SKIP):
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
        if not any("搜索有福利" in n["text"] or "系统出了点问题" in n["text"]
                   for n in after_nodes):
            raise RuntimeError("返回了未知页面，请检查截图")
        guard(deadline)
        d.press("back")
        time.sleep(2)
        after_nodes = scan(d)
    after = task_progress(after_nodes)
    after_energy = energy_balance(after_nodes)
    capped_gain = (before is not None and before >= 50 and after == before
                   and before_energy is not None and after_energy is not None
                   and after_energy > before_energy)
    if before is None or after is None or (after <= before and not capped_gain):
        raise RuntimeError("未确认累计任务次数增加，停止重复操作")
    print(f"已确认任务进度 {before} -> {after}；能量 {before_energy} -> {after_energy}", flush=True)
    return after_nodes


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
            selected = None
            for n in sorted(nodes, key=lambda n: n["cy"]):
                title = re.split(r"[(（]", n["text"])[0]
                if not allowed_browse(title):
                    continue
                try:
                    task_button(nodes, title, d.window_size()[0])
                except RuntimeError:
                    continue
                selected = title
                break
            if selected is None:
                print("当前屏幕没有已确认的免费浏览任务，停止并保留现场", flush=True)
                return
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
