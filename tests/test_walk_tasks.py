"""走路流程回归测试：提取纯逻辑，避免导入脚本时连接真实设备。"""
import ast
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def block(text, x=400, y=800):
    return {"text": text, "cx": x, "cy": y}


def walk_map(steps):
    return [block("走路赚元宝", 300, 150), block("今日已走1222", 100, 1200),
            block("现在可走", 500, 1500), block(str(steps), 500, 1570),
            block("出发", 730, 1540), block("赚步数", 980, 1600)]


def task_list(name="看视频60秒(0/10)"):
    return [block("赚步数", 500, 600), block(name), block("去完成", 950)]


def reward_popup(walked=1200):
    return [block("恭喜额外获得", 600, 700), block("奖励200步数", 600, 800),
            block("今日已走", 100, 1200), block(str(walked), 100, 1270),
            block("去领步数", 600, 1500), block("查看更多任务", 600, 1600),
            block("赚步数", 980, 1600)]


class Device:
    def __init__(self):
        self.events = []
        self.settings = {}

    def click(self, x, y):
        self.events.append(("click", x, y))

    def press(self, key):
        self.events.append(("press", key))

    def app_start(self, app, **kwargs):
        self.events.append(("start", app, kwargs))

    def swipe(self, *args):
        self.events.append(("swipe", args))

    def shell(self, args):
        self.events.append(("shell", args))


