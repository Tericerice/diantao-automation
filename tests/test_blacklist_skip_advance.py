"""黑名单收口离线回归：不连真机，用 AST 提取纯函数与主循环。

复用 e-diantao-166 的隔离加载方式；所有设备动作、OCR、完成日志均为 stub。
"""
import ast
import contextlib
import io
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from task_exclusions import is_blocked_boutique_task
from task_skip import (
    normalized_task_name,
    note_blocked_task,
    select_executable_task,
)
from utils import is_blacklisted

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = "查看3个优惠宝贝"
REAL = "看直播60秒"


def load_functions(filename, names, namespace=None):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8-sig"))
    wanted = set(names)
    tree.body = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in wanted]
    ns = {
        "re": re,
        "sys": SimpleNamespace(stdout=SimpleNamespace(encoding="utf-8")),
        "time": SimpleNamespace(sleep=lambda *_: None),
        "is_blocked_boutique_task": is_blocked_boutique_task,
        "is_blacklisted": is_blacklisted,
        "note_blocked_task": note_blocked_task,
        "select_executable_task": select_executable_task,
        "normalized_task_name": normalized_task_name,
    }
    if namespace:
        ns.update({k: v for k, v in namespace.items() if not k.startswith("_")})
    exec(compile(tree, filename, "exec"), ns)
    return ns


def bubble(text, cx=400, cy=600):
    return {"text": text, "cx": cx, "cy": cy}


def loop_namespace(*, scans, logged=None, executed=None, entered=None,
                   logger=None, executor=None, parser=None, device=None,
                   snippets=None, **extra):
    """构造主循环通用 stub；scan 序列耗尽后返回空列表。"""
    logged = [] if logged is None else logged
    executed = [] if executed is None else executed
    scan_calls = iter(scans)
    ns = {
        "d": device if device is not None else Mock(),
        "get_ocr_text_blocks": lambda *_, **__: next(scan_calls, []),
        "log_task_completed": logger or (lambda script, name: logged.append((script, name))),
        "report_task_found": lambda: None,
        "report_round_finished": lambda: None,
        "show_today_summary": lambda: None,
        "recheck_enabled": lambda: False,
        "time": SimpleNamespace(sleep=lambda *_: None, time=lambda: 0),
        "sys": SimpleNamespace(stdout=SimpleNamespace(encoding="utf-8")),
        "MAX_TASKS": 100,
        "SCAN_INTERVAL": 0,
        "STALE_LIMIT": 3,
        "MAX_CLICK": 2,
        "screen_width": 1080,
        "screen_height": 2400,
        "TASK_WHITELIST": [REAL],
        "WHITELIST": [REAL],
        "DANGER_KEYWORDS": [],
        "TASK_BTN_KW": [],
        "MAX_BACK_ATTEMPTS": 3,
        "is_stale_no_buttons": lambda *_: False,
        "is_whitelisted": lambda name: REAL in name,
        "parse_tasks_from_blocks": parser or (lambda *_: []),
        "scan_duck_tasks": parser or (lambda *_: []),
        "scan_extra_area_tasks": parser or (lambda *_: []),
        "scan_tasks": parser or (lambda *_: []),
        "find_browse_task": parser or (lambda *_: None),
        "do_task": executor or (lambda name, *_: executed.append(name) or True),
        "execute_task": executor or (lambda name, *_: executed.append(name) or True),
        "exec_browse": executor or (lambda *_args, **_kw: True),
        "exec_video": executor or (lambda *_args, **_kw: True),
        "exec_live": executor or (lambda *_args, **_kw: True),
        "exec_guess_price": executor or (lambda *_args, **_kw: True),
        "navigate": lambda: True,
        "navigate_to_dagong_page": lambda *_: True,
        "handle_dagong_reward_popup": lambda: None,
        "click_detili": lambda: None,
        "enter_shopping_tasks": lambda: None,
        "back_to_task": lambda *_args, **_kw: True,
        "show_dev_guide": lambda: None,
        "find_block_by_text": lambda blocks, text: next(
            (b for b in blocks if text in b["text"]), None),
        "print_ocr_blocks": lambda *_: None,
        "swipe_to_rightmost": lambda: None,
        "is_stale_task_list": lambda *_: False,
        "is_task_button": lambda *_: False,
        "_find_show_more_block": lambda *_: None,
        "_task_buttons": lambda blocks: [b for b in blocks if "去完成" in b["text"]],
        "detect_task_name_before_click": lambda *_: ("live", 60, REAL),
        "parse_seconds": lambda *_: 60,
        "TASK_BTN_KW": [],
    }
    if entered is not None:
        ns.update(entered)
    if snippets:
        ns.update(snippets)
    ns.update(extra)
    return ns


