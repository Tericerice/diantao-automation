"""打工守护的双时钟、页面状态转换和恢复，不连接手机或 OCR。"""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from deploy.register_work_guard import register, TARGET_ID


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dagong_guard_test", ROOT / "打工任务.py")
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)
SIZE = (1264, 2780)
NOW = 1_800_000_000


@pytest.fixture(autouse=True)
def isolated_phone_control(monkeypatch, tmp_path):
    monkeypatch.setenv("DIANTAO_CONTROL_DIR", str(tmp_path / "phone-control"))


def block(value, x, y):
    return dict(text=value, cx=x, cy=y)


def home(work="01:59:40", energy="00:00:46"):
    return [block(work, 630, 1728), block("打工中", 628, 1795),
            block("得体力", 1122, 1807), block(energy, 136, 1807),
            block("15:42", 130, 76), block("21:00", 196, 1325)]


def chooser():
    return [block("选工作 赚元宝", 633, 1655), block("廚师", 552, 1857),
            block("打工120分钟", 631, 1931), block("+888", 668, 2320),
            block("开始打工", 631, 2552),
            block("歌手", 147, 1858), block("打工10分钟", 230, 1931),
            block("+188", 249, 2322), block("带货", 954, 1857),
            block("打工60分钟", 1032, 1931), block("+588", 1060, 2320)]


def reward():
    return [block("恭喜获得元宝", 631, 1222), block("888", 576, 1462),
            block("元宝", 784, 1494), block("去完成", 634, 1779)]


def reward_claim():
    return [block("打工奖励", 631, 784), block("获得888元宝", 634, 905),
            block("开心收下", 631, 1739)]


def page(blocks):
    return guard.inspect_page(blocks, SIZE)


def phone_with(*pages):
    return SimpleNamespace(enter=Mock(return_value=pages[0]),
                           read=Mock(side_effect=pages[1:]),
                           click=Mock(), finish_reward=Mock())


def test_two_timers_ignore_status_bar_and_decorative_clock():
    result = page(home())
    assert result.kind == "home"
    assert result.work_seconds == 7180
    assert result.energy_seconds == 46
    assert result.energy is None
    assert page([block("21:00", 196, 1325), block("15:42", 130, 76)]).kind == "unknown"


