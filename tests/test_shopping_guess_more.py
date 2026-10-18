import contextlib
import io
import runpy
import sys
import types
import unittest
import time
from pathlib import Path


class _FakeSelector:
    def exists(self, timeout=0):
        return False

    def click(self):
        return None


class _FakeDevice:
    def __init__(self):
        self.clicks = []
        self.presses = []
        self.started_apps = []

    def window_size(self):
        return 1080, 2400

    def __call__(self, **_kwargs):
        return _FakeSelector()

    def app_start(self, app_name, stop=False):
        self.started_apps.append((app_name, stop))

    def click(self, x, y):
        self.clicks.append((x, y))

    def press(self, key):
        self.presses.append(key)


class ShoppingGuessMoreTest(unittest.TestCase):
    def setUp(self):
        self.original_sleep = time.sleep
        self.fake_device = _FakeDevice()
        self.ocr_blocks = [
            {"text": "去完成", "cx": 900, "cy": 1200},
            {"text": "查看更多", "cx": 540, "cy": 2100},
        ]
        self.blacklisted_names = set()
        self.original_modules = {
            name: sys.modules.get(name)
            for name in ("uiautomator2", "u2_scanner", "utils")
        }

        u2_scanner = types.ModuleType("u2_scanner")
        u2_scanner.DT_APP = "com.example"
        u2_scanner.connect_device = lambda: self.fake_device
        u2_scanner.click_three_selected_items = lambda _device: None
        u2_scanner.handle_guess_price_game = lambda _device: None
        u2_scanner.click_u2_control = lambda *args, **kwargs: True
        u2_scanner.execute_video_task = lambda *args, **kwargs: None

        utils = types.ModuleType("utils")
        utils.TASK_BTN_KW = ["去完成", "去浏览"]
        utils.BLACKLIST_KEYWORDS = []
        utils.LIVE_KW = []
        utils.get_ocr_text_blocks = lambda _device: self.ocr_blocks
        utils.check_can_open = lambda _device: None
        utils.log_task_completed = lambda *args, **kwargs: None
        utils.show_today_summary = lambda: None
        utils.browse_task = lambda *args, **kwargs: None
        utils.any_match = lambda text, keywords: any(kw in text for kw in keywords)
        utils.is_blacklisted = lambda name: name in self.blacklisted_names
        utils.back_to_task = lambda *args, **kwargs: True
        utils.show_dev_guide = lambda *args, **kwargs: None

        sys.modules["uiautomator2"] = types.ModuleType("uiautomator2")
        sys.modules["u2_scanner"] = u2_scanner
        sys.modules["utils"] = utils

    def tearDown(self):
        time.sleep = self.original_sleep
        for name, module in self.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def load_shopping_module(self):
        script_path = Path(__file__).resolve().parents[1] / "点淘购物赚钱.py"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            module_globals = runpy.run_path(str(script_path))
        module_globals["time"].sleep = lambda _seconds: None
        return module_globals, output

    def test_do_task_clicks_more_when_task_button_precedes_more_after_guess(self):
        # Given: OCR returns a visible task button before the collapsed-list expander.
        module_globals, output = self.load_shopping_module()
        module_globals["time"].sleep = lambda _seconds: None

        # When: the shopping script finishes a guess-price task.
        with contextlib.redirect_stdout(output):
            module_globals["do_task"]("guess", 0)

        # Then: it still clicks 查看更多 instead of returning early on 去完成.
        self.assertEqual(self.fake_device.clicks, [(540, 2100)])
        self.assertEqual(self.fake_device.presses, [])

    def test_detect_task_marks_yuanbao_mall_order_as_skip(self):
        # Given: the button row belongs to a dangerous yuanbao mall order task.
        self.blacklisted_names.add("元宝商城下单")
        self.ocr_blocks = [
            {"text": "元宝商城下单", "cx": 430, "cy": 1200},
            {"text": "去完成", "cx": 900, "cy": 1200},
        ]
        module_globals, _output = self.load_shopping_module()

        # When: the shopping script classifies the button before clicking it.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            task_type, seconds, task_name = module_globals["detect_task_name_before_click"](
                self.ocr_blocks,
                self.ocr_blocks[1],
            )

        # Then: the task is marked for skipping, not downgraded to browse.
        self.assertEqual((task_type, seconds, task_name), ("skip", 0, "元宝商城下单"))

    def test_blacklist_wins_over_nearby_browse_signal(self):
        # Given: OCR sees a dangerous task name and a nearby browse label.
        task_name = "元宝商城订单(0/1) +388"
        self.blacklisted_names.add(task_name)
        self.ocr_blocks = [
            {"text": task_name, "cx": 430, "cy": 1200},
            {"text": "浏览", "cx": 700, "cy": 1150},
            {"text": "去完成", "cx": 900, "cy": 1200},
        ]
        module_globals, _output = self.load_shopping_module()

        # When: the script classifies the task before clicking the button.
        result = module_globals["detect_task_name_before_click"](
            self.ocr_blocks,
            self.ocr_blocks[2],
        )

        # Then: the blacklist must take precedence over the browse fallback.
        self.assertEqual(result, ("skip", 0, task_name))

    def test_main_does_not_click_yuanbao_mall_order_button(self):
        # Given: the expanded shopping list contains only a blacklisted order task.
        self.blacklisted_names.add("元宝商城下单")
        self.ocr_blocks = [
            {"text": "查看更多", "cx": 540, "cy": 2100},
            {"text": "元宝商城下单", "cx": 430, "cy": 1200},
            {"text": "去完成", "cx": 900, "cy": 1200},
        ]
        module_globals, output = self.load_shopping_module()
        module_globals["MAX_TASKS"] = 1

        # When: the shopping script scans the task list.
        with contextlib.redirect_stdout(output):
            module_globals["main"]()

        # Then: it only clicks navigation/expansion points, never the blacklisted button.
        self.assertNotIn((900, 1200), self.fake_device.clicks)


if __name__ == "__main__":
    unittest.main()
