import contextlib
import io
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


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
        self.original_modules = {
            name: sys.modules.get(name) for name in ("u2_scanner", "utils")
        }
        self.original_sleep = __import__("time").sleep

        scanner = types.ModuleType("u2_scanner")
        scanner.DT_APP = "com.example"
        scanner.connect_device = lambda: self.fake_device
        scanner.navigate_chain = lambda *_args, **_kwargs: True

        utils = types.ModuleType("utils")
        utils.get_ocr_text_blocks = lambda _device: self.ocr_pages.pop(0)

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
        self.assertTrue(result)
        self.assertEqual(self.fake_device.clicks, [(146, 766), (631, 1790)])
        self.assertEqual(self.fake_device.presses, ["back"])

    def test_gray_tier_stops_without_extra_click(self):
        module = self.load()
        self.ocr_pages = [walk_page("100步")]
        result = module["claim_tier"](block("2500步", 354, 878))
        self.assertFalse(result)
        self.assertEqual(self.fake_device.clicks, [(354, 878)])

    def test_task_is_registered_in_dashboard(self):
        from workbench.tasks import TASKS
        task = TASKS["diantao-walk-sphere"]
        self.assertEqual(task["name"], "走路球体完成")
        self.assertEqual(task["script"], "走路球体完成.py")
        self.assertTrue(task["requires_ocr"])


if __name__ == "__main__":
    unittest.main()
