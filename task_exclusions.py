"""点淘任务的明确排除项；只按任务名称判断，不操作设备。"""
import re
import unicodedata


def is_blocked_boutique_task(name):
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = re.sub(r"[\s\u200b\u200c\u200d\ufeff]+", "", text)
    return "精选宝贝" in text
