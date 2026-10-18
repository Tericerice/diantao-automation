import pytest

from tools.taobao_energy import allowed_browse, energy_balance, task_button, task_progress, task_kind


def page(title="好物随心逛(0/10)"):
    return [dict(text="做任务赚能量", cx=600, cy=590),
            dict(text=title, cx=430, cy=1460),
            dict(text="去完成", cx=1102, cy=1492),
            dict(text="去完成", cx=1102, cy=1722)]


def test_selects_same_row_even_after_task_reorders():
    assert task_button(page(), "好物随心逛", 1264)["cy"] == 1492


@pytest.mark.parametrize("title", ["好物随心逛(10/10)", "好物随心逛（10/10)"])
def test_finished_task_is_not_reopened(title):
    with pytest.raises(RuntimeError, match="已经完成"):
        task_button(page(title), "好物随心逛", 1264)


@pytest.mark.parametrize("title", ["天猫积分换能量", "玩趣味小游戏", "升级赛车拿钱", "拍立淘"])
def test_user_exclusions(title):
    with pytest.raises(RuntimeError, match="跳过"):
        task_button(page(title), title, 1264)


def test_wrong_page_does_not_click():
    with pytest.raises(RuntimeError, match="不是赚能量"):
        task_button(page()[1:], "好物随心逛", 1264)


def test_ambiguous_button_does_not_click():
    nodes = page() + [dict(text="去完成", cx=1100, cy=1500)]
    with pytest.raises(RuntimeError, match="按钮未唯一"):
        task_button(nodes, "好物随心逛", 1264)


def test_progress_uses_cumulative_counter_not_task_counter():
    nodes = [dict(text="10/50", cx=109, cy=846),
             dict(text="40/50", cx=500, cy=1700)]
    assert task_progress(nodes) == 10
    assert task_progress(page()) is None


def test_dynamic_free_topic_is_allowed_but_spending_is_not():
    assert allowed_browse("看看#安克")
    assert allowed_browse("搜一搜你心仪的宝贝")
    assert not allowed_browse("看看#天猫积分换能量")
    assert not allowed_browse("未知任务")


def test_energy_balance_ignores_prices_and_car_level():
    nodes = [dict(text="￥0.72", cx=200, cy=370),
             dict(text="11500>", cx=212, cy=343),
             dict(text="200", cx=122, cy=461)]
    assert energy_balance(nodes) == 11500


@pytest.mark.parametrize("title,kind", [
    ("领闪购红包下单直接省", "taobao"),
    ("看淘宝视频领红包", "taobao"),
    ("去芭芭农场领水果", "taobao"),
    ("去蚂蚁森林收能量", "alipay"),
    ("逛一逛支付宝金豆夺宝", "alipay"),
    ("去百度App领现金", "external"),
    ("去淘宝特价版0元购", "external"),
    ("天猫积分换能量", "skip"),
    ("预约组队开赛提醒", "skip"),
])
def test_task_tiers_and_exclusions(title, kind):
    assert task_kind(title) == kind


def test_free_flash_visit_does_not_allow_purchase_tasks():
    assert task_button(page("领闪购红包下单直接省(0/1)"), "领闪购红包下单直接省", 1264)
    with pytest.raises(RuntimeError, match="跳过"):
        task_button(page("下单购买商品"), "下单购买商品", 1264)


def test_animation_is_reread_and_capped_rewards_use_balance(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    ready = page() + [dict(text="50/50", cx=120, cy=846), dict(text="33300", cx=210, cy=343)]
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "scan", lambda _: ready)
    assert task.verify_gain(object(), [], 50, 32900, datetime.now(timezone.utc)+timedelta(minutes=1)) == ready


@pytest.mark.parametrize("current", ["com.taobao.taobao", "com.android.launcher", "com.heytap.quicksearchbox"])
def test_missing_app_visits_landing_then_returns_without_downloading(monkeypatch, current):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    nodes = page("去百度App领现金(0/1)") + [dict(text="50/50", cx=120, cy=846),
                                              dict(text="33300", cx=210, cy=343)]
    d = MagicMock()
    d.window_size.return_value = (1264, 2780)
    d.adb_device.shell.return_value = ""
    d.app_current.return_value = dict(package=current)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "scan", lambda _: nodes)
    task.visit(d, "去百度App领现金", datetime.now(timezone.utc)+timedelta(minutes=1), nodes)
    d.click.assert_called_once_with(1102, 1492)
    if current == task.TB:
        d.press.assert_called_once_with("back")
    else:
        d.app_start.assert_called_once_with(task.TB)
    d.app_install.assert_not_called()


def test_taobao_on_lower_page_precedes_alipay_on_first_page(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    top = page("去蚂蚁森林收能量(0/1)") + [dict(text="50/50", cx=120, cy=846)]
    lower = page("看淘宝视频领红包(0/1)") + [dict(text="注：以上奖励均为最高奖励", cx=600, cy=2650)]
    scans = iter([lower, top, lower])
    d = MagicMock()
    d.window_size.return_value = (1264, 2780)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "scan", lambda _: next(scans))
    title, nodes = task.next_task(d, top, set(), datetime.now(timezone.utc)+timedelta(minutes=1))
    assert title == "看淘宝视频领红包"
    assert task.task_progress(nodes) == 50
    d.click.assert_not_called()
