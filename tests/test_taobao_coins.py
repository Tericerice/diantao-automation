"""双十一金币面板的实测布局及导航、执行、复核回归。"""

import importlib
from unittest.mock import Mock

import pytest


@pytest.fixture
def coins(monkeypatch):
    module = importlib.import_module("淘金币任务")
    monkeypatch.setattr(module, "d", Mock())
    monkeypatch.setattr(module, "screen_width", 1264)
    monkeypatch.setattr(module, "screen_height", 2780)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    module.d.app_current.return_value = {"package": module.TB_APP}
    return module


def node(text, x=400, y=374):
    return dict(text=text, cx=x, cy=y)


def panel(*rows):
    return [node("今日速赚240淘金币"), *rows]


def live_panel():
    # 2026-10-28 真机 OCR 布局，保留标题、说明和奖励的相对位置。
    return panel(
        node("完成下方任务得额外金币", 302, 574), node("+60", 1095, 598),
        node("任务到访得金币", 410, 814), node("+10", 1104, 855),
        node("每日来任务面板", 373, 884),
        node("逛清单，每15秒30金币(0/2)", 544, 1052), node("+60", 1098, 1111),
        node("数码配件升级", 385, 1334), node("数码清单", 708, 1334),
        node("发现精选好物", 382, 1520), node("+30", 1103, 1558),
        node("浏览15秒", 316, 1591),
        node("淘金币趣味课堂", 410, 1766), node("+30", 1104, 1806),
        node("参与答题", 315, 1836),
        node("去蚂蚁庄园逛逛哟", 436, 2012), node("+50", 1103, 2052),
        node("点击去逛", 312, 2083), node("更多专享福利", 174, 2391),
        node("展开", 1100, 2546),
    )


def test_live_layout_does_not_click_bonus_or_confuse_subtitle(coins):
    tasks = coins.parse_task_list(live_panel())
    assert [(t["name"], t["type"], t["seconds"]) for t in tasks] == [
        ("任务到访得金币", "visit", 60),
        ("逛清单,每15秒30金币(0/2)", "browse", 15),
        ("发现精选好物", "browse", 15),
    ]
    assert tasks[1]["progress"] == (0, 2)


@pytest.mark.parametrize("scale", [.5, 1, 1.5])
def test_layout_scales_with_device(coins, monkeypatch, scale):
    monkeypatch.setattr(coins, "screen_width", int(1264 * scale))
    monkeypatch.setattr(coins, "screen_height", int(2780 * scale))
    nodes = [node(n["text"], int(n["cx"] * scale), int(n["cy"] * scale))
             for n in live_panel()]
    assert len(coins.parse_task_list(nodes)) == 3


@pytest.mark.parametrize("label", ["去赚淘金币", "去赚金币"])
def test_navigation_uses_both_labels_and_confirms_destination(coins, monkeypatch, label):
    read = Mock(side_effect=[
        [node("首页", y=2680)], [node("领淘金币", 250, 500)],
        [node(label, 120, 1190), node("去赚能量", 1140, 1190)], live_panel(),
    ])
    monkeypatch.setattr(coins, "read_page", read)
    assert coins.navigate_to_task_list()
    assert [call.args for call in coins.d.click.call_args_list] == [
        (400, 2680), (250, 500), (120, 1190),
    ]
    coins.d.app_start.assert_called_once_with(coins.TB_APP, stop=True)


def test_navigation_never_accepts_energy_page_as_coins(coins, monkeypatch):
    monkeypatch.setattr(coins, "read_page", Mock(side_effect=[
        [node("领淘金币", 250, 500)], [node("去赚金币", 120, 1190)],
        *[[node("做任务赚能量"), node("去完成")]] * 3,
    ]))
    assert not coins.navigate_to_task_list()
    assert not coins.parse_task_list([node("做任务赚能量"), *live_panel()])


