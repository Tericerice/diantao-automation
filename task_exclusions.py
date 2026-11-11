"""点淘任务的明确排除项；只按任务名称判断，不操作设备。"""
import re
import unicodedata

# 用户 2026-11-10 指示：睡觉赚元宝（含三次点击子任务）整体拉黑，
# 不进入任何批量/顺序调度，也不计完成。
BLOCKED_TASK_FILES = frozenset({"睡觉赚元宝.py", "睡觉赚元宝"})


def is_blocked_task_file(name):
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    base = text.replace("\\", "/").rsplit("/", 1)[-1]
    return base in BLOCKED_TASK_FILES or base.removesuffix(".py") in BLOCKED_TASK_FILES


def is_blocked_sleep_task_name(name):
    """三次点击类气泡的硬屏蔽；NFKC + 去空白后匹配，返回 False 表示放行。"""
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = re.sub(r"[\s​‌‍﻿]+", "", text)
    keywords = (
        "精选宝贝", "查看3个", "看3个", "点击3个", "查看3件",
        "查看三次", "查看三个", "查看3次", "看三个", "看3件",
        "看三次", "点击三个", "点击3件", "点击三次", "点击3次",
    )
    if any(keyword in text for keyword in keywords):
        return True
    # 任务名被 OCR 拆开时（“查看 3 个精选”），再以“查看 + 量词”兜底。
    return "查看" in text and any(unit in text for unit in ("个", "件", "次"))


def is_blocked_boutique_task(name):
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = re.sub(r"[\s\u200b\u200c\u200d\ufeff]+", "", text)
    if "精选宝贝" in text:
        return True
    # 同一类商品任务会改名为特惠/优惠，或被 OCR 截成“查看3个”。
    product = re.search(r"精选|优选|特惠|优惠|宝贝|商品|好物", text)
    count = re.search(r"(?:查看|看|点击|点开|浏览)(?:3|三)(?:个|件|次)", text)
    if count:
        suffix = text[count.end():]
        if product or re.fullmatch(r"(?:[（(]\d+/\d+[）)])?", suffix):
            return True
    if product and re.search(r"(?:查看|看|点击|点开|浏览).{0,16}(?:3|三)次", text):
        return True
    return bool(re.search(r"(?:精选|优选|特惠|优惠).*?(?:宝贝|商品)", text)
                and re.search(r"[（(]\d+/3[）)]", text))
