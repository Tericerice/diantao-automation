from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from tools import taobao_energy as task


def deadline():
    return datetime.now(timezone.utc) + timedelta(minutes=1)


@pytest.mark.parametrize("initial_activity", ["TMSActivity", "TBMainActivity"])
def test_new_start_relaunches_even_when_taobao_is_already_open(
    monkeypatch, initial_activity
):
    device = Mock()
    home = dict(package=task.TB, activity="TBMainActivity")
    device.app_current.side_effect = [dict(package=task.TB, activity=initial_activity)]
    # 重启后所有读屏均处于首页；弹窗检查也会核对前台应用。
    def start(*args, **kwargs):
        device.app_current.side_effect = None
        device.app_current.return_value = home
    device.app_start.side_effect = start
    entry = Mock(exists=True)
    absent = Mock(exists=False)
    device.side_effect = lambda **query: entry if query == {"text": "领淘金币"} else absent
    opened = [dict(text="做任务赚能量", cx=500, cy=600)]
    monkeypatch.setattr(task, "scan", lambda _: opened)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)

    assert task.enter(device, deadline(), restart=True) == opened
    device.app_start.assert_called_once_with(task.TB, stop=True, use_monkey=True)
    entry.click.assert_called_once()


def test_restart_stops_without_clicking_if_home_never_appears(monkeypatch):
    device = Mock()
    device.app_current.return_value = dict(package=task.TB, activity="UnknownActivity")
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    scan = Mock()
    monkeypatch.setattr(task, "scan", scan)

    with pytest.raises(RuntimeError, match="未确认淘宝首页"):
        task.enter(device, deadline(), restart=True)
    device.click.assert_not_called()
    device.assert_not_called()
    scan.assert_not_called()


def test_expired_run_does_not_restart_the_phone():
    device = Mock()
    with pytest.raises(RuntimeError, match="时限"):
        task.enter(
            device, datetime.now(timezone.utc) - timedelta(seconds=1), restart=True
        )
    device.app_start.assert_not_called()


def test_returning_to_open_task_list_preserves_the_running_app(monkeypatch):
    device = Mock()
    device.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    opened = [dict(text="做任务赚能量", cx=500, cy=600)]
    monkeypatch.setattr(task, "scan", lambda _: opened)

    assert task.enter(device, deadline()) == opened
    device.app_start.assert_not_called()


@pytest.mark.parametrize("action", ["run", "enter"])
def test_manual_commands_request_a_fresh_start(monkeypatch, tmp_path, action):
    device = Mock()
    device.window_size.return_value = (1264, 2780)
    enter = Mock(return_value=[dict(text="做任务赚能量", cx=500, cy=600)])
    monkeypatch.setattr(task.sys, "argv", ["taobao_energy.py", action, "--serial", "phone"])
    monkeypatch.setattr(task, "setup_logging", lambda: tmp_path / "session.log")
    monkeypatch.setattr(task, "ocr_server_url", lambda: "configured")
    monkeypatch.setattr(task, "connect_with_retry", lambda _: device)
    monkeypatch.setattr(task, "enter", enter)
    monkeypatch.setattr(task, "next_task", lambda _, nodes, *args: (None, nodes))
    monkeypatch.setattr(task, "close_entry_popups", lambda _d, _deadline, nodes: nodes)

    task.main()
    assert enter.call_args.args[0] is device
    assert enter.call_args.kwargs == {"restart": True}


def test_entry_retry_uses_fresh_coordinates_and_checks_task_list(monkeypatch):
    device = Mock()
    device.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    first = [dict(text="升级赛车拿钱", cx=630, cy=1110),
             dict(text="去赚能量", cx=1144, cy=1187)]
    second = [dict(text="升级赛车拿钱", cx=630, cy=1110),
              dict(text="去赚能量", cx=1140, cy=1190)]
    opened = [dict(text="做任务赚能量", cx=500, cy=600)]
    scans = iter([first, second, opened])
    monkeypatch.setattr(task, "scan", lambda _: next(scans))
    monkeypatch.setattr(task.time, "sleep", lambda _: None)

    assert task.enter(device, deadline()) == opened
    assert [call.args for call in device.click.call_args_list] == [
        (1144, 1187), (1140, 1190),
    ]


def test_entry_never_reports_success_when_task_list_does_not_open(monkeypatch):
    device = Mock()
    device.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    nodes = [dict(text="升级赛车拿钱", cx=630, cy=1110),
             dict(text="去赚能量", cx=1144, cy=1187)]
    monkeypatch.setattr(task, "scan", lambda _: nodes)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="仍未确认任务列表"):
        task.enter(device, deadline())
    assert device.click.call_count == 3