def test_ambiguous_entry_is_not_clicked(coins, monkeypatch):
    monkeypatch.setattr(coins, "read_page", Mock(side_effect=[
        [node("领淘金币", 250, 500)],
        *[[node("去赚金币", 120, 1190), node("去赚淘金币", 500, 1500)]] * 4,
    ]))
    assert not coins.navigate_to_task_list()
    coins.d.click.assert_called_once_with(250, 500)


def test_notice_is_reread_before_clicking_entry(coins, monkeypatch):
    monkeypatch.setattr(coins, "read_page", Mock(side_effect=[
        [node("我知道了", 600, 1600), node("领淘金币", 250, 500)],
        [node("领淘金币", 260, 510)],
        [node("去赚金币", 120, 1190)], live_panel(),
    ]))
    assert coins.navigate_to_task_list()
    assert coins.d.click.call_args_list[1].args == (260, 510)


def test_merged_home_labels_are_cropped_and_relocated(coins, monkeypatch):
    recognize = Mock(side_effect=[[], [], [node("领淘金币", 110, 64)]])
    monkeypatch.setattr(coins, "_cloud_ocr", recognize)
    entry = coins.home_entry([node("领淘金币红包签到天猫超市", 730, 590)])
    assert (entry["cx"], entry["cy"]) == (530, 590)
    assert recognize.call_count == 3
    coins.d.click.assert_not_called()


def test_scrolled_home_is_restored_before_looking_for_entry(coins, monkeypatch):
    scrolled = [node("推荐", y=200), node("视频", y=2730), node("消息", y=2730),
                node("购物车", y=2730), node("我的淘宝", y=2730)]
    monkeypatch.setattr(coins, "read_page", Mock(side_effect=[
        scrolled, [node("领淘金币", 530, 590)], [node("去赚金币", 120, 1190)], live_panel(),
    ]))
    assert coins.navigate_to_task_list()
    coins.d.swipe.assert_called_once()
    coins.d.press.assert_not_called()


def test_completed_rows_and_numeric_rewards_are_not_executed(coins):
    nodes = panel(node("看直播30秒（2/2）", 400, 800), node("+50", 1100, 840),
                  node("浏览商品15秒", 400, 1200), node("500", 1100, 1240))
    assert coins.parse_task_list(nodes) == []


def test_lower_section_text_buttons_and_minutes(coins):
    nodes = panel(node("更多专享福利", 200, 800),
                  node("看视频2分钟(0/1)", 400, 1100), node("去完成", 1100, 1140))
    task, = coins.parse_task_list(nodes)
    assert task["type"] == "video"
    assert task["seconds"] == 120


def test_followed_product_browse_is_not_a_follow_action(coins):
    nodes = panel(node("更多专享福利", 200, 1600),
                  node("你关注的商品都可抵(0/1)", 504, 2018),
                  node("去完成", 1103, 2057), node("浏览15秒+30", 375, 2098))
    task, = coins.parse_task_list(nodes)
    assert task["type"] == "browse"
    assert task["seconds"] == 15
    assert coins.match_task_type("去关注主播领金币") == "skip"


def test_split_three_product_title_stays_blocked(coins):
    nodes = panel(node("查看3个", 250, 800), node("特惠卖场宝贝(0/3)", 650, 800),
                  node("+30", 1100, 840))
    assert coins.parse_task_list(nodes) == []


def test_executor_relocates_button_and_enforces_duration(coins, monkeypatch):
    before = coins.parse_task_list(live_panel())[2]
    fresh = panel(node("发现精选好物", 382, 1300), node("+30", 1103, 1340),
                  node("浏览15秒", 316, 1371))
    monkeypatch.setattr(coins, "read_page", Mock(side_effect=[fresh, [node("商品清单")]]))
    browse = Mock(return_value=True)
    monkeypatch.setattr(coins, "execute_browse_task", browse)
    assert coins.exec_task(before)
    coins.d.click.assert_called_once_with(1103, 1340)
    browse.assert_called_once_with(coins.d, min_duration=15, max_wait=120)


