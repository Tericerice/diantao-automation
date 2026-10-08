import task_recheck
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


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