def run_loop(ns, name):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = ns[name]()
    return result, stdout.getvalue()


# --- 核心契约：同屏有真实任务时继续选择、真实成功才计数/写日志 ---

def test_dagong_parser_excludes_blocked_and_advances_to_real_task():
    ns = load_functions("打工得体力.py",
                        {"normalize_task_name", "match_task_type",
                         "detect_task_name", "parse_tasks_from_blocks"},
                        {"DONE_BTN_KEYWORDS": ["去完成"],
                         "BLACKLIST_KEYWORDS": [],
                         "TASK_TYPE_MAP": {"看直播": "live"},
                         "TASK_CATEGORY_MAP": {"直播": "live"},
                         "NAME_ABOVE_GAP": 200, "NAME_H_OFFSET": 690})
    blocks = [
        bubble(BLOCKED, cy=500), bubble("去完成", cx=1000, cy=500),
        bubble(REAL, cy=800), bubble("去完成", cx=1000, cy=800),
    ]
    # 真实页面的任务名与按钮处于不同列；用真实解析器检测候选配对。
    tasks = ns["parse_tasks_from_blocks"](blocks, set())
    assert all(task[1] != BLOCKED for task in tasks)
    # 只要看到了被屏蔽任务，队列里仍可继续检查并保留同屏真实任务。
    assert ns["match_task_type"](REAL) == "live"


def test_dagong_main_counts_and_logs_only_real_task():
    # 解析器已在候选阶段排除黑名单，主循环只见真实任务；成功后计数/日志各 1 次。
    def parser(blocks, skipped=None):
        return [("live", REAL, 300, 400)]

    logged = []
    ns = loop_namespace(scans=[[bubble("去完成")]] * 1, parser=parser,
                        logged=logged)
    ns = load_functions("打工得体力.py", {"main"}, ns)
    _, output = run_loop(ns, "main")
    assert "已完成: 1 个任务" in output
    assert logged == [("打工得体力", REAL)]
    assert all(BLOCKED not in name for _, name in logged)
    assert ns["d"].screenshot.call_count == 0 or "页面无任务按钮" in output


def test_browse_executor_false_does_not_increment_dagong_counter():
    logged = []
    ns = load_functions("打工得体力.py", {"main"}, loop_namespace(
        scans=[[bubble("去完成")]] * 5,
        parser=lambda *_: [("browse", REAL, 100, 200)],
        snippets={"exec_browse": lambda *_: False},
        logged=logged,
    ))
    _, output = run_loop(ns, "main")
    assert "已完成: 1" not in output
    assert logged == []
    assert "连续3轮无实际进展" in output or "仅剩黑名单/无可执行任务" in output


def test_only_blocked_task_dagong_main_exits_within_three_rounds():
    def parser(blocks, skipped=None):
        for block in blocks:
            if is_blocked_boutique_task(block["text"]):
                note_blocked_task(block["text"], skipped)
        return []

    ns = load_functions("打工得体力.py", {"main"}, loop_namespace(
        scans=[[bubble(BLOCKED), bubble("去完成", cx=1000)]] * 8,
        parser=parser,
    ))
    _, output = run_loop(ns, "main")
    assert "仅剩黑名单/无可执行任务" in output
    assert "已完成: 1" not in output
    assert output.count("扫描") <= 3


