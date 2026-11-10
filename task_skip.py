"""点淘黑名单收口的共享离线辅助；只判断任务名与本轮去重，不操作设备。"""
import unicodedata

from task_exclusions import is_blocked_boutique_task


def normalized_task_name(name):
    """按 NFKC 归一化任务名，供本轮屏蔽提示与点击次数去重使用。"""
    return unicodedata.normalize("NFKC", str(name or "")).strip()


def note_blocked_task(name, skipped_this_run=None):
    """命中屏蔽任务时每轮只提示一次；返回是否应跳过该候选。"""
    from utils import is_blacklisted

    if not is_blocked_boutique_task(name) and not is_blacklisted(name):
        return False
    key = normalized_task_name(name)
    if skipped_this_run is None or key not in skipped_this_run:
        print(f"  ⊘ 屏蔽任务: 【{name}】")
        if skipped_this_run is not None:
            skipped_this_run.add(key)
    return True


def select_executable_task(candidates, skipped_this_run, clicked=None, max_clicks=2):
    """从候选任务中选择第一个未屏蔽且未超本轮点击上限的任务。

    candidates: 可迭代的 (task_name, btn_cx, btn_cy)；屏蔽任务直接忽略并
    继续检查同屏其余任务。返回 (name, cx, cy) 或 None。
    """
    for name, cx, cy in candidates:
        if not name or note_blocked_task(name, skipped_this_run):
            continue
        key = normalized_task_name(name)
        if clicked is not None and clicked.get(key, 0) >= max_clicks:
            print(f"  ⊘ 已达上限: 【{name}】(已做{clicked[key]}次)")
            continue
        if clicked is not None:
            clicked[key] = clicked.get(key, 0) + 1
        return (name, cx, cy)
    return None
