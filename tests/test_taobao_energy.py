import pytest

from tools.taobao_energy import allowed_browse, energy_balance, task_button, task_progress


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
