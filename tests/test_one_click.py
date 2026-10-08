import importlib.util
from pathlib import Path
from threading import Event
from collections import Counter

import pytest

from task_recheck import RECHECK_ENV, TASK_FOUND, ROUND_FINISHED


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("one_click", ROOT / "一键顺序执行.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_sequence_continues_after_failure(monkeypatch):
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        return len(calls) != 2, 0, "成功" if len(calls) != 2 else "超时"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute() == 1
    assert calls == ["连通性脚本.py", "一键下滑.py"]


def test_remaining_sequence_continues_after_failure(monkeypatch):
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        return len(calls) != 2, 0, "成功" if len(calls) != 2 else "超时"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(tasks=module.REMAINING_TASKS) == 1
    assert calls == [
        "主播打卡粉丝礼.py", "签到赢元宝.py",
        "睡觉赚元宝.py", "点淘鸭钻石任务.py", "点淘鸭摇一摇.py",
        "点淘购物赚钱.py", "打工得体力.py",
        "走路赚元宝.py", "元宝中心小任务.py",
    ]


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


def test_remaining_stop_prevents_next_script(monkeypatch):
    stop = Event()
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        stop.set()
        return False, 0, "用户停止"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(stop, module.REMAINING_TASKS) == 130
    assert calls == ["主播打卡粉丝礼.py"]


def test_missing_script_prevents_partial_run(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "SCRIPT_DIR", tmp_path)
    monkeypatch.setattr(module, "run_script", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
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
    assert module.execute(tasks=module.REMAINING_TASKS, max_rechecks=5) == 0
    assert calls == Counter({name: expected_runs for name, _ in module.REMAINING_TASKS})


@pytest.mark.parametrize("failure", ["exception", "timeout", "missing_feedback"])
def test_failed_rechecks_use_budget_and_continue_next_task(monkeypatch, failure):
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        if failure == "exception":
            raise RuntimeError("启动异常")
        return failure == "missing_feedback", 0, "成功" if failure == "missing_feedback" else "超时"

    monkeypatch.setattr(module, "run_script", fake_run)
    tasks = module.REMAINING_TASKS[:2]
    assert module.execute(tasks=tasks, max_rechecks=5) == 1
    assert calls == [tasks[0][0]] * 6 + [tasks[1][0]] * 6


def test_fifth_recheck_finishes_its_tasks_before_next_stage(monkeypatch):
    events = []
    rounds = Counter()
    first, second = module.REMAINING_TASKS[:2]

    def fake_run(filepath, **kwargs):
        rounds[filepath.name] += 1
        if filepath.name == first[0]:
            kwargs["on_line"](TASK_FOUND)
            events.append(("task_finished", rounds[filepath.name] - 1))
        else:
            events.append(("next_stage", rounds[filepath.name] - 1))
        kwargs["on_line"](ROUND_FINISHED)
        return True, 0, "成功"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(tasks=(first, second), max_rechecks=5) == 0
    assert events[5:7] == [("task_finished", 5), ("next_stage", 0)]
    assert rounds[first[0]] == 6
    assert rounds[second[0]] == 2


def test_stop_during_recheck_prevents_further_rounds_and_stages(monkeypatch):
    stop = Event()
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        kwargs["on_line"](TASK_FOUND)
        kwargs["on_line"](ROUND_FINISHED)
        if len(calls) == 2:
            stop.set()
        return True, 0, "成功"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(stop, module.REMAINING_TASKS, max_rechecks=5) == 130
    assert calls == [module.REMAINING_TASKS[0][0]] * 2
