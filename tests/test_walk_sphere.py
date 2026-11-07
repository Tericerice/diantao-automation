import contextlib
import io
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock


class _FakeDevice:
    def __init__(self):
        self.clicks = []
        self.presses = []

    def window_size(self):
        return 1080, 2400

    def click(self, x, y):
        self.clicks.append((x, y))

    def press(self, key):
        self.presses.append(key)

    def app_start(self, _app, stop=False):
        return None


def block(value, x, y):
    return dict(text=value, cx=x, cy=y)


def walk_page(*tiers):
    return [block("走路赚元宝", 320, 223), block("今日已走", 111, 1457),
            *[block(t, 100 + i * 80, 700 + i * 40) for i, t in enumerate(tiers)]]


def popup_page():
    return [block("领取走路奖励", 633, 924), block("获得188元宝", 628, 1046),
            block("再得68元宝", 631, 1790), block("放弃领取额外奖励", 633, 1942)]


def task_page():
    return [block("浏览27秒后完成", 1119, 1164)]


class WalkSphereTest(unittest.TestCase):
    def setUp(self):
        self.fake_device = _FakeDevice()
        self.ocr_pages = []
        self.navigation_calls = 0
        self.original_modules = {
            name: sys.modules.get(name) for name in ("u2_scanner", "utils")
        }
        self.original_sleep = __import__("time").sleep

        scanner = types.ModuleType("u2_scanner")
        scanner.DT_APP = "com.example"
        scanner.connect_device = lambda: self.fake_device
        scanner.navigate_chain = lambda *_args, **_kwargs: True
        scanner.classify_media_page = lambda _blocks: None
        scanner.execute_browse_task = lambda *_args, **_kwargs: True
        scanner.execute_live_task = lambda *_args, **_kwargs: None

        utils = types.ModuleType("utils")
        utils.get_ocr_text_blocks = lambda _device: (
            self.ocr_pages.pop(0) if self.ocr_pages else []
        )

        sys.modules["u2_scanner"] = scanner
        sys.modules["utils"] = utils

    def tearDown(self):
        __import__("time").sleep = self.original_sleep
        for name, module in self.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def load(self):
        path = Path(__file__).resolve().parents[1] / "走路球体完成.py"
        with contextlib.redirect_stdout(io.StringIO()):
            module = runpy.run_path(str(path))
        module["time"].sleep = lambda _seconds: None
        return module

    def load_navigation(self):
        path = Path(__file__).resolve().parents[1] / "走路球体完成.py"
        namespace = {}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        namespace["time"].sleep = lambda _seconds: None
        return namespace

    def test_scan_tiers_sorts_and_ignores_non_tiers(self):
        module = self.load()
        tiers = module["scan_tiers"]([
            block("5000步", 1, 1), block("今日已走", 2, 2),
            block("100步", 3, 3), block("2500步", 4, 4),
        ])
        self.assertEqual([steps for steps, _ in tiers], [100, 2500, 5000])

    def test_walk_page_and_popup_detection(self):
        module = self.load()
        self.assertTrue(module["is_walk_page"](walk_page("100步", "500步")))
        self.assertFalse(module["is_walk_page"]([block("元宝中心", 1, 1)]))
        self.assertTrue(module["popup_visible"](popup_page()))
        self.assertFalse(module["popup_visible"](walk_page("100步")))

    def test_extra_button_and_browse_seconds(self):
        module = self.load()
        extra = module["find_extra_button"](popup_page())
        self.assertEqual(extra["text"], "再得68元宝")
        self.assertEqual(module["browse_seconds"](task_page()), 27)
        self.assertEqual(module["browse_seconds"]([block("没有倒计时", 1, 1)]), 35)

    def test_claim_tier_clicks_extra_then_returns(self):
        module = self.load()
        self.ocr_pages = [popup_page(), task_page(), walk_page("500步")]
        result = module["claim_tier"](block("100步", 146, 766))
        self.assertEqual(result, "claimed")
        self.assertEqual(self.fake_device.clicks, [(146, 766), (631, 1790)])
        self.assertEqual(self.fake_device.presses, ["back"])

    def test_gray_tier_stops_without_extra_click(self):
        module = self.load()
        self.ocr_pages = [walk_page("100步")]
        result = module["claim_tier"](block("2500步", 354, 878))
        self.assertEqual(result, "unavailable")
        self.assertEqual(self.fake_device.clicks, [(354, 878)])

    def test_live_page_uses_live_executor(self):
        scanner = sys.modules["u2_scanner"]
        scanner.classify_media_page = lambda _blocks: "live"
        scanner.execute_live_task = Mock()
        module = self.load()
        self.ocr_pages = [popup_page(), task_page(), walk_page("500步")]
        result = module["claim_tier"](block("100步", 146, 766))
        self.assertEqual(result, "claimed")
        scanner.execute_live_task.assert_called_once()

    def test_task_is_registered_in_dashboard(self):
        from workbench.tasks import TASKS
        task = TASKS["diantao-walk-sphere"]
        self.assertEqual(task["name"], "走路球体完成")
        self.assertEqual(task["script"], "走路球体完成.py")
        self.assertTrue(task["requires_ocr"])

    def test_empty_ocr_after_tier_click_is_unknown(self):
        module = self.load()
        self.ocr_pages = [[]]
        self.assertEqual(module["claim_tier"](block("100步", 146, 766)), "unknown")

    def test_foreign_page_after_tier_click_is_unknown(self):
        module = self.load()
        self.ocr_pages = [[block("恭喜完成任务", 111, 222)]]
        self.assertEqual(module["claim_tier"](block("100步", 146, 766)), "unknown")

    def test_browse_timeout_is_bounded_failure(self):
        sys.modules["u2_scanner"].execute_browse_task = lambda *_a, **_k: False
        module = self.load()
        self.ocr_pages = [popup_page(), task_page()]
        self.assertEqual(module["claim_tier"](block("100步", 146, 766)), "failed")

    def test_unknown_after_reward_uses_bounded_navigation_recovery(self):
        module = self.load_navigation()
        calls = {"count": 0}

        def recover():
            calls["count"] += 1
            self.ocr_pages.clear()
            self.ocr_pages.append(walk_page("500步"))
            return True

        module["navigate_to_walk_page"] = recover
        module["return_to_walk_page"] = lambda: False
        self.ocr_pages = [popup_page(), task_page(), walk_page("500步"),
                          [], [], []]
        result = module["claim_tier"](block("100步", 146, 766))
        self.assertEqual(result, "claimed")
        self.assertEqual(calls["count"], 1)

    def test_unrecoverable_return_is_unknown_not_false_success(self):
        module = self.load_navigation()
        module["navigate_to_walk_page"] = lambda: False
        module["return_to_walk_page"] = lambda: False
        self.ocr_pages = [popup_page(), task_page(), walk_page("500步"),
                          [], [], []]
        self.assertEqual(module["claim_tier"](block("100步", 146, 766)), "unknown")

    def test_main_returns_error_code_for_unknown_navigation(self):
        module = self.load_navigation()
        module["navigate_to_walk_page"] = lambda: False
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = module["main"]()
        self.assertEqual(code, 1)
        self.assertIn("无法进入走路赚元宝页面", output.getvalue())

    def test_main_accepts_confirmed_page_without_tiers(self):
        module = self.load_navigation()
        module["navigate_to_walk_page"] = lambda: True
        module["get_ocr_text_blocks"] = lambda _device: walk_page()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = module["main"]()
        self.assertEqual(code, 0)
        self.assertIn("没有更多可点击档位", output.getvalue())

    def test_main_stops_with_reason_on_unknown_ocr(self):
        module = self.load_navigation()
        module["navigate_to_walk_page"] = lambda: True
        module["get_ocr_text_blocks"] = lambda _device: []
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = module["main"]()
        self.assertEqual(code, 1)
        self.assertIn("走路页/档位识别未知", output.getvalue())
        self.assertIn("导航恢复后仍未确认", output.getvalue())

    def test_normal_tier_then_next_tier(self):
        module = self.load_navigation()
        module["navigate_to_walk_page"] = lambda: True
        module["return_to_walk_page"] = lambda: True
        pages = [
            walk_page("100步", "200步"),
            popup_page(), task_page(),
            walk_page("200步"),
            walk_page("200步"),
            walk_page(),
            walk_page(),
        ]
        module["get_ocr_text_blocks"] = lambda _device: (
            pages.pop(0) if pages else walk_page()
        )
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = module["main"]()
        self.assertEqual(code, 0)
        self.assertIn("共处理 1 个走路档位", output.getvalue())
        self.assertIn("点击档位【200步】", output.getvalue())


if __name__ == "__main__":
    unittest.main()
