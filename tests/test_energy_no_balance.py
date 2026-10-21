from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from tools import taobao_energy as task


def deadline():
    return datetime.now(timezone.utc) + timedelta(minutes=2)


def page(title="好物沉浸看", count=7, total=29, header="121000累计"):
    nodes = [dict(text="做任务赚能量", cx=631, cy=590),
             dict(text=f"{title}({count}/10)", cx=434, cy=1686),
             dict(text="去完成", cx=1102, cy=1720)]
    if total is not None:
        nodes.append(dict(text=f"{total}/50", cx=118, cy=845))
    if header is not None:
        nodes.append(dict(text=header, cx=263, cy=336))
    return nodes


@pytest.fixture
def phone(monkeypatch, tmp_path):
    d = MagicMock()
    d.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    d.window_size.return_value = (1264, 2780)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "OUT", tmp_path)
    monkeypatch.setattr(task, "_session", {"completed": 0})
    return d


@pytest.mark.parametrize("header", ["121000累计", None, "1206007"])
@pytest.mark.parametrize("total", [29, 50, None])
def test_browse_ignores_balance_and_uses_task_progress(phone, monkeypatch, header, total):
    before = page(header=header, total=total)
    after = page(count=8, header=header, total=total)
    monkeypatch.setattr(task, "scan", lambda _: after)
    assert task.browse(phone, "好物沉浸看", 5, deadline(), before) == after
    phone.click.assert_called_once_with(1102, 1720)
    assert task._session["completed"] == 1


def test_visit_does_not_require_balance(phone, monkeypatch):
    title = "领闪购红包下单直接省"
    before = page(title=title, count=0, header=None)
    after = page(title=title, count=1, header=None)
    monkeypatch.setattr(task, "scan", lambda _: after)
    assert task.visit(phone, title, deadline(), before) == after
    phone.click.assert_called_once_with(1102, 1720)
    phone.app_install.assert_not_called()
    assert task._session["completed"] == 1


def test_balance_jump_alone_does_not_confirm_completion(phone, monkeypatch):
    unchanged = page(header="1206007")
    monkeypatch.setattr(task, "scan", lambda _: unchanged)
    with pytest.raises(RuntimeError):
        task.verify_gain(phone, unchanged, 29, (7, 10), deadline(), title="好物沉浸看")
    assert task._session["completed"] == 0


def test_changed_progress_on_wrong_page_is_not_confirmation(phone, monkeypatch):
    wrong = page(count=8)[1:]
    monkeypatch.setattr(task, "scan", lambda _: wrong)
    with pytest.raises(RuntimeError):
        task.verify_gain(phone, wrong, 29, (7, 10), deadline(), title="好物沉浸看")
    assert task._session["completed"] == 0
