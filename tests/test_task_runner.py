import threading
from pathlib import Path

import pytest

from task_runner import run_script


@pytest.mark.parametrize("source", ["import time; time.sleep(10)", "import time; print('partial', end='', flush=True); time.sleep(10)"])
def test_silent_or_partial_output_still_times_out(tmp_path: Path, source: str) -> None:
    script = tmp_path / "silent.py"
    script.write_text(source, encoding="utf-8")
    success, elapsed, reason = run_script(
        script, cwd=tmp_path, timeout=0.5,
        should_stop=lambda: False, on_line=lambda line: None,
    )
    assert not success
    assert "超时" in reason
    assert elapsed < 3


def test_cancel_silent_process(tmp_path: Path) -> None:
    script = tmp_path / "silent.py"
    script.write_text("import time; time.sleep(10)", encoding="utf-8")
    stop = threading.Event()
    timer = threading.Timer(0.5, stop.set)
    timer.start()
    try:
        success, elapsed, reason = run_script(
            script, cwd=tmp_path, timeout=10,
            should_stop=stop.is_set, on_line=lambda line: None,
        )
    finally:
        timer.cancel()
    assert (success, reason) == (False, "用户停止")
    assert elapsed < 3


@pytest.mark.parametrize("code", [0, 7])
def test_output_and_exit_code(tmp_path: Path, code: int) -> None:
    script = tmp_path / "output.py"
    script.write_text(f"print('中文日志'); raise SystemExit({code})", encoding="utf-8")
    lines: list[str] = []
    success, _, reason = run_script(
        script, cwd=tmp_path, timeout=5,
        should_stop=lambda: False, on_line=lines.append,
    )
    assert success == (code == 0)
    assert lines == ["中文日志"]
    assert reason == ("成功" if code == 0 else "错误码 7")


def test_no_timeout_waits_for_script_to_finish(tmp_path: Path) -> None:
    script = tmp_path / "quick.py"
    script.write_text("print('done')", encoding="utf-8")
    lines: list[str] = []
    success, _, reason = run_script(
        script, cwd=tmp_path, timeout=None,
        should_stop=lambda: False, on_line=lines.append,
    )
    assert (success, reason) == (True, "成功")
    assert lines == ["done"]


def test_no_timeout_still_responds_to_stop(tmp_path: Path) -> None:
    script = tmp_path / "silent.py"
    script.write_text("import time; time.sleep(10)", encoding="utf-8")
    stop = threading.Event()
    timer = threading.Timer(0.5, stop.set)
    timer.start()
    try:
        success, elapsed, reason = run_script(
            script, cwd=tmp_path, timeout=None,
            should_stop=stop.is_set, on_line=lambda line: None,
        )
    finally:
        timer.cancel()
    assert (success, reason) == (False, "用户停止")
    assert elapsed < 3


def test_recheck_environment_is_only_set_for_requested_child(tmp_path: Path, monkeypatch):
    from task_recheck import RECHECK_ENV

    monkeypatch.delenv(RECHECK_ENV, raising=False)
    script = tmp_path / "environment.py"
    script.write_text(f"import os; print(os.environ.get('{RECHECK_ENV}', 'off'))", encoding="utf-8")
    lines = []
    for overrides in ({RECHECK_ENV: "1"}, None):
        success, _, _ = run_script(
            script, cwd=tmp_path, timeout=5, should_stop=lambda: False,
            on_line=lines.append, env_overrides=overrides,
        )
        assert success
    assert lines == ["1", "off"]
