"""隔离加载业务函数，避免导入脚本时连接真机。"""

import ast
import os
import random
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

import u2_scanner
import utils
from task_catalog import is_task_file
from task_runner import run_script


ROOT = Path(__file__).resolve().parents[1]


def load_definitions(filename, names, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8-sig"))
    tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    exec(compile(tree, filename, "exec"), namespace)
    return namespace


def test_nested_video_pause_does_not_resume_callers_watcher():
    ctx = Mock()
    device = SimpleNamespace(_global_watcher_ctx=ctx)
    utils.pause_global_watcher(device)
    with patch.object(u2_scanner, "_execute_video_task", return_value=True):
        assert u2_scanner.execute_video_task(device, "看视频", 0, 0)
    ctx.stop.assert_called_once()
    ctx.start.assert_not_called()
    utils.resume_global_watcher(device)
    ctx.start.assert_called_once()


def test_watcher_restored_if_video_raises():
    ctx = Mock()
    device = SimpleNamespace(_global_watcher_ctx=ctx)
    with patch.object(u2_scanner, "_execute_video_task", side_effect=RuntimeError("offline")):
        with pytest.raises(RuntimeError, match="offline"):
            u2_scanner.execute_video_task(device, "看视频", 0, 0)
    ctx.stop.assert_called_once()
    ctx.start.assert_called_once()


@pytest.mark.parametrize("blocks", [[], [{"text": "页面标题"}]])
def test_yuanbao_exits_after_exactly_three_empty_scans(blocks):
    scan = Mock(side_effect=[blocks] * 3 + [AssertionError("没有按三轮退出")])
    ns = load_definitions("元宝中心小任务.py", {"scan_and_execute", "is_stale_no_buttons"}, {
        "d": object(), "MAX_TASKS": 20, "STALE_LIMIT": 3,
        "time": SimpleNamespace(sleep=lambda seconds: None),
        "get_ocr_text_blocks": scan, "scan_extra_area_tasks": lambda blocks: [],
    })
    ns["scan_and_execute"]()
    assert scan.call_count == 3


def test_coin_exits_when_page_has_text_but_no_tasks():
    scan = Mock(side_effect=[[{"text": "标题"}]] * 3 + [AssertionError("没有退出")])
    ns = load_definitions("淘金币任务.py", {"run_tasks"}, {
        "d": Mock(), "screen_width": 1080, "screen_height": 2400,
        "read_page": scan, "is_task_page": lambda nodes: True,
        "parse_task_list": lambda nodes: [], "normalize": str,
        "EMPTY_LIMIT": 3, "MAX_ATTEMPTS": 2, "scroll_list": Mock(),
        "time": SimpleNamespace(sleep=lambda seconds: None),
    })
    ns["run_tasks"]()
    assert scan.call_count == 3


def test_down_moves_and_merges_toward_bottom_without_changing_board():
    ns = load_definitions("diantao_1024_auto.py", {"GameEngine"}, {"np": np})
    board = np.array([[1, 0], [1, 3]])
    original = board.copy()
    moved, score, changed = ns["GameEngine"].move_down(board)
    np.testing.assert_array_equal(moved, [[0, 0], [2, 3]])
    np.testing.assert_array_equal(board, original)
    assert score == 2
    assert changed


@pytest.mark.parametrize("hint", ["即将完成", "已完成", "恭喜"])
def test_shopping_live_hint_cannot_bypass_requested_duration(hint):
    clock = SimpleNamespace(now=0.0)

    def sleep(seconds):
        clock.now += seconds

    ns = load_definitions("点淘购物赚钱.py", {"do_task"}, {
        "d": Mock(), "time": SimpleNamespace(time=lambda: clock.now, sleep=sleep),
        "check_can_open": lambda device: None, "detect_entered_media_type": lambda *args: "live",
        "get_ocr_text_blocks": lambda device: [{"text": hint}],
        "screen_width": 1080, "screen_height": 2400, "random": random, "re": re,
        "TASK_BTN_KW": [], "back_to_task": lambda *args, **kwargs: None,
    })
    started_at = ns["do_task"]("live", 60, "看直播60秒")
    assert clock.now - started_at >= 63


@pytest.mark.parametrize("filename", ["calibrate.py", "debug_find_board.py", "u2_scanner.py", "rag_client.py", "task_runner.py"])
def test_utilities_are_not_batch_tasks(filename):
    assert not is_task_file(filename)


def test_explicit_business_and_external_tasks_remain_available():
    assert is_task_file("一键下滑.py")
    assert is_task_file("点淘鸭摇一摇额外元宝.py")
    assert is_task_file("..\\coin11-tb-main\\2026淘宝618活动.py")


@pytest.mark.parametrize("executor", [utils.browse_task, u2_scanner.execute_browse_task])
def test_browse_timeout_is_not_success(executor):
    clock = SimpleNamespace(now=0.0)

    def sleep(seconds):
        clock.now += seconds

    device = Mock()
    device.window_size.return_value = (1080, 2400)
    with patch.object(u2_scanner.time, "time", side_effect=lambda: clock.now), \
         patch.object(u2_scanner.time, "sleep", side_effect=sleep), \
         patch.object(u2_scanner, "scan_page", return_value=[]), \
         patch.object(utils, "get_ocr_text_blocks", return_value=[]):
        assert executor(device, min_duration=60, max_wait=5) is False


def test_diamond_fullwidth_progress_and_rows_do_not_chain():
    ns = load_definitions("点淘鸭钻石任务.py", {"parse_progress", "_cluster_rows"}, {
        "re": re, "ROW_CLUSTER_TOLERANCE": 80,
    })
    assert ns["parse_progress"]("看直播（ 2 / 5 ）") == (2, 5)
    rows = ns["_cluster_rows"]([{"cy": 100}, {"cy": 170}, {"cy": 240}])
    assert len(rows) == 2


def test_diamond_missing_button_is_skipped_without_click():
    device = Mock()
    ns = load_definitions("点淘鸭钻石任务.py", {"do_task"}, {
        "d": device, "get_ocr_text_blocks": lambda device: [],
    })
    assert ns["do_task"]("看直播60秒", 900, 1200) is False
    device.click.assert_not_called()


def test_diamond_completed_live_progress_is_not_restarted():
    device = Mock()
    ns = load_definitions("点淘鸭钻石任务.py", {"do_task", "parse_progress"}, {
        "d": device, "get_ocr_text_blocks": lambda device: [{"text": "去完成", "cx": 900, "cy": 1200}],
        "is_live": lambda name: True, "re": re,
    })
    assert ns["do_task"]("看直播（5/5）", 900, 1200) is False
    device.click.assert_not_called()


def test_gui_stop_keeps_run_disabled_until_worker_finishes():
    ns = load_definitions("任务选择器.py", {"App"}, {
        "tk": SimpleNamespace(DISABLED="disabled", NORMAL="normal"),
    })
    app = ns["App"].__new__(ns["App"])
    app.btn_run, app.btn_stop, app.progress_label = Mock(), Mock(), Mock()
    app.running, app.closing = True, False
    app._stop()
    app.btn_run.config.assert_not_called()
    assert app.running
    app._on_finish()
    assert not app.running
    app.btn_run.config.assert_called_once_with(state="normal", text="▶ 运行选中")


def test_gui_discovery_excludes_tools_even_when_they_exist(tmp_path):
    for name in ["签到赢元宝.py", "debug_find_board.py", "calibrate.py", "task_runner.py"]:
        (tmp_path / name).touch()
    ns = load_definitions("任务选择器.py", {"scan_tasks"}, {
        "SCRIPT_DIR": str(tmp_path), "os": os, "is_task_file": is_task_file,
        "DEFAULT_TIMEOUTS": {}, "EXTRA_TASKS": [],
    })
    assert [task["file"] for task in ns["scan_tasks"]()] == ["签到赢元宝.py"]


def test_cli_reports_silent_child_timeout(tmp_path):
    (tmp_path / "silent.py").write_text("import time; time.sleep(10)", encoding="utf-8")
    log = Mock()
    ns = load_definitions("全部执行.py", {"run_task"}, {
        "SCRIPT_DIR": str(tmp_path), "os": os, "time": time,
        "stop_flag": False, "run_script": run_script, "log": log,
        "now": lambda: "00:00:00",
    })
    name, success, elapsed = ns["run_task"]({"name": "测试静默脚本", "file": "silent.py", "timeout": 0.5})
    assert name == "测试静默脚本"
    assert not success
    assert elapsed < 3
    assert "超时" in log.call_args.args[0]


@pytest.mark.parametrize("failure", [False, True])
def test_flower_live_enters_and_returns_even_on_error(failure):
    events = []
    device = Mock()
    device.click.side_effect = lambda *args: events.append(("click", args))
    device.press.side_effect = lambda key: events.append(("press", key))

    def watch(*args, **kwargs):
        events.append(("live", kwargs))
        if failure:
            raise RuntimeError("设备响应异常")

    ns = load_definitions("618花花乐.py", {"do_task"}, {
        "d": device, "any_match": lambda name, words: True, "LIVE_KW": ["直播"],
        "check_can_open": lambda device: None, "execute_live_task": watch,
        "time": SimpleNamespace(sleep=lambda seconds: None),
    })
    if failure:
        with pytest.raises(RuntimeError, match="设备响应异常"):
            ns["do_task"](900, 600, "看直播")
    else:
        ns["do_task"](900, 600, "看直播")
    assert events == [("click", (900, 600)), ("live", {"duration": 10}), ("press", "back")]
