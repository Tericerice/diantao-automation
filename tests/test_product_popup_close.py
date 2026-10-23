from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from PIL import Image

from tools import taobao_energy as task


def deadline():
    return datetime.now(timezone.utc) + timedelta(minutes=2)


def phone():
    d = Mock()
    d.window_size.return_value = (1264, 2780)
    d.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    d.screenshot.return_value = Image.new("RGB", (1264, 2780))
    return d


def overlay():
    return [dict(text="为你推荐好价商品", cx=540, cy=496),
            dict(text="去抢频道额外优惠", cx=633, cy=1975)]


@pytest.mark.parametrize("marker", ["为你推荐好价商品", "去抢频道额外优惠"])
def test_recommendation_popup_scans_lower_strip_for_centered_x(monkeypatch, marker):
    d = phone()
    observe = Mock(return_value=[dict(text="X", cx=632, cy=228),
                                 dict(text="X", cx=100, cy=228)])
    monkeypatch.setattr(task, "_vision_recognize", observe)
    assert task.find_popup_close(d, [dict(text=marker, cx=500, cy=500)], deadline()) == (
        632, round(2780 * .73) + 228)
    crop = observe.call_args.args[0]
    assert crop.size == (1264, round(2780 * .27))


def test_unknown_page_does_not_trigger_bottom_strip_ocr(monkeypatch):
    observe = Mock()
    monkeypatch.setattr(task, "_vision_recognize", observe)
    assert task.find_popup_close(phone(), [dict(text="×", cx=1100, cy=600)], deadline()) is None
    observe.assert_not_called()


@pytest.mark.parametrize("blocks,message", [
    ([], "未唯一"),
    ([dict(text="X", cx=100, cy=228)], "未唯一"),
    ([dict(text="X", cx=632, cy=228), dict(text="X", cx=640, cy=240)], "未唯一"),
])
def test_ambiguous_or_background_x_is_not_clicked(monkeypatch, blocks, message):
    monkeypatch.setattr(task, "_vision_recognize", Mock(return_value=blocks))
    with pytest.raises(RuntimeError, match=message):
        task.find_popup_close(phone(), overlay(), deadline())


def test_recognized_product_popup_is_clicked_then_rescanned(monkeypatch):
    d = phone()
    opened = [dict(text="做任务赚能量", cx=600, cy=590)]
    monkeypatch.setattr(task, "find_popup_close", Mock(return_value=(632, 2258)))
    monkeypatch.setattr(task, "scan", Mock(return_value=opened))
    first = True
    def find(*_):
        nonlocal first
        if first:
            first = False
            return (632, 2258)
        return None
    monkeypatch.setattr(task, "find_popup_close", find)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    assert task.close_entry_popups(d, deadline(), overlay()) == opened
    d.click.assert_called_once_with(632, 2258)


def test_home_coupon_banner_uses_x_from_its_own_row(monkeypatch):
    d = phone()
    observe = Mock(return_value=[dict(text="X", cx=1214, cy=48),
                                 dict(text="X", cx=100, cy=200)])
    monkeypatch.setattr(task, "_vision_recognize", observe)
    nodes = [dict(text="6张共1570元消费券，仅剩1天1小时", cx=461, cy=2550)]
    assert task.find_home_banner_close(d, nodes, deadline()) == (1214, 2548)
    assert observe.call_args.args[0].size == (1264, 120)


def test_coupon_banner_without_an_x_does_not_guess(monkeypatch):
    nodes = [dict(text="6张共1570元消费券，仅剩1天1小时", cx=461, cy=2550)]
    assert task.find_home_banner_close(phone(), nodes, deadline()) is None