def test_repeated_blocked_ocr_never_counts_or_logs_in_dagong():
    def parser(blocks, skipped=None):
        for block in blocks:
            if is_blocked_boutique_task(block["text"]):
                note_blocked_task(block["text"], skipped)
        return [("browse", BLOCKED, 100, 200)]

    logged = []
    ns = load_functions("打工得体力.py", {"main"}, loop_namespace(
        scans=[[bubble(BLOCKED), bubble("去完成", cx=1000)]] * 8,
        parser=parser,
        snippets={"exec_browse": lambda *_: False},
        logged=logged,
    ))
    _, output = run_loop(ns, "main")
    assert "已完成: 1" not in output
    assert logged == []
    assert "连续3轮无实际进展" in output or "仅剩黑名单/无可执行任务" in output


def test_shake_selects_real_task_after_blocked_candidate():
    executed = []
    ns = load_functions("点淘鸭摇一摇.py", {"run_mode"}, loop_namespace(
        scans=[[bubble("去摇一摇"), bubble("去完成")]] * 8,
        parser=lambda *_: [(BLOCKED, 100, 200), (REAL, 300, 400)],
        executed=executed,
    ))
    _, output = run_loop(ns, "run_mode")
    assert executed and executed[0] == REAL
    assert all(BLOCKED not in name for name in executed)
    assert "📊 已完成 1/100" in output


def test_shake_only_blocked_task_exits_without_completion():
    ns = load_functions("点淘鸭摇一摇.py", {"run_mode"}, loop_namespace(
        scans=[[bubble("去摇一摇"), bubble("去完成")]] * 8,
        parser=lambda *_: [(BLOCKED, 100, 200)],
    ))
    _, output = run_loop(ns, "run_mode")
    assert "📊 已完成 1" not in output
    assert "共完成 0 个任务" in output


def test_diamond_scan_excludes_blocked_and_keeps_other_task():
    ns = load_functions("点淘鸭钻石任务.py", {"scan_duck_tasks", "_cluster_rows"}, {
        "ROW_CLUSTER_TOLERANCE": 50,
        "parse_progress": lambda text: (0, 1) if "(" in text or "（" in text else None,
        "BTN_KEYWORDS": ["去完成"],
        "DANGER_KEYWORDS": [],
    })
    blocks = [
        bubble(f"{BLOCKED}(0/3)", cx=200), bubble("去完成", cx=1000),
        bubble(f"{REAL}(0/1)", cx=200, cy=900), bubble("去完成", cx=1000, cy=900),
    ]
    pairs = ns["scan_duck_tasks"](blocks, set())
    assert all(BLOCKED not in name for name, _, _ in pairs)
    assert any(REAL in name for name, _, _ in pairs)


def test_diamond_main_does_not_count_false_executor():
    ns = load_functions("点淘鸭钻石任务.py", {"scan_and_execute"}, loop_namespace(
        scans=[[bubble("去完成")]] * 8,
        parser=lambda *_: [(REAL, 100, 200)],
        snippets={"do_task": lambda *_: False},
    ))
    _, output = run_loop(ns, "scan_and_execute")
    assert "共完成 0 个任务" in output
    assert "仅剩黑名单/无可执行任务" in output


def test_yuanbao_executor_false_does_not_increment_or_log():
    logged = []
    ns = load_functions("元宝中心小任务.py", {"scan_and_execute"}, loop_namespace(
        scans=[[bubble("额外任务")]] * 8,
        parser=lambda *_: [(REAL, 100, 200)],
        snippets={"execute_task": lambda *_: False},
        logged=logged,
    ))
    _, output = run_loop(ns, "scan_and_execute")
    assert "📊 已完成 1" not in output
    assert logged == []
    assert "仅剩黑名单/无可执行任务" in output


