from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from tools import taobao_energy as task


def deadline():
    return datetime.now(timezone.utc) + timedelta(minutes=1)


@pytest.fixture
def phone(monkeypatch):
    d = Mock()
    d.app_current.return_value = dict(package=task.TB, activity="com.taobao.search.SearchActivity")
    d.return_value = Mock(exists=True, count=1)
    monkeypatch.setattr(task, "_session", {})
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    return d


def test_search_types_saved_terms_in_rotation_without_reading_recommendations(phone, monkeypatch):
    scan = Mock()
    monkeypatch.setattr(task, "scan", scan)
    for _ in range(len(task.SEARCH_TERMS) + 1):
        task.search_saved_term(phone, deadline())
    assert [c.args[0] for c in phone.send_keys.call_args_list] == [
        *task.SEARCH_TERMS, task.SEARCH_TERMS[0],
    ]
    assert task.SEARCH_TERMS[:2] == ("固态硬盘", "牛肉干")
    assert all(c.kwargs == {"clear": True} for c in phone.send_keys.call_args_list)
    assert all(c.args == ("enter",) for c in phone.press.call_args_list)
    scan.assert_not_called()


@pytest.mark.parametrize("exists,count", [(False, 0), (True, 2)])
def test_missing_or_ambiguous_search_field_never_types(phone, exists, count):
    phone.return_value.exists = exists
    phone.return_value.count = count
    with pytest.raises(RuntimeError, match="搜索输入框"):
        task.search_saved_term(phone, deadline())
    phone.send_keys.assert_not_called()
    phone.press.assert_not_called()


def test_search_does_not_type_into_another_application(phone):
    phone.app_current.return_value = dict(package="other.package")
    with pytest.raises(RuntimeError, match="离开淘宝"):
        task.search_saved_term(phone, deadline())
    phone.send_keys.assert_not_called()
    phone.assert_not_called()


def test_expired_search_does_not_focus_or_type(phone):
    with pytest.raises(RuntimeError, match="时限"):
        task.search_saved_term(phone, datetime.now(timezone.utc) - timedelta(seconds=1))
    phone.assert_not_called()
    phone.send_keys.assert_not_called()

def test_unknown_page_does_not_receive_saved_keyword(phone, monkeypatch):
    phone.app_current.return_value["activity"] = "LoginActivity"
    monkeypatch.setattr(task, "scan", Mock(return_value=[dict(text="请输入手机号")]))
    with pytest.raises(RuntimeError, match="搜索页面"):
        task.search_saved_term(phone, deadline())
    phone.send_keys.assert_not_called()


def test_webview_search_can_use_its_identified_input_field(phone, monkeypatch):
    phone.app_current.return_value["activity"] = "TMSActivity"
    monkeypatch.setattr(task, "scan", Mock(return_value=[dict(text="搜索有福利")]))
    task.search_saved_term(phone, deadline())
    phone.send_keys.assert_called_once_with("固态硬盘", clear=True)


def test_search_browse_uses_saved_input_and_keeps_reward_verification(phone, monkeypatch, tmp_path):
    nodes = [
        dict(text="做任务赚能量", cx=600, cy=590),
        dict(text="搜一搜你喜欢的宝贝(0/10)", cx=430, cy=1460),
        dict(text="去完成", cx=1102, cy=1492),
        dict(text="75700", cx=210, cy=343),
    ]
    phone.window_size.return_value = (1264, 2780)
    phone.screenshot.return_value.save = Mock()
    verify = Mock(return_value=nodes)
    monkeypatch.setattr(task, "OUT", tmp_path)
    monkeypatch.setattr(task, "return_from_browse", Mock(return_value=nodes))
    monkeypatch.setattr(task, "verify_gain", verify)
    monkeypatch.setattr(task, "scan", Mock(side_effect=AssertionError("不读取推荐词")))
    assert task.browse(phone, "搜一搜你喜欢的宝贝", 5, deadline(), nodes) == nodes
    phone.send_keys.assert_called_once_with("固态硬盘", clear=True)
    verify.assert_called_once()
