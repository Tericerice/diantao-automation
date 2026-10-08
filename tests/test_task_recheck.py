import task_recheck
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import itertools

import pytest


def test_standalone_scripts_do_not_emit_recheck_feedback(monkeypatch, capsys):
    monkeypatch.delenv(task_recheck.RECHECK_ENV, raising=False)
    task_recheck.report_task_found()
    task_recheck.report_round_finished()
    assert capsys.readouterr().out == ""


def test_one_click_scripts_emit_recheck_feedback(monkeypatch, capsys):
    monkeypatch.setenv(task_recheck.RECHECK_ENV, "1")
    task_recheck.report_task_found()
    task_recheck.report_round_finished()
    assert capsys.readouterr().out.splitlines() == [task_recheck.TASK_FOUND, task_recheck.ROUND_FINISHED]


def test_empty_anchor_round_finishes_in_one_click_instead_of_scrolling_forever(monkeypatch):
    monkeypatch.setenv(task_recheck.RECHECK_ENV, "1")
    source = (Path(__file__).resolve().parents[1] / "主播打卡粉丝礼.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "scan_and_clock")
    class Device:
        swipe = Mock()

        def __call__(self, **kwargs):
            return SimpleNamespace(exists=lambda **kwargs: False)

    device = Device()
    finished = Mock()
    namespace = {
        "time": SimpleNamespace(sleep=lambda _: None), "d": device,
        "get_ocr_text_blocks": lambda *args, **kwargs: [], "scan_page": lambda _: [],
        "screen_width": 1264, "screen_height": 2780,
        "recheck_enabled": task_recheck.recheck_enabled,
        "report_task_found": Mock(), "report_round_finished": finished,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "主播打卡粉丝礼.py", "exec"), namespace)
    assert namespace["scan_and_clock"]() == 0
    device.swipe.assert_called_once()
    finished.assert_called_once()
    namespace["report_task_found"].assert_not_called()


@pytest.mark.parametrize("tasks", [[], [("下单", 900, 500)], [("浏览精选推荐", 900, 500)]])
def test_center_round_reports_only_executable_tasks_and_finishes(monkeypatch, tasks):
    monkeypatch.setenv(task_recheck.RECHECK_ENV, "1")
    source = (Path(__file__).resolve().parents[1] / "元宝中心小任务.py").read_text(encoding="utf-8")
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
             and n.name in {"scan_and_execute", "is_stale_no_buttons"}]
    scans = itertools.chain([tasks], itertools.repeat([]))
    events = []
    namespace = {
        "time": SimpleNamespace(sleep=lambda _: None), "d": object(),
        "MAX_TASKS": 30, "STALE_LIMIT": 3,
        "get_ocr_text_blocks": lambda _: [{"text": "额外任务"}],
        "scan_extra_area_tasks": lambda _: next(scans),
        "is_blacklisted": lambda name: name == "下单",
        "execute_task": lambda *args: events.append("executed"),
        "recheck_enabled": task_recheck.recheck_enabled,
        "report_task_found": lambda: events.append("found"),
        "report_round_finished": lambda: events.append("finished"),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "元宝中心小任务.py", "exec"), namespace)
    namespace["scan_and_execute"]()
    assert events == (["found", "executed", "finished"] if tasks and tasks[0][0] != "下单" else ["finished"])