def load_walk():
    path = Path(__file__).parents[1] / "走路赚元宝.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    namespace = {"re": re, "screen_width": 1080, "screen_height": 2400,
                 "time": types.SimpleNamespace(sleep=lambda _: None),
                 "d": Device(), "DT_APP": "com.taobao.live",
                 "check_can_open": lambda _: None,
                 "report_task_found": lambda: None,
                 "report_round_finished": lambda: None,
                 "show_today_summary": lambda: None, "sys": sys}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    namespace[target.id] = value
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class WalkTasksTest(unittest.TestCase):
    def setUp(self):
        self.walk = load_walk()

    def scan_sequence(self, pages):
        iterator = iter(pages)
        self.walk["get_ocr_text_blocks"] = lambda _: next(iterator)

    def test_same_row_button_does_not_use_previous_video_title(self):
        blocks = [block("看视频60秒", y=700), block("去完成", 950, 700),
                  block("玩一次搜索并找低价", y=830), block("去完成", 950, 830)]
        tasks = self.walk["parse_tasks_from_blocks"](blocks)
        self.assertEqual([t[1:3] for t in tasks],
                         [("video", "看视频60秒"), ("search_low_price", "玩一次搜索并找低价")])

    def test_search_fragments_block_even_when_title_contains_browse(self):
        blocks = [block("浏览精选推荐", y=700), block("去完成", 950, 700),
                  block("浏览玩一次搜索", y=800), block("并找低价", y=835),
                  block("去完成", 950, 820)]
        self.assertEqual([t[2] for t in self.walk["parse_tasks_from_blocks"](blocks)],
                         ["浏览精选推荐"])

    def test_task_title_above_button_and_reward_are_handled(self):
        blocks = [block("浏览省钱专区30秒", y=760), block("额外得100步", y=795),
                  block("(0/5)", y=815), block("去完成", 950, 850)]
        self.assertEqual(self.walk["parse_tasks_from_blocks"](blocks)[0][2], "浏览省钱专区30秒")

    def test_button_without_title_is_skipped(self):
        self.assertEqual(self.walk["parse_tasks_from_blocks"]([block("去完成", 950)]), [])

    def test_four_approved_browse_tasks_are_paired_and_classified(self):
        names = ["浏览元宝商城30秒(0/1)", "浏览精选推荐60秒",
                 "浏览上新好物60秒", "浏览省钱专区60秒"]
        blocks = []
        for index, name in enumerate(names):
            y = 700 + index * 240
            blocks.extend([block(name, y=y), block("去浏览" if index == 0 else "去完成", 950, y)])
        tasks = self.walk["parse_tasks_from_blocks"](blocks)
        self.assertEqual([t[2] for t in tasks], names)
        self.assertEqual([t[1] for t in tasks], ["browse"] * 4)
        self.assertEqual([self.walk["parse_seconds"](t[2]) for t in tasks], [30, 60, 60, 60])

    def test_mall_browse_execution_uses_requested_duration(self):
        calls = []
        self.walk.update(check_can_open=lambda _: None,
                         execute_browse_task=lambda device, **kwargs: calls.append(kwargs))
        self.assertTrue(self.walk["execute_task"]("browse", "浏览元宝商城30秒(0/1)", 950, 800))
        self.assertEqual(calls, [{"min_duration": 30, "max_wait": 60}])

    def test_shenquan_browse_and_spaced_mall_title_are_allowed(self):
        for name in ("浏览神券专区60秒", "浏览 元宝商城 30秒（0/1）"):
            with self.subTest(name=name):
                tasks = self.walk["parse_tasks_from_blocks"](task_list(name))
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0][1], "browse")

    def test_mall_exception_does_not_allow_purchase_or_search_tasks(self):
        for name in ("元宝商城下单", "浏览元宝商城30秒并购买", "浏览元宝商城充值",
                     "浏览元宝商城搜索找低价"):
            with self.subTest(name=name):
                self.assertTrue(self.walk["is_blacklisted"](name))
                self.assertEqual(self.walk["parse_tasks_from_blocks"](task_list(name)), [])

    def test_real_phone_ocr_rewards_do_not_replace_titles(self):
        self.walk.update(screen_width=1264, screen_height=2780)
        blocks = [block("玩1次搜索并找低价", 444, 1266), block("去完成", 1078, 1310),
                  block("文+388找低价赢海量元宝", 472, 1354),
                  block("看视频60秒(0/10)", 416, 1501), block("去完成", 1078, 1548),
                  block("文+200", 302, 1589), block("60s", 166, 1594),
                  block("看直播60秒(0/10)", 418, 1739), block("去完成", 1078, 1782),
                  block("文+200", 302, 1823), block("随机任务", 121, 1936),
                  block("去玩1次猜价格游戏", 446, 1974), block("去完成", 1078, 2020),
                  block("文+200猜价格赢海量元宝", 473, 2060)]
        tasks = self.walk["parse_tasks_from_blocks"](blocks)
        self.assertEqual([t[1:3] for t in tasks],
                         [("video", "看视频60秒(0/10)"), ("live", "看直播60秒(0/10)"),
                          ("search_low_price", "玩1次搜索并找低价"),
                          ("guess_price", "去玩1次猜价格游戏")])

    def test_non_button_text_is_not_clicked(self):
        blocks = [block("看视频60秒"), block("去完成任务赚步数", 950)]
        self.assertEqual(self.walk["parse_tasks_from_blocks"](blocks), [])

    def test_execute_guard_blocks_search_even_with_safe_type(self):
        self.assertFalse(self.walk["execute_task"]("browse", "浏览玩一次搜索并找低价", 950, 800))
        self.assertEqual(self.walk["d"].events, [])
        self.assertEqual(self.walk["match_task_type"]("浏览玩一次搜索并找低价"), "other")

    def test_external_cash_tasks_are_blocked_before_clicking(self):
        for name in ("去同程旅行签到换现金", "去同城旅行签到换现金",
                     "去头条极速版赚现金", "浏览头条极速版赚现金(0/1)"):
            with self.subTest(name=name):
                self.assertTrue(self.walk["is_blacklisted"](name))
                self.assertEqual(self.walk["parse_tasks_from_blocks"](task_list(name)), [])
                self.assertFalse(self.walk["execute_task"]("browse", name, 950, 800))
                self.assertEqual(self.walk["d"].events, [])

    def test_search_browse_title_is_paired_without_header_or_icon(self):
        blocks = [block("随机任务", 120, 740), block("搜索宝贝后", 400, 780),
                  block("浏览45秒", 400, 815), block("Q", 120, 825),
                  block("去完成", 950, 825), block("文+150", 300, 860)]
        tasks = self.walk["parse_tasks_from_blocks"](blocks)
        self.assertEqual(tasks[0][1:3], ("search_browse", "搜索宝贝后浏览45秒"))
        for name in ("搜索宝贝后浏览45秒并购买", "搜索宝贝后浏览45秒找低价"):
            self.assertTrue(self.walk["is_blacklisted"](name))

    def search_pages(self, countdown=True):
        return [[block("搜索领步数", 350, 230), block("Q输入想买的商品", 630, 1327)],
                [block("'牙刷", 134, 1900)],
                [block("Q牙刷", 184, 391), block("搜索", 950, 390)],
                [block("滑动浏览45", 950, 1270)] if countdown else [block("搜索看更多宝贝")]]

    def setup_search_execution(self, pages):
        self.scan_sequence(pages)
        self.walk["pause_global_watcher"] = lambda _: None
        self.walk["resume_global_watcher"] = lambda _: None
        self.walk["read_search_step_balance"] = lambda: (100, [])

    def test_search_browse_rescans_moved_field_and_button_before_timer(self):
        completed = [block("赚步数", 500, 600), block("搜索宝贝后浏览45秒"), block("已完成", 950)]
        pages = self.search_pages() + [completed, completed]
        self.setup_search_execution(pages)
        calls = []
        self.walk["execute_browse_task"] = lambda _, **kw: calls.append(kw) or True
        self.assertTrue(self.walk["exec_search_browse"](950, 800, "搜索宝贝后浏览45秒"))
        self.assertEqual(self.walk["d"].events[:5], [
            ("click", 950, 800), ("click", 630, 1327),
            ("shell", ["input", "text", "yashua"]), ("click", 134, 1900), ("click", 950, 390)])
        self.assertEqual(calls, [{"min_duration": 45, "max_wait": 75}])

    def test_search_without_countdown_never_starts_browsing(self):
        self.setup_search_execution(self.search_pages(False) + [[block("空白")]] * 2)
        self.walk["execute_browse_task"] = lambda *a, **k: self.fail("不应开始计时")
        self.assertFalse(self.walk["exec_search_browse"](950, 800, "搜索宝贝后浏览45秒"))

    def test_search_still_actionable_does_not_log_completion(self):
        self.setup_search_execution(self.search_pages() + [task_list("搜索宝贝后浏览45秒")] * 2)
        self.walk["execute_browse_task"] = lambda *a, **k: True
        self.walk["log_task_completed"] = lambda *a: self.fail("不应记为完成")
        self.assertFalse(self.walk["execute_task"]("search_browse", "搜索宝贝后浏览45秒", 950, 800))

    def test_repeatable_search_success_requires_actual_step_increase(self):
        self.setup_search_execution(self.search_pages() + [task_list("搜索宝贝后浏览45秒")] * 2)
        balances = iter([(375, []), (525, [])])
        self.walk["read_search_step_balance"] = lambda: next(balances)
        self.walk["execute_browse_task"] = lambda *a, **k: True
        self.assertTrue(self.walk["exec_search_browse"](950, 800, "搜索宝贝后浏览45秒"))

    def test_missing_title_is_not_proof_of_completion(self):
        self.setup_search_execution(self.search_pages() + [task_list("看视频60秒")] * 2)
        self.walk["execute_browse_task"] = lambda *a, **k: True
        self.assertFalse(self.walk["exec_search_browse"](950, 800, "搜索宝贝后浏览45秒"))

    def test_step_balance_reopens_list_using_current_ocr(self):
        self.scan_sequence([task_list() + [block("X", 1000, 610)], walk_map(375),
                            task_list(), task_list()])
        balance, blocks = self.walk["read_search_step_balance"]()
        self.assertEqual(balance, 375)
        self.assertEqual(blocks, task_list())
        self.assertEqual(self.walk["d"].events, [("click", 1000, 610), ("click", 980, 1600)])

    def test_low_price_title_ignores_calendar_and_merges_split_lines(self):
        blocks = [block("第1天 第2天明天", y=660), block("玩1次搜索", y=730),
                  block("并找低价", y=765), block("去完成", 950, 780),
                  block("文+388找低价赢海量元宝", y=820)]
        tasks = self.walk["parse_tasks_from_blocks"](blocks)
        self.assertEqual(tasks[0][1:3], ("search_low_price", "玩1次搜索并找低价"))
        for title in ("玩1次搜索并找低价购买", "玩1次搜索并找低价分享", "搜索找低价"):
            self.assertTrue(self.walk["is_blacklisted"](title))

    def low_price_pages(self):
        return [[block("搜索商品→寻找最低价格→答对赢188元宝", y=894),
                 block("请输入想找的商品", 354, 1837)],
                [block("1牙刷", 135, 1902)],
                [block("牙刷", 218, 1066), block("找最低价", 1073, 1065)],
                [block("找找哪个商品价格最低", y=1026),
                 block("￥???", 122, 1612), block("￥???", 530, 1612)],
                [block("猜它价格最低", 631, 2518)],
                [block("恭喜完成任务，获得388步数", y=1795)], task_list()]

    def setup_low_price(self, pages, after=1301):
        self.setup_search_execution(pages)
        balances = iter([(913, task_list("玩1次搜索并找低价")), (after, task_list())])
        self.walk["read_search_step_balance"] = lambda: next(balances)
        self.walk["restore_walk_task_list"] = lambda _: True
        self.walk["close_walk_low_price"] = lambda _: True

    def test_low_price_relocates_after_keyboard_and_submits_once(self):
        self.setup_low_price(self.low_price_pages())
        self.assertTrue(self.walk["exec_search_low_price"](1, 1, "玩1次搜索并找低价"))
        self.assertEqual(self.walk["d"].events, [
            ("click", 950, 800), ("click", 354, 1837),
            ("shell", ["input", "text", "yashua"]), ("click", 135, 1902),
            ("press", "back"), ("click", 1073, 1065),
            ("click", 122, 1612), ("click", 631, 2518)])

    def test_low_price_without_game_does_not_guess(self):
        pages = self.low_price_pages()[:3] + [[block("搜索建议")]]
        self.setup_low_price(pages)
        self.assertFalse(self.walk["exec_search_low_price"](1, 1, "玩1次搜索并找低价"))
        self.assertEqual(self.walk["d"].events[-1], ("click", 1073, 1065))

    def test_low_price_no_reward_or_step_change_is_not_logged(self):
        pages = self.low_price_pages()[:-2] + [[block("还剩2次机会")], task_list()]
        self.setup_low_price(pages, after=913)
        self.walk["log_task_completed"] = lambda *a: self.fail("不能虚报完成")
        self.assertFalse(self.walk["execute_task"]("search_low_price", "玩1次搜索并找低价", 1, 1))

    def test_available_steps_ignores_today_and_milestones(self):
        blocks = walk_map(1299) + [block("20000步", 500, 300)]
        self.assertEqual(self.walk["read_available_steps"](blocks), 1299)
        self.assertEqual(self.walk["read_available_steps"]([block("现在可走1,299步")]), 1299)
        self.assertIsNone(self.walk["read_available_steps"]([block("今日已走1222")]))

    def test_navigation_reuses_home_center_walk_chain(self):
        calls = []
        scanner = types.ModuleType("u2_scanner")
        scanner.navigate_chain = lambda device, steps: calls.append(steps) or True
        self.scan_sequence([walk_map(0)])
        with patch.dict(sys.modules, {"u2_scanner": scanner}):
            self.assertTrue(self.walk["navigate_to_walk_page"](self.walk["d"]))
        self.assertEqual(calls[0], [("元宝中心", "元宝中心"), ("走路赚元宝", "走路赚元宝")])
        self.assertEqual(self.walk["d"].events[0][0], "start")

    def test_upload_then_departure_before_task_list(self):
        self.scan_sequence([walk_map(0) + [block("上传步数", 100, 1400)],
                            walk_map(1200), walk_map(0)])
        self.assertTrue(self.walk["prepare_walk_steps"]())
        self.assertEqual(self.walk["d"].events, [("click", 100, 1400), ("click", 730, 1540)])

    def test_animation_is_rescanned_without_repeated_click(self):
        self.scan_sequence([walk_map(1200), walk_map(1200), [], walk_map(0)])
        self.assertTrue(self.walk["prepare_walk_steps"]())
        self.assertEqual(self.walk["d"].events, [("click", 730, 1540)])

    def test_departure_reward_confirms_today_counter_increase(self):
        self.scan_sequence([walk_map(1200), reward_popup(2422)])
        self.assertTrue(self.walk["prepare_walk_steps"]())
        self.assertEqual(self.walk["d"].events, [("click", 730, 1540)])

    def test_reward_without_step_increase_does_not_confirm_departure(self):
        self.scan_sequence([walk_map(1200)] + [reward_popup(1222)] * 5)
        self.assertFalse(self.walk["prepare_walk_steps"]())

    def test_reward_more_tasks_does_not_click_recommended_live(self):
        self.scan_sequence([reward_popup(), task_list()])
        self.assertTrue(self.walk["open_walk_task_list"]())
        self.assertEqual(self.walk["d"].events, [("click", 600, 1600)])

    def test_reward_is_not_a_task_list_even_with_background_buttons(self):
        self.assertFalse(self.walk["is_walk_task_list"](reward_popup() + task_list()))

    def test_unchanged_steps_stop_repeated_departures(self):
        self.scan_sequence([walk_map(1200)] * 6)
        self.assertFalse(self.walk["prepare_walk_steps"]())
        self.assertEqual(self.walk["d"].events, [("click", 730, 1540)])

    def test_zero_steps_do_not_click_departure(self):
        self.scan_sequence([walk_map(0)])
        self.assertTrue(self.walk["prepare_walk_steps"]())
        self.assertEqual(self.walk["d"].events, [])

    def test_unknown_steps_do_not_click_departure(self):
        self.scan_sequence([[b for b in walk_map(0) if b["text"] != "0"]])
        self.assertFalse(self.walk["prepare_walk_steps"]())
        self.assertEqual(self.walk["d"].events, [])

    def test_task_list_opening_requires_verified_panel(self):
        self.scan_sequence([walk_map(0), task_list()])
        self.assertTrue(self.walk["open_walk_task_list"]())
        self.assertEqual(self.walk["d"].events, [("click", 980, 1600)])

    def test_wrong_landing_page_does_not_start_tasks(self):
        self.scan_sequence([walk_map(0)] + [[block("商品详情")]] * 3)
        self.assertFalse(self.walk["open_walk_task_list"]())

    def test_return_to_map_reopens_list_with_fresh_coordinates(self):
        self.scan_sequence([walk_map(0), task_list()])
        self.assertTrue(self.walk["restore_walk_task_list"]([block("商品详情")]))
        self.assertEqual(self.walk["d"].events, [("press", "back"), ("click", 980, 1600)])

    def test_main_prepares_steps_before_opening_list(self):
        events = []
        self.walk["navigate_to_walk_page"] = lambda _: events.append("navigate") or True
        self.walk["prepare_walk_steps"] = lambda: events.append("steps") or True
        self.walk["open_walk_task_list"] = lambda: events.append("list") or False
        self.walk["main"]()
        self.assertEqual(events, ["navigate", "steps", "list"])

    def test_unchanged_task_stops_after_three_attempts_and_reports_round(self):
        events = []
        self.walk.update(navigate_to_walk_page=lambda _: True, prepare_walk_steps=lambda: True,
                         open_walk_task_list=lambda: True,
                         get_ocr_text_blocks=lambda _: task_list(),
                         execute_task=lambda *args: events.append("execute") or True,
                         report_task_found=lambda: events.append("found"),
                         report_round_finished=lambda: events.append("finished"))
        self.walk["main"]()
        self.assertEqual(events.count("execute"), 3)
        self.assertEqual(events.count("found"), 3)
        self.assertEqual(events[-1], "finished")


if __name__ == "__main__":
    unittest.main()
