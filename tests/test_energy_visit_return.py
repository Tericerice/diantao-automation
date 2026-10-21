from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from tools import taobao_energy as task


def deadline():
    return datetime.now(timezone.utc) + timedelta(minutes=2)


def page(balance=91400):
    return [dict(text="做任务赚能量", cx=630, cy=590),
            dict(text=str(balance), cx=210, cy=343),
            dict(text="48/50", cx=118, cy=845),
            dict(text="逛一逛蚂蚁庄园(0/1)", cx=430, cy=1460),
            dict(text="去完成", cx=1102, cy=1492)]


@pytest.fixture
def phone(monkeypatch):
    d = Mock()
    d.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    d.window_size.return_value = (1264, 2780)
    def foreground(*args, **kwargs):
        d.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    d.app_start.side_effect = foreground
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "_session", {})
    return d


def test_returns_from_external_app_without_operating_its_login(phone, monkeypatch):
    phone.app_current.return_value = dict(package="com.eg.android.AlipayGphone", activity="FingerprintActivity")
    monkeypatch.setattr(task, "scan", Mock(return_value=page()))
    assert task.return_from_visit(phone, deadline()) == page()
    phone.app_start.assert_called_once_with(task.TB, use_monkey=True)
    phone.click.assert_not_called()
    phone.press.assert_not_called()


def test_existing_list_is_preserved_without_back_or_relaunch(phone, monkeypatch):
    monkeypatch.setattr(task, "scan", Mock(return_value=page()))
    assert task.return_from_visit(phone, deadline()) == page()
    phone.press.assert_not_called()
    phone.app_start.assert_not_called()


def test_return_reenters_list_from_taobao_home(phone, monkeypatch):
    phone.app_current.return_value["activity"] = "TBMainActivity"
    monkeypatch.setattr(task, "scan", Mock(return_value=[dict(text="领淘金币")]))
    enter = Mock(return_value=page())
    monkeypatch.setattr(task, "enter", enter)
    assert task.return_from_visit(phone, deadline()) == page()
    enter.assert_called_once()

def test_interrupted_activity_entry_is_retried_from_fresh_taobao(phone, monkeypatch):
    phone.app_current.return_value["activity"] = "TBMainActivity"
    monkeypatch.setattr(task, "scan", Mock(side_effect=[[dict(text="领淘金币")], page()]))
    monkeypatch.setattr(task, "enter", Mock(side_effect=RuntimeError("请先回到淘宝首页")))
    assert task.return_from_visit(phone, deadline()) == page()
    phone.app_start.assert_called_once_with(task.TB, stop=True, use_monkey=True)


def test_ocr_service_error_during_return_is_not_hidden(phone, monkeypatch):
    phone.app_current.return_value["activity"] = "TBMainActivity"
    monkeypatch.setattr(task, "scan", Mock(return_value=[dict(text="领淘金币")]))
    monkeypatch.setattr(task, "enter", Mock(side_effect=RuntimeError("OCR服务请求失败")))
    with pytest.raises(RuntimeError, match="OCR"):
        task.return_from_visit(phone, deadline())
    phone.app_start.assert_not_called()


def test_internal_visit_returns_through_taobao_page(phone, monkeypatch):
    phone.app_current.return_value["activity"] = "BrowserActivity"
    monkeypatch.setattr(task, "scan", Mock(side_effect=[[dict(text="商品活动")], page()]))
    assert task.return_from_visit(phone, deadline()) == page()
    phone.press.assert_called_once_with("back")


def test_delayed_redirect_during_ocr_invalidates_old_list(phone, monkeypatch):
    scans = 0
    def scan(_):
        nonlocal scans
        scans += 1
        if scans == 1:
            phone.app_current.return_value["package"] = "com.eg.android.AlipayGphone"
        return page()
    monkeypatch.setattr(task, "scan", scan)
    assert task.return_from_visit(phone, deadline()) == page()
    assert scans == 2
    phone.app_start.assert_called_once_with(task.TB, stop=True, use_monkey=True)

def test_redirect_after_list_recognition_requires_stable_foreground(phone, monkeypatch):
    redirected = False
    def sleep(seconds):
        nonlocal redirected
        if seconds == 2 and not redirected:
            redirected = True
            phone.app_current.return_value["package"] = "com.eg.android.AlipayGphone"
    monkeypatch.setattr(task.time, "sleep", sleep)
    monkeypatch.setattr(task, "scan", Mock(return_value=page()))
    assert task.return_from_visit(phone, deadline()) == page()
    assert phone.app_current()["package"] == task.TB
    phone.app_start.assert_called_once_with(task.TB, stop=True, use_monkey=True)


@pytest.mark.parametrize("package", ["com.oplus.securitypermission", "unknown.redirect"])
def test_unknown_permission_or_redirect_is_left_without_clicking(phone, monkeypatch, package):
    phone.adb_device.shell.return_value = "package:installed"
    phone.click.side_effect = lambda *args: phone.app_current.return_value.update(package=package)
    monkeypatch.setattr(task, "scan", lambda _: [] if phone.app_current()["package"] != task.TB else page(92200))
    assert task.visit(phone, "逛一逛蚂蚁庄园", deadline(), page()) == page(92200)
    phone.click.assert_called_once_with(1102, 1492)
    assert phone.app_current()["package"] == task.TB


def test_delayed_redirect_during_reward_check_returns_and_confirms_gain(phone, monkeypatch):
    reads = 0
    def scan(_):
        nonlocal reads
        reads += 1
        if reads == 1:
            phone.app_current.return_value["package"] = "com.eg.android.AlipayGphone"
            return [dict(text="支付宝·芭芭农场")]
        return [dict(n, text="49/50") if n["text"] == "48/50" else n for n in page(92200)]
    monkeypatch.setattr(task, "scan", scan)
    result = task.verify_gain(phone, page(), 48, None, deadline(), recover_visit=True)
    assert task.task_progress(result) == 49
    assert task._session["completed"] == 1
    phone.app_start.assert_called_once_with(task.TB, use_monkey=True)


def test_foreground_retry_is_bounded(phone, monkeypatch):
    phone.app_current.return_value["package"] = "com.eg.android.AlipayGphone"
    phone.app_start.side_effect = None
    scan = Mock()
    monkeypatch.setattr(task, "scan", scan)
    with pytest.raises(RuntimeError, match="3次返回淘宝"):
        task.return_from_visit(phone, deadline())
    assert phone.app_start.call_count == 3
    phone.press.assert_not_called()
    scan.assert_not_called()


def test_expired_return_does_not_touch_phone(phone):
    with pytest.raises(RuntimeError, match="时限"):
        task.return_from_visit(phone, datetime.now(timezone.utc) - timedelta(seconds=1))
    assert phone.mock_calls == []


def test_round_continues_to_next_task_after_return(phone, monkeypatch):
    phone.adb_device.shell.return_value = "package:installed"
    def leave(*args):
        phone.app_current.return_value["package"] = "com.eg.android.AlipayGphone"
    phone.click.side_effect = leave
    monkeypatch.setattr(task, "scan", Mock(return_value=page(92200)))
    tasks = iter(["逛一逛蚂蚁庄园", "好物随心逛", None])
    monkeypatch.setattr(task, "next_task", lambda _, nodes, *args: (next(tasks), nodes))
    browse = Mock(return_value=page(92200))
    monkeypatch.setattr(task, "browse", browse)
    assert task.run_round(phone, page(), deadline(), 3, 17)
    browse.assert_called_once()
    assert phone.app_current()["package"] == task.TB