def test_executor_does_not_click_changed_progress(coins, monkeypatch):
    before = coins.parse_task_list(live_panel())[1]
    changed = [dict(n, text=n["text"].replace("(0/2)", "(1/2)")) for n in live_panel()]
    monkeypatch.setattr(coins, "read_page", lambda: changed)
    assert not coins.exec_task(before)
    coins.d.click.assert_not_called()


def test_external_landing_is_not_swiped(coins, monkeypatch):
    before = coins.parse_task_list(live_panel())[2]
    monkeypatch.setattr(coins, "read_page", lambda: live_panel())
    coins.d.app_current.return_value = {"package": "external.app"}
    assert not coins.exec_task(before)
    coins.d.swipe.assert_not_called()


def test_return_exhaustion_is_failure(coins, monkeypatch):
    read = Mock(return_value=[node("其他页面")])
    monkeypatch.setattr(coins, "read_page", read)
    assert not coins.back_to_task_page()
    assert read.call_count == 6
    assert coins.d.press.call_count == 5


@pytest.mark.parametrize("after,expected", [("0/2", False), ("1/2", True), ("2/2", True)])
def test_verification_requires_progress_growth(coins, monkeypatch, after, expected):
    before = coins.parse_task_list(live_panel())[1]
    nodes = [dict(n, text=n["text"].replace("0/2", after)) for n in live_panel()]
    monkeypatch.setattr(coins, "read_page", lambda: nodes)
    assert coins.verify_task(before) is expected


def test_disappeared_task_is_not_reported_complete(coins, monkeypatch):
    before = coins.parse_task_list(live_panel())[2]
    monkeypatch.setattr(coins, "read_page", lambda: panel())
    assert not coins.verify_task(before)


def test_completed_progress_is_confirmed_after_reward_button_disappears(coins, monkeypatch):
    before = coins.parse_task_list(live_panel())[1]
    monkeypatch.setattr(coins, "read_page", lambda: panel(
        node("逛清单，每15秒30金币(2/2)", 546, 1062)))
    assert coins.verify_task(before)


def test_same_row_completed_status_is_confirmed(coins, monkeypatch):
    before = coins.parse_task_list(live_panel())[2]
    monkeypatch.setattr(coins, "read_page", lambda: panel(
        node("发现精选好物", 382, 1520), node("已完成", 1103, 1558)))
    assert coins.verify_task(before)


def test_uncredited_task_is_bounded_and_not_counted(coins, monkeypatch):
    nodes = panel(node("发现精选好物", 382, 1520), node("+30", 1103, 1558))
    monkeypatch.setattr(coins, "read_page", lambda: nodes)
    execute = Mock(return_value=True)
    monkeypatch.setattr(coins, "exec_task", execute)
    monkeypatch.setattr(coins, "scroll_list", Mock())
    assert coins.run_tasks() == {"attempted": 2, "confirmed": 0}
    assert execute.call_count == 2


def test_lost_list_stops_without_further_execution(coins, monkeypatch):
    monkeypatch.setattr(coins, "read_page", Mock(side_effect=[live_panel(), *[[]] * 6]))
    execute = Mock()
    monkeypatch.setattr(coins, "exec_task", execute)
    assert coins.run_tasks() == {"attempted": 1, "confirmed": 0}
    execute.assert_called_once()


def test_stale_progress_after_confirmation_is_not_replayed(coins, monkeypatch):
    nodes = panel(node("逛清单15秒(0/2)", 400, 800), node("+60", 1100, 840))
    monkeypatch.setattr(coins, "read_page", lambda: nodes)
    execute = Mock(return_value=True)
    monkeypatch.setattr(coins, "exec_task", execute)
    monkeypatch.setattr(coins, "verify_task", lambda _: True)
    monkeypatch.setattr(coins, "scroll_list", Mock())
    assert coins.run_tasks() == {"attempted": 1, "confirmed": 1}
    execute.assert_called_once()
