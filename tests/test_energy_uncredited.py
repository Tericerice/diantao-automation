from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from tools import taobao_energy as task


def deadline():
    return datetime.now(timezone.utc) + timedelta(minutes=5)


def page():
    return [dict(text="做任务赚能量", cx=631, cy=590),
            dict(text="75700已累计升级已得", cx=344, cy=330),
            dict(text="16/50", cx=118, cy=845)]


def test_unchanged_balance_is_bounded_and_never_counted_as_success(monkeypatch):
    nodes = page()
    scan = Mock(return_value=nodes)
    monkeypatch.setattr(task, "scan", scan)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "_session", {"completed": 0})
    with pytest.raises(task.RewardNotConfirmed) as error:
        task.verify_gain(Mock(), nodes, 16, 75700, deadline())
    assert error.value.nodes == nodes
    assert scan.call_count == 2
    assert task._session["completed"] == 0


def test_uncredited_browse_is_skipped_and_next_task_runs(monkeypatch):
    nodes = page()
    d = Mock()
    d.app_current.return_value = dict(package=task.TB)
    attempts = []
    names = iter(["好物随心逛", "好物沉浸看", None])
    def choose(_, current, attempted, limit):
        attempts.append(set(attempted))
        return next(names), current
    browse = Mock(side_effect=[task.RewardNotConfirmed(nodes), nodes])
    monkeypatch.setattr(task, "next_task", choose)
    monkeypatch.setattr(task, "browse", browse)
    assert task.run_round(d, nodes, deadline(), 3, 17)
    assert browse.call_count == 2
    assert attempts == [set(), {"好物随心逛"}, {"好物随心逛"}]


@pytest.mark.parametrize("nodes,package", [
    ([], task.TB), (page(), "unknown.package"),
])
def test_uncredited_task_on_wrong_screen_still_stops(monkeypatch, nodes, package):
    d = Mock()
    d.app_current.return_value = dict(package=package)
    choose = Mock(return_value=("好物随心逛", page()))
    monkeypatch.setattr(task, "next_task", choose)
    monkeypatch.setattr(task, "browse", Mock(side_effect=task.RewardNotConfirmed(nodes)))
    with pytest.raises(task.RewardNotConfirmed):
        task.run_round(d, page(), deadline(), 3, 17)
    choose.assert_called_once()


def test_unrelated_browse_errors_are_not_swallowed(monkeypatch):
    monkeypatch.setattr(task, "next_task", Mock(return_value=("好物随心逛", page())))
    monkeypatch.setattr(task, "browse", Mock(side_effect=RuntimeError("腾讯云 OCR 请求失败")))
    with pytest.raises(RuntimeError, match="OCR"):
        task.run_round(Mock(), page(), deadline(), 3, 17)


def test_reward_check_respects_deadline_before_reading(monkeypatch):
    scan = Mock()
    monkeypatch.setattr(task, "scan", scan)
    with pytest.raises(RuntimeError, match="时限"):
        task.verify_gain(Mock(), page(), 16, 75700,
                         datetime.now(timezone.utc) - timedelta(seconds=1))
    scan.assert_not_called()
