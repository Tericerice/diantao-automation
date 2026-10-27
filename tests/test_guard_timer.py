"""Timer and workbench regression checks without operating a phone."""
from contextlib import nullcontext
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from guard_timer import RUN_ENV, GuardTimer, request_refresh, timer_status


ROOT = Path(__file__).resolve().parents[1]


def test_status_uses_elapsed_time_and_hides_previous_process(tmp_path):
    timer = GuardTimer(tmp_path, now=lambda: 100)
    timer.publish("waiting", schedule=SimpleNamespace(work_at=160, energy_at=110))
    result = timer_status(os.getpid(), directory=tmp_path, now=lambda: 115)
    assert result["work_remaining"] == 45
    assert result["energy_remaining"] == 0
    assert result["observed_at"] == 100
    for pid in (None, os.getpid() + 1):
        result = timer_status(pid, directory=tmp_path, now=lambda: 115)
        assert not result["active"]
        assert result["work_at"] is None
        assert result["energy_remaining"] is None


def test_new_run_discards_old_deadlines_and_corrupt_state(tmp_path):
    (tmp_path / "timer.json").write_text("{")
    assert timer_status(123, directory=tmp_path)["phase"] == "starting"
    timer = GuardTimer(tmp_path)
    timer.publish("starting")
    assert timer_status(os.getpid(), directory=tmp_path)["work_at"] is None


def test_windows_launcher_pid_uses_run_identity(monkeypatch, tmp_path):
    monkeypatch.setenv(RUN_ENV, "this-run")
    timer = GuardTimer(tmp_path)
    timer.publish("waiting", schedule=SimpleNamespace(work_at=160, energy_at=200))
    assert timer_status(os.getpid() + 1, run_id="this-run", directory=tmp_path)["active"]
    assert not timer_status(os.getpid(), run_id="older-run", directory=tmp_path)["active"]
    assert not timer_status(None, run_id="this-run", directory=tmp_path)["active"]