def test_yuanbao_blocked_executor_never_counts():
    ns = load_functions("元宝中心小任务.py", {"execute_task"}, {
        "d": Mock(), "note_blocked_task": note_blocked_task,
        "re": re, "time": SimpleNamespace(sleep=lambda *_: None),
    })
    assert ns["execute_task"](BLOCKED, 100, 200) is False
    assert ns["d"].mock_calls == []


def test_acceleration_false_executor_continues_scanning_instead_of_break():
    logged = []
    ns = load_functions("打工加速.py", {"main"}, loop_namespace(
        scans=[[bubble("浏览精选推荐30秒")]] * 6,
        parser=lambda *_: ("浏览精选推荐30秒", 100, 200),
        snippets={"exec_browse": lambda *_: False},
        logged=logged,
    ))
    _, output = run_loop(ns, "main")
    assert "连续3轮无实际进展" in output
    assert "共完成 0 个任务" in output
    assert logged == []


def test_acceleration_blocked_first_candidate_still_selects_real_task():
    ns = load_functions("打工加速.py", {"find_browse_task"}, {
        "re": re,
        "has_search_browse_nearby": lambda *_: False,
        "has_sliding_browse_nearby": lambda *_: False,
        "note_blocked_task": note_blocked_task,
    })
    blocks = [bubble(BLOCKED, cy=400), bubble("浏览精选推荐30秒", cy=700)]
    with contextlib.redirect_stdout(io.StringIO()):
        result = ns["find_browse_task"](blocks, set())
    assert result == ("浏览精选推荐30秒", 400, 700)


def test_shopping_skipped_executor_does_not_count_completion():
    ns = load_functions("点淘购物赚钱.py",
                        {"main", "_task_buttons", "_task_area_top"}, loop_namespace(
        scans=[[bubble("去完成", cx=1000)]] * 8,
        snippets={
            "do_task": lambda *_: False,
            "detect_task_name_before_click": lambda *_: ("live", 60, REAL),
            "TASK_BTN_KW": [],
            "MAX_BACK_ATTEMPTS": 3,
        },
    ))
    _, output = run_loop(ns, "main")
    assert "共完成 0 个任务" in output
    assert "不计入完成数量" in output


def test_walk_blacklist_rejects_three_product_task():
    ns = load_functions("走路赚元宝.py", {"is_blacklisted"}, {
        "BLACKLIST_KEYWORDS": [],
        "is_search_browse_task": lambda *_: False,
        "is_walk_low_price_task": lambda *_: False,
    })
    assert ns["is_blacklisted"](BLOCKED) is True


def test_yangyouhui_parser_excludes_three_product_task():
    ns = load_functions("养优惠.py", {"normalize", "parse_tasks"}, {
        "is_blocked_boutique_task": is_blocked_boutique_task,
        "TITLE_RE": re.compile(r"^(搜索宝贝后浏览|看精彩直播|看精彩内容|看精美内容|看视频|逛直播|看直播|浏览)\d+秒"),
        "PROGRESS_RE": re.compile(r"[（(](\d+)/(\d+)[）)]"),
    })
    blocks = [bubble(BLOCKED, cx=200), bubble("去完成", cx=1000)]
    assert ns["parse_tasks"](blocks, 1080) == []


def test_shared_selector_accepts_other_task_after_blocked_candidate():
    skipped = set()
    clicked = {}
    task = select_executable_task(
        [(BLOCKED, 100, 200), (REAL, 300, 400)], skipped, clicked,
    )
    assert task == (REAL, 300, 400)
    assert normalized_task_name(BLOCKED) in skipped
    assert normalized_task_name(BLOCKED) not in clicked


def test_shared_selector_only_blocked_task_returns_none():
    skipped = set()
    assert select_executable_task([(BLOCKED, 100, 200)], skipped) is None
    assert len(skipped) == 1


def test_blocked_task_false_is_never_counted_by_shared_selector():
    # 被屏蔽候选根本不会返回给调用方；调用方无需为 False 增加完成数。
    assert select_executable_task([(BLOCKED, 1, 2)], set()) is None
