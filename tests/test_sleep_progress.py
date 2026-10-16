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
        "STALE_LIMIT": 3, "screen_height": 2780, "check_center_btn": lambda: "waiting",
        "get_ocr_text_blocks": Mock(return_value=[bubble("睡觉赚元宝", y=220)]),
        "navigate_to_sleep_page": Mock(return_value=True),
        "return_to_sleep_page": Mock(return_value=True),
        "find_bubble": Mock(return_value=None), "do_bubble_task": Mock(),
        "click_float_bubbles": Mock(return_value=0),
        "report_task_found": Mock(), "report_round_finished": Mock(),
    }
    ns.update(overrides)
    return load_functions("睡觉赚元宝.py", {"scan_and_collect", "is_sleep_page"}, ns)


def test_sleep_does_not_collect_live_room_numbers_and_bounds_failed_return():
    ns = sleep_loop(get_ocr_text_blocks=Mock(return_value=[bubble("家具灯饰榜第100+名")]),
                    return_to_sleep_page=Mock(return_value=False))
    assert ns["scan_and_collect"]() == 0
    ns["return_to_sleep_page"].assert_called_once()
    ns["find_bubble"].assert_not_called()
    ns["click_float_bubbles"].assert_not_called()
    ns["report_round_finished"].assert_not_called()


def test_repeatable_live_task_is_not_limited_by_its_name():
    target = {"name": "看福利直播30秒", "cx": 160, "cy": 860}
    ns = sleep_loop(find_bubble=Mock(side_effect=[target] * 5 + [None]))
    assert ns["scan_and_collect"]() == 5
    assert ns["do_bubble_task"].call_count == 5
    ns["report_round_finished"].assert_called_once()


def test_changed_progress_is_allowed_and_empty_round_finishes():
    targets = [{"name": f"看福利直播30秒({i}/5)", "cx": 160, "cy": 860} for i in range(5)]
    ns = sleep_loop(find_bubble=Mock(side_effect=targets + [None]))
    assert ns["scan_and_collect"]() == 5
    ns["report_round_finished"].assert_called_once()


def test_sleep_recovers_page_then_resumes_scanning():
    ns = sleep_loop(get_ocr_text_blocks=Mock(side_effect=[
        [bubble("直播间")], [bubble("睡觉赚元宝", y=220)],
    ]))
    assert ns["scan_and_collect"]() == 0
    ns["return_to_sleep_page"].assert_called_once()
    ns["click_float_bubbles"].assert_called_once()
    ns["report_round_finished"].assert_called_once()


def test_center_entry_is_not_sleep_page_title():
    ns = sleep_loop()
    assert not ns["is_sleep_page"]([bubble("睡觉赚元宝", y=2240)])


@pytest.mark.parametrize("pages, navigated, expected, backs", [
    ([[bubble("直播间")], [bubble("睡觉赚元宝", y=220)]], False, True, 1),
    ([[bubble("睡觉赚元宝", y=220)]], False, True, 0),
    ([[bubble("直播间")]] * 4, False, False, 3),
    ([[bubble("直播间")]] * 4 + [[bubble("睡觉赚元宝", y=220)]], True, True, 3),
    ([[bubble("直播间")]] * 5, True, False, 3),
])
def test_return_checks_actual_page_and_bounds_recovery(pages, navigated, expected, backs):
    ns = sleep_loop(get_ocr_text_blocks=Mock(side_effect=pages),
                    navigate_to_sleep_page=Mock(return_value=navigated))
    load_functions("睡觉赚元宝.py", {"return_to_sleep_page"}, ns)
    assert ns["return_to_sleep_page"]() is expected
    assert ns["d"].press.call_count == backs


def test_live_return_failure_is_not_logged_as_success():
    ns = sleep_loop(return_to_sleep_page=Mock(return_value=False))
    ns.update(execute_live_task=Mock(), click_device_point=Mock(), log_task_completed=Mock())
    load_functions("睡觉赚元宝.py", {"do_bubble_task"}, ns)
    assert ns["do_bubble_task"]("看福利直播30秒", 160, 860) is False
    ns["execute_live_task"].assert_called_once()
    ns["log_task_completed"].assert_not_called()


def test_failed_live_return_stops_before_rewards_or_completion():
    target = {"name": "看福利直播30秒", "cx": 160, "cy": 860}
    ns = sleep_loop(find_bubble=Mock(return_value=target), do_bubble_task=Mock(return_value=False))
    assert ns["scan_and_collect"]() == 0
    ns["click_float_bubbles"].assert_not_called()
    ns["report_task_found"].assert_not_called()
    ns["report_round_finished"].assert_not_called()


def test_reward_click_opening_live_room_cannot_trigger_live_reward_scan():
    ns = sleep_loop(
        get_ocr_text_blocks=Mock(side_effect=[
            [bubble("睡觉赚元宝", y=220)],
            [bubble("家具灯饰榜第100+名"), bubble("58")],
            [bubble("睡觉赚元宝", y=220)],
        ]),
        click_float_bubbles=Mock(side_effect=[1, 0]),
    )
    assert ns["scan_and_collect"]() == 1
    ns["return_to_sleep_page"].assert_called_once()
    assert ns["find_bubble"].call_count == 2
    assert ns["click_float_bubbles"].call_count == 2