def load_guard():
    spec = importlib.util.spec_from_file_location("dagong_timer_test", ROOT / "打工任务.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_refresh_wakes_early_and_reschedules_from_new_observation(tmp_path, monkeypatch):
    guard = load_guard()
    clock = SimpleNamespace(value=100)
    calls = []

    def visit(*args, **kwargs):
        calls.append(clock.value)
        if len(calls) == 3:
            raise guard.GuardBlocked("unknown page")
        return guard.Schedule(200 if len(calls) == 1 else 125, 300)

    def sleep(seconds):
        clock.value += seconds
        if clock.value == 102:
            request_refresh(tmp_path)

    monkeypatch.setattr(guard, "visit", visit)
    with pytest.raises(guard.GuardBlocked):
        guard.guard(Mock(), state_path=tmp_path / "state.json", now=lambda: clock.value,
                    sleep=sleep, turn=nullcontext)
    assert calls == [100, 102, 125]
    assert timer_status(os.getpid(), directory=tmp_path)["phase"] == "blocked"


def test_retry_can_be_calibrated_and_cancelled(tmp_path, monkeypatch):
    guard = load_guard()
    clock = SimpleNamespace(value=100)
    visit = Mock(side_effect=[guard.ScanUnavailable("network"), KeyboardInterrupt])
    monkeypatch.setattr(guard, "visit", visit)

    def sleep(seconds):
        clock.value += seconds
        request_refresh(tmp_path)

    with pytest.raises(KeyboardInterrupt):
        guard.guard(Mock(), state_path=tmp_path / "state.json", now=lambda: clock.value,
                    sleep=sleep, turn=nullcontext)
    assert visit.call_count == 2
    assert clock.value == 101
    assert timer_status(os.getpid(), directory=tmp_path)["phase"] == "stopped"


def test_all_in_one_starts_guard_first_and_reuses_running_guard(monkeypatch, tmp_path):
    import workbench.app as desktop
    monkeypatch.setenv("DIANTAO_OCR_SERVER_URL", "http://ocr.invalid")
    monkeypatch.setattr(desktop, "RUNTIME", tmp_path)
    monkeypatch.setattr(desktop, "PROCESSES", {})
    monkeypatch.setattr(desktop, "STARTED", {})
    launches = []

    def launch(task_id, *args, **kwargs):
        launches.append(task_id)
        process = SimpleNamespace(pid=len(launches), poll=lambda: None)
        desktop.PROCESSES[task_id] = process
        desktop.STARTED[task_id] = 100
        return process

    monkeypatch.setattr(desktop, "launch_process", launch)
    desktop.start_task("diantao-all-in-one")
    assert launches == ["diantao-work-guard", "diantao-all-in-one"]
    desktop.PROCESSES.pop("diantao-all-in-one")
    desktop.start_task("diantao-all-in-one")
    assert launches.count("diantao-work-guard") == 1


def test_refresh_api_requires_running_guard(monkeypatch):
    import workbench.app as desktop
    monkeypatch.setattr(desktop, "PROCESSES", {})
    with pytest.raises(desktop.HTTPException) as exc:
        desktop.refresh_work_guard()
    assert exc.value.status_code == 409
    desktop.PROCESSES["diantao-work-guard"] = SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(desktop, "STARTED", {"diantao-work-guard": 100})
    request = Mock()
    monkeypatch.setattr(desktop, "request_refresh", request)
    assert desktop.refresh_work_guard()["ok"]
    request.assert_called_once_with()


def test_update_popup_and_home_label_recover_navigation(monkeypatch):
    guard = load_guard()
    monkeypatch.setattr(guard.time, "sleep", lambda _: None)
    monkeypatch.setitem(sys.modules, "u2_scanner", SimpleNamespace(
        navigate_to_dagong_page=lambda _: False))
    monkeypatch.setitem(sys.modules, "yuanbao_popup", SimpleNamespace(
        handle_yuanbao_live_popups=lambda _: True))
    device = Mock()
    device.window_size.return_value = (1264, 2780)
    phone = guard.Phone(device)
    home = guard.Page("home", work_seconds=3600, energy_seconds=600)
    phone.read = Mock(side_effect=[guard.Page("unknown"), home])
    center = {"text": "领元宝", "cx": 170, "cy": 670}
    work = {"text": "打工赚元宝", "cx": 480, "cy": 2240}
    phone.scan = Mock(side_effect=[
        [{"text": "快来更新点淘"}, {"text": "立即更新"}], [center], [work],
    ])
    phone.click = Mock()
    assert phone.enter() is home
    device.press.assert_called_once_with("back")
    assert [call.args[0] for call in phone.click.call_args_list] == [center, work]


def test_unconfirmed_navigation_retries_instead_of_ending_daemon(monkeypatch):
    guard = load_guard()
    monkeypatch.setitem(sys.modules, "u2_scanner", SimpleNamespace(
        navigate_to_dagong_page=lambda _: True))
    device = Mock()
    device.window_size.return_value = (1264, 2780)
    phone = guard.Phone(device)
    phone.read = Mock(return_value=guard.Page("unknown"))
    with pytest.raises(guard.ScanUnavailable):
        phone.enter()
    device.click.assert_not_called()


def test_energy_bonus_popup_dismisses_only_confirmed_optional_reward():
    guard = load_guard()
    blocks = [
        {"text": "定时奖励", "cx": 632, "cy": 783},
        {"text": "获得75体力", "cx": 631, "cy": 904},
        {"text": "看直播60秒", "cx": 630, "cy": 1738},
        {"text": "放弃获得额外奖励", "cx": 634, "cy": 1908},
    ]
    page = guard.inspect_page(blocks, (1264, 2780))
    assert page.kind == "energy_reward"
    home = guard.Page("home", work_seconds=6000, energy_seconds=300)
    phone = SimpleNamespace(enter=Mock(return_value=page),
                            read=Mock(return_value=home), click=Mock())
    now = 1_800_000_000
    schedule = guard.visit(phone, now=lambda: now)
    phone.click.assert_called_once_with(blocks[-1])
    assert schedule.work_at == now + 6001
    assert schedule.energy_at == now + 301
    assert guard.inspect_page(blocks[1:], (1264, 2780)).kind == "unknown"


def test_scan_prepares_screen_before_observation(monkeypatch):
    guard = load_guard()
    device = Mock()
    device.window_size.return_value = (1264, 2780)
    calls = []

    def shell(command):
        calls.append(command)
        return SimpleNamespace(output="")

    device.shell.side_effect = shell
    monkeypatch.setattr(guard.time, "sleep", lambda _: None)
    monkeypatch.setitem(sys.modules, "utils", SimpleNamespace(
        get_ocr_text_blocks=lambda *a, **kw: calls.append("ocr") or [{"text": "test"}]))
    phone = guard.Phone(device)
    phone.scan()
    assert calls == ["input keyevent KEYCODE_WAKEUP", "dumpsys window policy",
                     "wm dismiss-keyguard", "ocr"]


def test_secure_lockscreen_reports_required_user_action_without_ocr(monkeypatch):
    guard = load_guard()
    device = Mock()
    device.window_size.return_value = (1264, 2780)
    device.shell.return_value = SimpleNamespace(output="secure=true\nmIsShowing=true")
    monkeypatch.setattr(guard.time, "sleep", lambda _: None)
    ocr = Mock()
    monkeypatch.setitem(sys.modules, "utils", SimpleNamespace(get_ocr_text_blocks=ocr))
    with pytest.raises(guard.ScanUnavailable, match="请解锁"):
        guard.Phone(device).scan()
    ocr.assert_not_called()
    assert device.shell.call_count == 2
