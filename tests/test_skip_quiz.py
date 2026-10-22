from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from tools import taobao_energy as task


@pytest.mark.parametrize("title", ["淘金币省钱等级考试", "去答题领能量", "看看#答题活动"])
def test_quiz_titles_are_excluded_from_selection_and_manual_clicks(title):
    assert task.task_kind(title) == "skip"
    assert not task.allowed_browse(title)
    with pytest.raises(RuntimeError, match="跳过"):
        task.task_button([], title, 1264)


def test_scanner_skips_quiz_and_continues_to_browse_task(monkeypatch):
    nodes = [
        dict(text="做任务赚能量", cx=630, cy=590),
        dict(text="淘金币省钱等级考试(0/1)", cx=430, cy=1460),
        dict(text="去完成", cx=1102, cy=1492),
        dict(text="好物沉浸看(0/10)", cx=430, cy=1920),
        dict(text="去完成", cx=1102, cy=1952),
        dict(text="注：以上奖励均为最高奖励", cx=600, cy=2650),
    ]
    phone = Mock()
    phone.window_size.return_value = (1264, 2780)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "scan", lambda _: nodes)
    title, _ = task.next_task(phone, nodes, set(), datetime.now(timezone.utc) + timedelta(minutes=1))
    assert title == "好物沉浸看"
    phone.click.assert_not_called()