@pytest.mark.parametrize("seconds", [5, 10, 30, 60, 120, 300, 1800, 10800])
def test_energy_uses_actual_increasing_interval(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, sec = divmod(remainder, 60)
    result = page(home(energy=f"{hours:02}:{minutes:02}:{sec:02}"))
    schedule = guard.Schedule.from_page(result, 100)
    assert schedule.energy_at == 100 + seconds + 1
    assert schedule.next_at() == min(schedule.work_at, schedule.energy_at)


def test_missing_energy_timer_rechecks_soon_without_delaying_work():
    schedule = guard.Schedule.from_page(page(home(work="00:00:03", energy="?")), 100)
    assert schedule.work_at == 104
    assert schedule.energy_at == 116
    assert schedule.next_at() == 104


def test_chooser_uses_real_ocr_variant_and_requires_two_hour_reward():
    result = page(chooser())
    assert result.kind == "chooser"
    assert result.chef["text"] == "廚师"
    wrong = chooser()
    wrong[2]["text"] = "打工10分钟"
    assert page(wrong).kind == "unknown"
    wrong = chooser()
    wrong[3]["text"] = "+188"
    assert page(wrong).kind == "unknown"


def test_reward_popup_is_not_treated_as_home():
    assert page(reward() + home(work="去打工赚钱", energy="领体力")).kind == "reward"


def test_full_cycle_collects_energy_finishes_reward_starts_chef_and_rescans():
    ready = page(home(work="领取888元宝", energy="领体力"))
    claimed_energy = page(home(work="领取888元宝", energy="00:02:00"))
    idle = page(home(work="去打工赚钱", energy="00:01:50"))
    choice = page(chooser())
    working = page(home(energy="00:01:40"))
    phone = phone_with(ready, claimed_energy, page(reward()), idle, choice, choice, working)
    schedule = guard.visit(phone, now=lambda: NOW)
    assert phone.click.call_args_list == [
        call(ready.energy), call(claimed_energy.claim), call(idle.work),
        call(choice.chef), call(choice.start),
    ]
    phone.finish_reward.assert_called_once()
    assert schedule.work_at == NOW + 7181
    assert schedule.energy_at == NOW + 101


def test_reward_claim_popup_clicks_accept_and_continues():
    claimed_popup = page(reward_claim())
    assert claimed_popup.kind == "reward_claim"
    assert claimed_popup.complete["text"] == "开心收下"

    ready = page(home(work="领取888元宝", energy="已领完"))
    idle = page(home(work="去打工赚钱", energy="已领完"))
    choice = page(chooser())
    working = page(home(work="01:59:40", energy="已领完"))
    phone = phone_with(ready, claimed_popup, idle, choice, choice, working)
    schedule = guard.visit(phone, now=lambda: NOW)
    assert phone.click.call_args_list == [
        call(ready.claim), call(claimed_popup.complete), call(idle.work),
        call(choice.chef), call(choice.start),
    ]
    phone.finish_reward.assert_not_called()
    assert schedule.work_at == NOW + 7181
    assert schedule.energy_at == NOW + 7181  # 已领完随打工倒计时复查，杜绝15秒死循环抢占


def test_restart_reads_remaining_work_without_resetting_two_hours():
    working = page(home(work="00:32:10", energy="01:30:00"))
    phone = phone_with(working)
    schedule = guard.visit(phone, now=lambda: NOW)
    phone.click.assert_not_called()
    assert schedule.work_at == NOW + 1931
    assert schedule.next_at() == NOW + 1931


def test_unknown_page_never_clicks():
    phone = phone_with(page([block("立即下单", 600, 1750)]))
    with pytest.raises(guard.GuardBlocked):
        guard.visit(phone)
    phone.click.assert_not_called()


def test_chef_start_must_confirm_two_hour_countdown():
    choice = page(chooser())
    phone = phone_with(choice, choice, page(home(work="00:09:58")))
    with pytest.raises(guard.GuardBlocked, match="两小时"):
        guard.visit(phone)
    assert phone.click.call_count == 2


def test_reward_task_failure_stops_before_starting_work():
    phone = phone_with(page(reward()))
    phone.finish_reward.side_effect = guard.GuardBlocked("未识别任务页面")
    with pytest.raises(guard.GuardBlocked):
        guard.visit(phone)
    phone.click.assert_not_called()


def test_unavailable_ocr_retries_without_clicking_and_persists_schedule(monkeypatch, tmp_path):
    visits = Mock(side_effect=[guard.ScanUnavailable("网络失败"), guard.Schedule(7300, 200)])
    monkeypatch.setattr(guard, "visit", visits)
    clock = SimpleNamespace(value=100)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock.value += seconds
        if clock.value >= 116:
            raise KeyboardInterrupt

    path = tmp_path / "state.json"
    with pytest.raises(KeyboardInterrupt):
        guard.guard(Mock(), state_path=path, now=lambda: clock.value, sleep=sleep)
    assert visits.call_count == 2
    assert sum(sleeps[:15]) == 15
    assert max(sleeps) == 1
    assert json.loads(path.read_text()) == {"work_at": 7300, "energy_at": 200}


def test_once_returns_schedule_without_waiting(monkeypatch, tmp_path):
    result = guard.Schedule(7200, 10800)
    monkeypatch.setattr(guard, "visit", lambda *a, **kw: result)
    sleep = Mock()
    assert guard.guard(Mock(), once=True, state_path=tmp_path / "state.json", sleep=sleep) == result
    sleep.assert_not_called()


def test_waiting_long_intervals_is_interruptible():
    clock = SimpleNamespace(value=0)
    waits = []

    def sleep(seconds):
        clock.value += seconds
        waits.append(seconds)

    guard.wait_until(7200, now=lambda: clock.value, sleep=sleep)
    assert sum(waits) == 7200
    assert max(waits) == 30


def test_guard_wakes_for_each_timer_and_keeps_next_chef_deadline(monkeypatch, tmp_path):
    clock = SimpleNamespace(value=NOW)
    events = []
    schedules = iter([
        guard.Schedule(NOW + 7200, NOW + 5),
        guard.Schedule(NOW + 7200, NOW + 10805),
        guard.Schedule(NOW + 14400, NOW + 10805),
    ])

    def visit(*args, **kwargs):
        events.append(clock.value)
        return next(schedules)

    def sleep(seconds):
        clock.value += seconds

    monkeypatch.setattr(guard, "visit", visit)
    with pytest.raises(StopIteration):
        guard.guard(Mock(), state_path=tmp_path / "state.json",
                    now=lambda: clock.value, sleep=sleep)
    assert events == [NOW, NOW + 5, NOW + 7200, NOW + 10805]
    assert json.loads((tmp_path / "state.json").read_text())["work_at"] == NOW + 14400


@pytest.mark.parametrize("media", ["live", "video", "browse"])
def test_reward_task_uses_existing_executor_and_confirms_return(monkeypatch, media):
    device = Mock()
    device.window_size.return_value = SIZE
    phone = guard.Phone(device)
    landing = [block("滑动浏览30秒" if media == "browse" else "30秒后完成", 600, 600)]
    phone.scan = Mock(return_value=landing)
    phone.click = Mock()
    phone.read = Mock(side_effect=[guard.Page("unknown"), page(home(work="去打工赚钱"))])
    scanner = SimpleNamespace(
        classify_media_page=lambda _: None if media == "browse" else media,
        execute_live_task=Mock(return_value=True),
        execute_video_task=Mock(return_value=True),
        execute_browse_task=Mock(return_value=True),
    )
    monkeypatch.setitem(sys.modules, "u2_scanner", scanner)
    monkeypatch.setattr(guard.time, "sleep", lambda _: None)
    phone.finish_reward(page(reward()))
    phone.click.assert_called_once_with(page(reward()).complete)
    executor = getattr(scanner, f"execute_{media}_task")
    executor.assert_called_once()
    if media == "browse":
        assert executor.call_args.kwargs["min_duration"] == 30
    else:
        assert executor.call_args.kwargs["duration"] == (35 if media == "live" else 30)
    device.press.assert_called_once_with("back")


def test_unknown_reward_landing_stops_without_using_media_executors(monkeypatch):
    device = Mock()
    device.window_size.return_value = SIZE
    phone = guard.Phone(device)
    phone.click = Mock()
    phone.scan = Mock(return_value=[block("确认订单", 500, 1200)])
    scanner = SimpleNamespace(
        classify_media_page=lambda _: None,
        execute_live_task=Mock(), execute_video_task=Mock(), execute_browse_task=Mock(),
    )
    monkeypatch.setitem(sys.modules, "u2_scanner", scanner)
    monkeypatch.setattr(guard.time, "sleep", lambda _: None)
    with pytest.raises(guard.GuardBlocked, match="尚未支持"):
        phone.finish_reward(page(reward()))
    scanner.execute_live_task.assert_not_called()
    scanner.execute_video_task.assert_not_called()
    scanner.execute_browse_task.assert_not_called()
    device.press.assert_not_called()


def test_independent_dashboard_entry_does_not_join_batch_catalog():
    from workbench.tasks import TASKS
    from task_catalog import TASK_FILES
    task = TASKS[TARGET_ID]
    assert task["name"] == "打工守护"
    assert task["script"] == "打工任务.py"
    assert task["args"] == []
    assert task["script"] not in TASK_FILES


def test_butler_registration_is_idempotent_and_preserves_other_tasks(tmp_path):
    path = tmp_path / "tools" / "managed_process" / "registry.yaml"
    path.parent.mkdir(parents=True)
    original = "targets:\n  - id: diantao-work\n    name: original\n"
    path.write_text(original, encoding="utf-8")
    register(tmp_path)
    first = path.read_text(encoding="utf-8")
    register(tmp_path)
    assert path.read_text(encoding="utf-8") == first
    assert first.count(f"id: {TARGET_ID}\n") == 1
    assert "    name: original" in first
    assert "execution_timeout_seconds" not in first
