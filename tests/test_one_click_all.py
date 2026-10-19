import importlib.util
from collections import Counter
from pathlib import Path
from threading import Event

import pytest

from task_recheck import RECHECK_ENV, TASK_FOUND, ROUND_FINISHED


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("one_click_all", ROOT / "一键全部执行.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_all_tasks_cover_sequence_remaining_and_energy():
    assert [step.filename for step in module.ALL_TASKS] == [
        "连通性脚本.py", "一键下滑.py",
        "主播打卡粉丝礼.py", "签到赢元宝.py", "睡觉赚元宝.py",
        "点淘鸭钻石任务.py", "点淘鸭摇一摇.py", "点淘购物赚钱.py",
        "打工得体力.py", "走路赚元宝.py", "元宝中心小任务.py", "养优惠.py",
        "tools/taobao_energy.py",
    ]
    assert module.ALL_TASKS[-1].uv
    assert module.ALL_TASKS[-1].args == ("run", "--repeat", "30")
    assert [step.rechecks for step in module.SEQUENCE_TASKS] == [0, 0]
    assert all(step.rechecks == 5 for step in module.REMAINING_TASKS)


def test_all_tasks_exist_on_disk():
    for step in module.ALL_TASKS:
        assert (module.SCRIPT_DIR / step.filename).is_file(), step.filename


def test_uv_command_matches_registered_entry(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: "C:/tools/uv.exe")
    command = module.build_command(module.ENERGY_TASK)
    assert command[:3] == ["C:/tools/uv.exe", "--quiet", "run"]
    assert command[3:9] == ["--with", "uiautomator2", "--with", "requests",
                            "--with", "python-dotenv"]
    assert command[9:12] == ["python", "-u",
                             str(module.SCRIPT_DIR / "tools" / "taobao_energy.py")]
    assert command[12:] == ["run", "--repeat", "30"]


def test_plain_command_uses_current_interpreter():
    command = module.build_command(module.SEQUENCE_TASKS[0])
    assert command[0] == module.sys.executable
    assert command[1:3] == ["-u", str(module.SCRIPT_DIR / "连通性脚本.py")]


def test_uv_missing_reports_startup_error(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        return True, 0, "成功"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(tasks=(module.ENERGY_TASK,)) == 1
    assert calls == []


def test_sequence_continues_after_failure(monkeypatch):
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        return len(calls) != 2, 0, "成功" if len(calls) != 2 else "超时"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(tasks=module.SEQUENCE_TASKS) == 1
    assert calls == ["连通性脚本.py", "一键下滑.py"]


def test_remaining_sequence_continues_after_failure(monkeypatch):
    calls = []
    tasks = tuple(module.Step(step.filename, step.timeout) for step in module.REMAINING_TASKS)

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        return len(calls) != 2, 0, "成功" if len(calls) != 2 else "超时"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(tasks=tasks) == 1
    assert calls == [step.filename for step in module.REMAINING_TASKS]


def test_stop_prevents_next_script(monkeypatch):
    stop = Event()
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        stop.set()
        return False, 0, "用户停止"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(stop) == 130
    assert calls == ["连通性脚本.py"]


def test_missing_script_prevents_partial_run(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "SCRIPT_DIR", tmp_path)
    monkeypatch.setattr(module, "run_script", lambda *a, **k: pytest.fail("不应启动脚本"))
    assert module.execute() == 1


@pytest.mark.parametrize("found_rounds, expected_runs", [(0, 2), (2, 3), (6, 6)])
def test_each_task_rechecks_until_empty_or_limit(monkeypatch, found_rounds, expected_runs):
    calls = Counter()

    def fake_run(filepath, **kwargs):
        calls[filepath.name] += 1
        assert kwargs["env_overrides"] == {RECHECK_ENV: "1"}
        if calls[filepath.name] <= found_rounds:
            kwargs["on_line"](TASK_FOUND)
        kwargs["on_line"](ROUND_FINISHED)
        return True, 0, "成功"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(tasks=module.REMAINING_TASKS) == 0
    assert calls == Counter({step.filename: expected_runs for step in module.REMAINING_TASKS})


def test_no_recheck_step_runs_once_without_markers(monkeypatch):
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append((filepath.name, kwargs.get("env_overrides")))
        return True, 0, "成功"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(tasks=module.SEQUENCE_TASKS) == 0
    assert calls == [("连通性脚本.py", None), ("一键下滑.py", None)]


def test_energy_step_receives_explicit_command(monkeypatch):
    captured = {}

    def fake_run(filepath, **kwargs):
        captured["name"] = filepath.name
        captured["command"] = kwargs["command"]
        captured["env"] = kwargs.get("env_overrides")
        return True, 0, "成功"

    monkeypatch.setattr(module, "run_script", fake_run)
    monkeypatch.setattr(module.shutil, "which", lambda name: "C:/tools/uv.exe")
    assert module.execute(tasks=(module.ENERGY_TASK,)) == 0
    assert captured["name"] == "taobao_energy.py"
    assert captured["command"][0] == "C:/tools/uv.exe"
    assert captured["env"] is None
