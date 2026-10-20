from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from tools import taobao_energy as task


def deadline():
    return datetime.now(timezone.utc) + timedelta(minutes=5)


def node(text, x=500, y=600):
    return dict(text=text, cx=x, cy=y)


def device():
    d = Mock()
    d.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    return d


def test_event_popups_are_closed_in_sequence_using_fresh_screens(monkeypatch):
    d = device()
    opened = [node("做任务赚能量"), node("×", 1100, 600)]
    scan = Mock(side_effect=[[node("稍后再说", 600, 1800)], opened])
    monkeypatch.setattr(task, "scan", scan)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    assert task.close_entry_popups(d, deadline(), [node("我知道了")]) == opened
    assert [c.args for c in d.click.call_args_list] == [(500, 600), (600, 1800)]


def test_event_popup_is_cleared_before_clicking_energy_entry(monkeypatch):
    d = device()
    event = [node("升级赛车拿钱"), node("去赚能量", 1100, 1200)]
    opened = [node("做任务赚能量")]
    scan = Mock(side_effect=[[node("我知道了", 600, 1800)], event, opened])
    monkeypatch.setattr(task, "scan", scan)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    assert task.enter(d, deadline()) == opened
    assert [c.args for c in d.click.call_args_list] == [(600, 1800), (1100, 1200)]


@pytest.mark.parametrize("nodes", [
    [node("×"), node("立即领取"), node("去授权")],
    [node("取消"), node("开启会员")],
    [node("做任务赚能量"), node("×")],
])
def test_unknown_popup_or_task_sheet_close_is_not_clicked(nodes):
    d = device()
    assert task.close_entry_popups(d, deadline(), nodes) == nodes
    d.click.assert_not_called()


def test_reappearing_popup_is_bounded(monkeypatch):
    d = device()
    popup = [node("下次再说")]
    monkeypatch.setattr(task, "scan", lambda _: popup)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="3次"):
        task.close_entry_popups(d, deadline(), popup)
    assert d.click.call_count == 3


def test_ambiguous_popup_does_not_click():
    d = device()
    with pytest.raises(RuntimeError, match="未唯一"):
        task.close_entry_popups(d, deadline(), [node("我知道了"), node("我知道了", 600)])
    d.click.assert_not_called()


def test_native_description_popup_is_closed_and_rechecked(monkeypatch):
    d = device()
    popup = Mock(exists=True, count=1)
    absent = Mock(exists=False)
    def select(**query):
        return popup if "descriptionMatches" in query and popup.exists else absent
    d.side_effect = select
    popup.click.side_effect = lambda: setattr(popup, "exists", False)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    task.close_entry_popups(d, deadline())
    popup.click.assert_called_once()


@pytest.mark.parametrize("outside,expired", [(True, False), (False, True)])
def test_popup_guards_prevent_clicks(outside, expired):
    d = device()
    if outside:
        d.app_current.return_value["package"] = "other"
    limit = datetime.now(timezone.utc) - timedelta(seconds=1) if expired else deadline()
    with pytest.raises(RuntimeError):
        task.close_entry_popups(d, limit, [node("我知道了")])
    d.click.assert_not_called()


def prepare_main(monkeypatch, tmp_path, extra=(), action="run"):
    d = device()
    entry = Mock(return_value=[node("做任务赚能量")])
    monkeypatch.setattr(task.sys, "argv", ["taobao_energy.py", action, "--serial", "phone", *extra])
    monkeypatch.setattr(task, "setup_logging", lambda: tmp_path / "session.log")
    monkeypatch.setattr(task, "ocr_server_url", lambda: "configured")
    monkeypatch.setattr(task, "connect_with_retry", Mock(return_value=d))
    monkeypatch.setattr(task, "enter", entry)
    return d, entry


@pytest.mark.parametrize("results,expected", [
    ([False, False], 2), ([True, True, False], 3), ([True] * 6, 6),
])
def test_default_rechecks_stop_on_empty_and_have_a_hard_limit(monkeypatch, tmp_path, results, expected):
    _, entry = prepare_main(monkeypatch, tmp_path)
    run = Mock(side_effect=results)
    monkeypatch.setattr(task, "run_round", run)
    task.main()
    assert entry.call_count == run.call_count == expected
    assert all(c.kwargs == {"restart": True} for c in entry.call_args_list)
    assert len({c.args[2] for c in run.call_args_list}) == 1  # 所有轮次共用同一截止时间


def test_rechecks_can_be_disabled(monkeypatch, tmp_path):
    _, entry = prepare_main(monkeypatch, tmp_path, ("--rechecks", "0"))
    run = Mock(return_value=True)
    monkeypatch.setattr(task, "run_round", run)
    task.main()
    assert entry.call_count == run.call_count == 1


def test_auto_defaults_to_current_screen_without_recheck(monkeypatch, tmp_path):
    _, entry = prepare_main(monkeypatch, tmp_path, action="auto")
    monkeypatch.setattr(task, "scan", Mock(return_value=[node("做任务赚能量")]))
    run = Mock(return_value=True)
    monkeypatch.setattr(task, "run_round", run)
    task.main()
    entry.assert_not_called()
    run.assert_called_once()


def test_recheck_does_not_restart_after_deadline(monkeypatch, tmp_path):
    _, entry = prepare_main(monkeypatch, tmp_path)
    monkeypatch.setattr(task, "run_round", Mock(return_value=True))
    real_guard = task.guard
    def guard(limit):
        if entry.call_count:
            raise RuntimeError("时限已到")
        real_guard(limit)
    monkeypatch.setattr(task, "guard", guard)
    with pytest.raises(RuntimeError, match="时限"):
        task.main()
    assert entry.call_count == 1


def test_attempted_visits_are_reset_between_rounds(monkeypatch):
    d = device()
    opened = [node("做任务赚能量")]
    attempts = []
    def next_task(_, nodes, attempted, limit):
        attempts.append(set(attempted))
        return ("逛一逛蚂蚁庄园" if not attempted else None), nodes
    monkeypatch.setattr(task, "next_task", next_task)
    monkeypatch.setattr(task, "visit", lambda *args: opened)
    assert task.run_round(d, opened, deadline(), 2, 25)
    assert task.run_round(d, opened, deadline(), 2, 25)
    assert attempts == [set(), {"逛一逛蚂蚁庄园"}, set(), {"逛一逛蚂蚁庄园"}]


def test_failed_reward_verification_preserves_scene_instead_of_restart(monkeypatch, tmp_path):
    _, entry = prepare_main(monkeypatch, tmp_path)
    monkeypatch.setattr(task, "run_round", Mock(side_effect=RuntimeError("未确认任务奖励增加")))
    with pytest.raises(RuntimeError, match="未确认"):
        task.main()
    assert entry.call_count == 1


@pytest.mark.parametrize("value", ["-1", "6"])
def test_invalid_recheck_limit_fails_before_connecting(monkeypatch, tmp_path, value):
    _, entry = prepare_main(monkeypatch, tmp_path, ("--rechecks", value))
    with pytest.raises(SystemExit):
        task.main()
    task.connect_with_retry.assert_not_called()
    entry.assert_not_called()
