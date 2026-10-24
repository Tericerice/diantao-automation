import pytest

from tools.taobao_energy import allowed_browse, task_row_progress, task_button, task_progress, task_kind


def page(title="好物随心逛(0/10)"):
    return [dict(text="做任务赚能量", cx=600, cy=590),
            dict(text=title, cx=430, cy=1460),
            dict(text="去完成", cx=1102, cy=1492),
            dict(text="去完成", cx=1102, cy=1722)]


def test_selects_same_row_even_after_task_reorders():
    assert task_button(page(), "好物随心逛", 1264)["cy"] == 1492


@pytest.mark.parametrize("title", ["好物随心逛(10/10)", "好物随心逛（10/10)"])
def test_progress_text_does_not_hide_live_action_button(title):
    assert task_button(page(title), "好物随心逛", 1264)["cy"] == 1492


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


def test_row_progress_matches_exact_task_not_similar_title():
    nodes = page("好物随心逛加倍(3/10)") + [dict(text="好物随心逛(1/10)", cx=400, cy=900)]
    assert task_row_progress(nodes, "好物随心逛") == (1, 10)
    assert task_row_progress(page("好物随心逛（2/10)"), "好物随心逛") == (2, 10)
    assert task_row_progress(page("好物随心逛"), "好物随心逛") is None


def test_ambiguous_task_progress_is_not_used():
    assert task_row_progress(page() + page(), "好物随心逛") is None


