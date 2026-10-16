"""Regression checks for false rewards and sleep task loops, without a device."""
import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_functions(filename, names, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8-sig"))
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(tree, filename, "exec"), namespace)
    return namespace


def bubble(text, x=470, y=626):
    return {"text": text, "cx": x, "cy": y}


def test_rankings_are_not_float_rewards():
    ns = load_functions("u2_scanner.py", {"scan_float_bubbles"}, {
        "re": re,
        "scan_page": lambda _: [bubble("家具灯饰榜第100+名"), bubble("100+"),
                                bubble("+58", x=600), bubble("10", x=750)],
    })
    device = SimpleNamespace(window_size=lambda: (1264, 2780))
    assert [b["text"] for b in ns["scan_float_bubbles"](device)] == ["+58", "10"]


@pytest.mark.parametrize("after, expected", [
    ([bubble("10", x=472, y=628)], 0),
    ([], 1),
    ([bubble("20")], 1),
    ([bubble("10", x=800)], 1),
])
def test_reward_is_counted_only_when_clicked_bubble_changes(after, expected):
    scan = Mock(side_effect=[[bubble("10")], after])
    device = Mock()
    ns = load_functions("u2_scanner.py", {"click_float_bubbles"}, {
        "scan_float_bubbles": scan, "time": SimpleNamespace(sleep=lambda _: None),
    })
    assert ns["click_float_bubbles"](device) == expected
    device.click.assert_called_once_with(470, 626)


def sleep_loop(**overrides):
    ns = {
        "d": Mock(), "time": SimpleNamespace(sleep=lambda _: None), "re": re,
        "STALE_LIMIT": 3, "check_center_btn": lambda: "waiting",
        "get_ocr_text_blocks": Mock(return_value=[bubble("睡觉赚元宝")]),
        "navigate_to_sleep_page": Mock(return_value=True),
        "find_bubble": Mock(return_value=None), "do_bubble_task": Mock(),
        "click_float_bubbles": Mock(return_value=0),
        "report_task_found": Mock(), "report_round_finished": Mock(),
    }
    ns.update(overrides)
    return load_functions("睡觉赚元宝.py", {"scan_and_collect"}, ns)


def test_sleep_does_not_collect_live_room_numbers_and_bounds_failed_return():
    ns = sleep_loop(get_ocr_text_blocks=Mock(return_value=[bubble("家具灯饰榜第100+名")]))
    assert ns["scan_and_collect"]() == 0
    assert ns["navigate_to_sleep_page"].call_count == 3
    ns["click_float_bubbles"].assert_not_called()
    ns["report_round_finished"].assert_not_called()


def test_same_task_without_progress_stops_after_three_attempts():
    target = {"name": "看福利直播30秒", "cx": 160, "cy": 860}
    ns = sleep_loop(find_bubble=Mock(return_value=target))
    # A finite mock sequence also makes the regression fail fast before the fix.
    ns["do_bubble_task"].side_effect = [None] * 3 + [AssertionError("repeated task did not stop")]
    assert ns["scan_and_collect"]() == 3
    assert ns["do_bubble_task"].call_count == 3
    ns["report_round_finished"].assert_not_called()


def test_changed_progress_is_allowed_and_empty_round_finishes():
    targets = [{"name": f"看福利直播30秒({i}/5)", "cx": 160, "cy": 860} for i in range(5)]
    ns = sleep_loop(find_bubble=Mock(side_effect=targets + [None]))
    assert ns["scan_and_collect"]() == 5
    ns["report_round_finished"].assert_called_once()


def test_sleep_recovers_page_then_resumes_scanning():
    ns = sleep_loop(get_ocr_text_blocks=Mock(side_effect=[
        [bubble("直播间")], [bubble("睡觉赚元宝")],
    ]))
    assert ns["scan_and_collect"]() == 0
    ns["navigate_to_sleep_page"].assert_called_once()
    ns["click_float_bubbles"].assert_called_once()
    ns["report_round_finished"].assert_called_once()
