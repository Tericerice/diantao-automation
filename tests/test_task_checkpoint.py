"""大任务边界重放；复核反馈也必须保存，避免恢复时改变原来的执行分支。"""
import importlib
import itertools
import os
from pathlib import Path
import subprocess
import sys

import pytest

import task_checkpoint as checkpoint
from task_runner import run_script
from task_recheck import TASK_FOUND, ROUND_FINISHED


@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setenv(checkpoint.SESSION_ENV, str(tmp_path / "checkpoints"))
    monkeypatch.setenv(checkpoint.SCOPE_ENV, "root")
    monkeypatch.setattr(checkpoint, "_calls", itertools.count())
    return tmp_path


def test_completed_step_skips_but_active_step_restarts(session):
    events = []
    checkpoint.run_step("1", "签到", lambda: events.append("签到"))
    interrupted = checkpoint.Checkpoint("2", "睡觉")
    interrupted.begin()
    checkpoint.run_step("1", "签到", lambda: events.append("不应再次签到"))
    checkpoint.run_step("2", "睡觉", lambda: events.append("睡觉"))
    checkpoint.run_step("3", "赚钱", lambda: events.append("赚钱"))
    assert events == ["签到", "睡觉", "赚钱"]


def test_nested_active_round_is_reported_instead_of_outer_script(session, monkeypatch):
    outer = checkpoint.Checkpoint("script-1", "一键下滑.py")
    outer.begin()
    monkeypatch.setenv(checkpoint.SCOPE_ENV, outer.scope)
    checkpoint.run_step("swipe-1", "打工", lambda: None)
    checkpoint.Checkpoint("swipe-2", "睡觉").begin()
    assert checkpoint.current_task(outer.directory, "default") == "睡觉"
    outer.finish([True, 1, "成功"])
    assert checkpoint.current_task(outer.directory, "default") == "default"


def test_run_step_forwards_label_keyword_to_original_round(session):
    assert checkpoint.run_step("1", "睡觉", lambda **kw: kw,
                               label="2", name="睡觉") == {"label": "2", "name": "睡觉"}


def test_replay_preserves_child_result_and_recheck_markers(session, monkeypatch):
    script = session / "child.py"
    script.write_text(f"print({TASK_FOUND!r}); print({ROUND_FINISHED!r})\n", encoding="utf-8")
    original = []
    result = run_script(script, cwd=session, timeout=5, should_stop=lambda: False,
                        on_line=original.append)
    monkeypatch.setattr(checkpoint, "_calls", itertools.count())
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: pytest.fail("已完成的子任务不应再启动"))
    restored = []
    assert run_script(script, cwd=session, timeout=5, should_stop=lambda: False,
                      on_line=restored.append) == result
    assert restored[1:] == original == [TASK_FOUND, ROUND_FINISHED]


def test_failed_task_already_passed_by_sequence_is_not_repeated(session, monkeypatch):
    script = session / "failed.py"
    script.write_text("raise SystemExit(7)\n", encoding="utf-8")
    options = dict(cwd=session, timeout=5, should_stop=lambda: False, on_line=lambda _: None)
    result = run_script(script, **options)
    assert result[0] is False
    monkeypatch.setattr(checkpoint, "_calls", itertools.count())
    assert run_script(script, **options) == result


def test_changed_command_is_not_replayed_with_old_result(session):
    first = checkpoint.Checkpoint("1", "脚本", ["python", "old.py"])
    first.finish(True)
    with pytest.raises(RuntimeError, match="定义已经变化"):
        checkpoint.Checkpoint("1", "脚本", ["python", "new.py"])


def test_kill_race_cannot_mark_interrupted_step_done_or_advance_following_step(session):
    sign = checkpoint.Checkpoint("1", "签到")
    sign.finish(True)
    sleep = checkpoint.Checkpoint("2", "睡觉")
    sleep.begin()
    saved = checkpoint.snapshot(sign.directory)
    # 模拟被终止的子进程先退出，父调度器来得及写入失败/推进，随后也被终止。
    sleep.finish([False, 0, "错误码 1"])
    checkpoint.Checkpoint("3", "赚钱").begin()
    checkpoint.restore_snapshot(sign.directory, saved)
    assert checkpoint.Checkpoint("1", "签到").done
    assert not checkpoint.Checkpoint("2", "睡觉").done
    assert checkpoint.Checkpoint("3", "赚钱").cached is None
    assert checkpoint.current_task(sign.directory, "default") == "睡觉"


def test_without_host_checkpoint_does_not_write_or_skip(monkeypatch):
    monkeypatch.delenv(checkpoint.SESSION_ENV, raising=False)
    calls = []
    for _ in range(2):
        checkpoint.run_step("sleep", "睡觉", lambda: calls.append(1))
    assert calls == [1, 1]