@pytest.mark.parametrize("title,kind", [
    ("领闪购红包下单直接省", "taobao"),
    ("看淘宝视频领红包", "taobao"),
    ("去芭芭农场领水果", "taobao"),
    ("去蚂蚁森林收能量", "alipay"),
    ("逛一逛蚂蚁庄园", "alipay"),
    ("逛一逛支付宝农场", "alipay"),
    ("搜一搜你喜欢的宝贝", "taobao"),
    ("拍立淘逛感兴趣的宝贝", "taobao"),
    ("淘金币省钱等级考试", "skip"),
    ("去组队可加快升级", "taobao"),
    ("你关注的商品都可抵", "taobao"),
    ("逛一逛领购物红包", "external"),
    ("去百度极速版领现金", "external"),
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


def test_pending_action_is_allowed_when_cumulative_progress_is_capped(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    ready = page("好物随心逛(1/10)") + [dict(text="50/50", cx=120, cy=846)]
    phone = type("Phone", (), {"window_size": lambda self: (1264, 2780)})()
    assert task.next_task(
        phone, ready, set(),
        datetime.now(timezone.utc) + timedelta(minutes=1),
    )[0] == "好物随心逛"


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
    d.app_start.side_effect = lambda *args, **kwargs: setattr(
        d.app_current, "return_value", dict(package=task.TB)
    )
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "scan", lambda _: nodes)
    task.visit(d, "去百度App领现金", datetime.now(timezone.utc)+timedelta(minutes=1), nodes)
    d.click.assert_called_once_with(1102, 1492)
    if current == task.TB:
        d.press.assert_not_called()
    else:
        d.app_start.assert_called_once_with(task.TB, use_monkey=True)
    d.app_install.assert_not_called()


def test_visible_task_selection_never_scrolls(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    nodes = page("去蚂蚁森林收能量(0/1)") + [dict(text="50/50", cx=120, cy=846)]
    d = MagicMock()
    d.window_size.return_value = (1264, 2780)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    scan = MagicMock()
    monkeypatch.setattr(task, "scan", scan)
    title, selected = task.next_task(
        d, nodes, set(), datetime.now(timezone.utc) + timedelta(minutes=1)
    )
    assert title == "去蚂蚁森林收能量"
    assert selected is nodes
    d.click.assert_not_called()
    d.swipe.assert_not_called()
    scan.assert_not_called()


def test_visible_taobao_task_precedes_visible_alipay_task():
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    nodes = [
        dict(text="做任务赚能量", cx=630, cy=590),
        dict(text="去蚂蚁森林收能量(0/1)", cx=430, cy=1460),
        dict(text="去完成", cx=1102, cy=1492),
        dict(text="看淘宝视频领红包(0/1)", cx=430, cy=1700),
        dict(text="去完成", cx=1102, cy=1732),
    ]
    d = MagicMock()
    d.window_size.return_value = (1264, 2780)
    title, selected = task.next_task(
        d, nodes, set(), datetime.now(timezone.utc) + timedelta(minutes=1)
    )
    assert title == "看淘宝视频领红包"
    assert selected is nodes
    d.swipe.assert_not_called()


def test_no_visible_eligible_task_ends_without_scrolling():
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    nodes = page("天猫积分换能量(0/1)") + [
        dict(text="淘金币省钱等级考试(0/1)", cx=430, cy=1800),
        dict(text="去完成", cx=1102, cy=1832),
    ]
    d = MagicMock()
    d.window_size.return_value = (1264, 2780)
    title, selected = task.next_task(
        d, nodes, set(), datetime.now(timezone.utc) + timedelta(minutes=1)
    )
    assert title is None
    assert selected is nodes
    d.swipe.assert_not_called()


@pytest.mark.parametrize("label", ["赚能量", "賺能量", "去赚能量", "去賺能量"])
def test_enter_accepts_cloud_ocr_earn_button_variant(monkeypatch, label):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    nodes = [dict(text="淘金币双11狂享20亿", cx=506, cy=216),
             dict(text=label, cx=1154, cy=1177)]
    opened = page()
    d = MagicMock()
    d.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    scans = iter([nodes, opened])
    monkeypatch.setattr(task, "scan", lambda _: next(scans))
    assert task.enter(d, datetime.now(timezone.utc)+timedelta(minutes=1)) == opened
    d.click.assert_called_once_with(1154, 1177)


def test_enter_rejects_ambiguous_earn_button_variants(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    nodes = [dict(text="淘金币双11狂享20亿", cx=506, cy=216),
             dict(text="赚能量", cx=1154, cy=1177),
             dict(text="賺能量", cx=1154, cy=1300)]
    d = MagicMock()
    d.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    monkeypatch.setattr(task, "scan", lambda _: nodes)
    with pytest.raises(RuntimeError, match="未唯一"):
        task.enter(d, datetime.now(timezone.utc)+timedelta(minutes=1))
    d.click.assert_not_called()


@pytest.mark.parametrize("selector_kind", ["text", "description"])
def test_home_entry_closes_known_logistics_prompt_and_supports_both_labels(
    monkeypatch, selector_kind
):
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    from tools import taobao_energy as task

    controls = {}
    dismissed = False

    def select(**query):
        nonlocal dismissed
        key = tuple(query.items())
        if key not in controls:
            control = MagicMock()
            control.count = 1
            if query == {"text": "取消"}:
                def close():
                    nonlocal dismissed
                    dismissed = True
                control.click.side_effect = close
            controls[key] = control
        controls[key].exists = query == {selector_kind: "领淘金币"} or (
            not dismissed and query in [
                {"text": "开启快递物流提醒"}, {"text": "去授权"}, {"text": "取消"},
            ]
        )
        return controls[key]

    d = MagicMock(side_effect=select)
    d.app_current.return_value = dict(package=task.TB, activity="TBMainActivity")
    header = [dict(text="淘金币双11狂享20亿", cx=500, cy=210),
              dict(text="赚能量", cx=1154, cy=1177)]
    scans = iter([header, page()])
    monkeypatch.setattr(task, "scan", lambda _: next(scans))
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    assert task.enter(d, datetime.now(timezone.utc) + timedelta(minutes=1)) == page()
    controls[(("text", "取消"),)].click.assert_called_once()
    controls[((selector_kind, "领淘金币"),)].click.assert_called_once()
    select(text="去授权").click.assert_not_called()
    d.click.assert_called_once_with(1154, 1177)


def test_revised_event_without_old_heading_opens_only_earn_energy(monkeypatch):
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    from tools import taobao_energy as task

    d = MagicMock()
    d.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    nodes = [dict(text="升级赛车拿钱", cx=636, cy=1109),
             dict(text="去赚能量", cx=1144, cy=1187)]
    scans = iter([nodes, page()])
    monkeypatch.setattr(task, "scan", lambda _: next(scans))
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    assert task.enter(d, datetime.now(timezone.utc) + timedelta(minutes=1)) == page()
    d.click.assert_called_once_with(1144, 1187)


def test_restart_closes_home_coupon_popup_before_entering_event(monkeypatch):
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    from tools import taobao_energy as task

    popup = [dict(text="6张消费券共", cx=630, cy=1098),
             dict(text="关闭按钮", cx=631, cy=2148)]
    opened = page()
    d = MagicMock()
    d.app_current.return_value = dict(package=task.TB, activity="TBMainActivity")
    entry = MagicMock()
    entry.exists = True
    d.side_effect = lambda **query: (
        entry if query.get("text") == "领淘金币" else MagicMock(exists=False)
    )
    scans = iter([popup, opened])
    monkeypatch.setattr(task, "scan", lambda _: next(scans))
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    assert task.enter(
        d, datetime.now(timezone.utc) + timedelta(minutes=1), restart=True
    ) == opened
    d.app_start.assert_called_once_with(task.TB, stop=True, use_monkey=True)
    d.click.assert_called_once_with(631, 2148)
    entry.click.assert_called_once()


def test_manual_launch_deadline_is_relative_to_current_start():
    from tools.taobao_energy import run_deadline
    from datetime import datetime, timedelta
    # 回归：历史截止日期之后也能正常手动启动，跨日运行仍有明确上限。
    now = datetime.fromisoformat("2026-10-19T23:30:00+08:00")
    assert run_deadline(None, 60, now) == now + timedelta(hours=1)
    assert run_deadline("2026-10-20T00:00:00+08:00", 60, now).hour == 0


@pytest.mark.parametrize("value,minutes", [
    ("2026-10-19T00:00:00+08:00", 60),
    ("2026-10-20T00:00:00", 60),
    ("invalid", 60),
    (None, 0),
    (None, -1),
])
def test_invalid_runtime_options_are_rejected(value, minutes):
    from tools.taobao_energy import run_deadline
    from datetime import datetime
    with pytest.raises(ValueError):
        run_deadline(value, minutes, datetime.fromisoformat("2026-10-19T18:00:00+08:00"))


def test_console_is_concise_and_error_details_stay_in_file(tmp_path, monkeypatch, capsys):
    from tools import taobao_energy as task
    monkeypatch.setattr(task, "_raw_scan", False)
    path = task.setup_logging(tmp_path)
    try:
        task.LOG.debug('屏幕识别 {"blocks": [{"text": "OCR详情"}]}')
        task.LOG.info("[任务] 1/30 | 支付宝 | 去蚂蚁森林收能量")
        task._session.update(initial=32900, balance=33300, completed=1)
        def failed_main():
            raise RuntimeError("当前不是赚能量任务列表")
        monkeypatch.setattr(task, "main", failed_main)
        assert task.cli() == 1
        output = capsys.readouterr().out
        assert "[任务] 1/30 | 支付宝" in output
        assert "[停止] 当前不是赚能量任务列表" in output
        assert "完成 1 项，耗时" in output
        assert "余额" not in output
        assert "能量 +" not in output
        assert "Traceback" not in output
        assert "OCR详情" not in output
        detail = path.read_text(encoding="utf-8")
        assert "OCR详情" in detail
        assert "Traceback" in detail
        assert "RuntimeError" in detail
    finally:
        for handler in task.LOG.handlers[:]:
            task.LOG.removeHandler(handler)
            handler.close()
        task._session.clear()


def test_visit_title_in_reward_description_is_not_a_second_task():
    nodes = page("逛一逛蚂蚁庄园(0/1)") + [dict(text="逛一逛蚂蚁庄园+600", cx=430, cy=1524)]
    assert task_button(nodes, "逛一逛蚂蚁庄园", 1264)["cy"] == 1492


def test_row_title_ignores_icon_text_on_the_same_baseline():
    # 实测 OCR: 图标文字(“闲鱼”)与“去完成”同一水平线，且比标题更靠右。
    nodes = [
        dict(text="做任务赚能量", cx=631, cy=590),
        dict(text="去闲鱼签到省钱(0/1)", cx=468, cy=1225),
        dict(text="闲鱼", cx=174, cy=1294),
        dict(text="点击去逛+600", cx=390, cy=1294),
        dict(text="去完成", cx=1102, cy=1258),
        dict(text="去一淘签到领现金(0/1)", cx=495, cy=1914),
        dict(text="去完成", cx=1102, cy=1950),
    ]
    from tools import taobao_energy as task
    rows = task.task_rows(nodes, 1264)
    assert [row["text"] for row, _ in rows] == ["去闲鱼签到省钱(0/1)", "去一淘签到领现金(0/1)"]
    assert task.next_task(
        type("Phone", (), {"window_size": lambda self: (1264, 2780)})(),
        nodes, set(), __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc) + __import__("datetime").timedelta(minutes=1),
    )[0] == "去闲鱼签到省钱"


def test_etao_landing_page_opens_app_instead_of_download():
    from tools import taobao_energy as task
    nodes = [
        dict(text="正在跳转", cx=284, cy=220),
        dict(text="一淘", cx=636, cy=802),
        dict(text="打开一淘", cx=632, cy=2049),
        dict(text="下载一淘", cx=634, cy=2268),
    ]
    assert task.landing_open_button(nodes, "com.taobao.etao") == dict(
        text="打开一淘", cx=632, cy=2049)
    assert task.landing_open_button(nodes, "com.taobao.idlefish") is None
    assert task.landing_open_button(nodes, "com.taobao.taobao") is None


def test_landing_page_is_absent_without_redirect_marker():
    from tools import taobao_energy as task
    nodes = [dict(text="打开一淘", cx=632, cy=2049)]
    assert task.landing_open_button(nodes, "com.taobao.etao") is None


def test_etao_visit_clicks_open_etao_on_taobao_landing_page(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    title = "去一淘签到领现金"
    nodes = [dict(text="做任务赚能量", cx=631, cy=590),
             dict(text="去一淘签到领现金(0/1)", cx=495, cy=1914),
             dict(text="去完成", cx=1102, cy=1950)]
    landing = [dict(text="正在跳转", cx=284, cy=220),
               dict(text="一淘", cx=636, cy=802),
               dict(text="打开一淘", cx=632, cy=2049),
               dict(text="下载一淘", cx=634, cy=2268)]
    d = MagicMock()
    d.window_size.return_value = (1264, 2780)
    d.adb_device.shell.return_value = "package:installed"
    d.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    clicks = []

    def click(x, y):
        clicks.append((x, y))
        if (x, y) == (632, 2049):
            d.app_current.return_value = dict(package="com.taobao.etao")
    d.click.side_effect = click
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "scan", lambda _: landing)
    monkeypatch.setattr(task, "return_from_visit", lambda *_: nodes)
    monkeypatch.setattr(task, "_session", {})
    task.visit(d, title, datetime.now(timezone.utc) + timedelta(minutes=2), nodes)
    assert (632, 2049) in clicks
    assert (634, 2268) not in clicks
    assert clicks[0] == (1102, 1950)


def test_only_verified_photo_browse_is_allowed():
    assert allowed_browse("拍立淘逛感兴趣的宝贝")
    assert task_button(page("拍立淘逛感兴趣的宝贝(0/5)"), "拍立淘逛感兴趣的宝贝", 1264)
    assert not allowed_browse("拍立淘上传照片")
    assert task_kind("拍立淘上传照片") == "skip"


def test_pending_task_row_is_not_counted_as_finished(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    ready = page("好物随心逛(1/10)")
    d = MagicMock()
    d.window_size.return_value = (1264, 2780)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "scan", lambda _: ready)
    monkeypatch.setattr(task, "_session", {})
    assert task.verify_gain(d, ready, None, (0, 10),
                            datetime.now(timezone.utc)+timedelta(minutes=1), title="好物随心逛") == ready
    assert task._session.get("completed", 0) == 0


def test_five_second_label_does_not_shorten_fifteen_second_task():
    from tools.taobao_energy import browse_seconds
    nodes = page("你关注的商品都可抵(0/1)") + [
        dict(text="浏览15秒+400", cx=390, cy=1524),
        dict(text="浏览5秒+400", cx=390, cy=1754)]
    assert browse_seconds(nodes, "你关注的商品都可抵", 25) == 17


def test_search_returns_through_keyboard_and_search_page(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    d = MagicMock()
    d.app_current.return_value = dict(package=task.TB, activity="com.taobao.search.SearchActivity")
    scans = iter([[dict(text="搜索发现", cx=146, cy=792)],
                  [dict(text="历史搜索", cx=146, cy=390)], page()])
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "scan", lambda _: next(scans))
    assert task.return_from_browse(d, datetime.now(timezone.utc)+timedelta(minutes=1)) == page()
    assert d.press.call_count == 3


def test_external_visit_returns_immediately_when_target_opens(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    nodes = page("去快手打卡领手机(0/1)") + [dict(text="50/50", cx=120, cy=846),
                                             dict(text="63000", cx=210, cy=343)]
    ready = nodes + []
    ready[1] = dict(text="去快手打卡领手机(1/1)", cx=430, cy=1460)
    d = MagicMock()
    d.window_size.return_value = (1264, 2780)
    d.adb_device.shell.return_value = "package:installed"
    d.app_current.return_value = dict(package="com.kuaishou.nebula")
    d.app_start.side_effect = lambda *args, **kwargs: setattr(
        d.app_current, "return_value", dict(package=task.TB)
    )
    waits = []
    monkeypatch.setattr(task.time, "sleep", waits.append)
    monkeypatch.setattr(task, "scan", lambda _: ready)
    monkeypatch.setattr(task, "_session", {})
    task.visit(d, "去快手打卡领手机", datetime.now(timezone.utc)+timedelta(minutes=1), nodes)
    assert waits == [1, 4, 2, 3, 3]
    d.app_start.assert_called_once_with(task.TB, use_monkey=True)


def test_quiz_is_skipped_before_entering_question_page(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    nodes = page(task.QUIZ+"(0/1)") + [dict(text="53800", cx=210, cy=343)]
    d = MagicMock()
    d.window_size.return_value = (1264, 2780)
    d.app_current.return_value = dict(package=task.TB)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "scan", lambda _: [dict(text="另一道题", cx=500, cy=700)])
    with pytest.raises(RuntimeError, match="跳过"):
        task.quiz(d, datetime.now(timezone.utc)+timedelta(minutes=1), nodes)
    d.click.assert_not_called()


def test_known_quiz_is_also_skipped_without_submitting(monkeypatch):
    from tools import taobao_energy as task
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock
    nodes = page(task.QUIZ+"(0/1)") + [dict(text="53800", cx=210, cy=343)]
    question = [dict(text="1.进入比赛期后，想继续追赶对手，哪项操作最有效？", cx=600, cy=745),
                dict(text="A 及时邀请好友助力", cx=314, cy=1018)]
    ready = page(task.QUIZ+"(1/1)")
    scans = iter([question, question+[dict(text="我选好了", cx=630, cy=2659)],
                  [dict(text="回答正确", cx=500, cy=1000)], ready])
    d = MagicMock()
    d.window_size.return_value = (1264, 2780)
    d.app_current.return_value = dict(package=task.TB)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "scan", lambda _: next(scans))
    monkeypatch.setattr(task, "_session", {})
    with pytest.raises(RuntimeError, match="跳过"):
        task.quiz(d, datetime.now(timezone.utc)+timedelta(minutes=1), nodes)
    d.click.assert_not_called()
