import contextlib
import io
import runpy
import sys
import types
import unittest
import time
from unittest.mock import patch
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

    def window_size(self):
        return 1080, 2400

    def __call__(self, **_kwargs):
        return _FakeSelector()

    def app_start(self, _app_name, stop=False):
        return None

    def click(self, x, y):
        self.clicks.append((x, y))

    def press(self, key):
        self.presses.append(key)

    def swipe(self, x1, y1, x2, y2, duration=0.3):
        return None


class DuckShakeExtraYuanbaoTest(unittest.TestCase):
    def setUp(self):
        self.original_sleep = time.sleep
        self.fake_device = _FakeDevice()
        self.browse_calls = []
        self.video_calls = []
        self.original_modules = {
            name: sys.modules.get(name)
            for name in ("uiautomator2", "u2_scanner", "utils")
        }

        u2_scanner = types.ModuleType("u2_scanner")
        u2_scanner.DT_APP = "com.example"
        u2_scanner.connect_device = lambda: self.fake_device
        u2_scanner.execute_live_task = lambda *_args, **_kwargs: None
        u2_scanner.execute_video_task = self._record_video_task
        u2_scanner.is_stale_no_buttons = lambda prev, current, limit=3: False
        u2_scanner.click_three_selected_items = lambda _device: None
        u2_scanner.execute_browse_task = self._record_browse_task

        utils = types.ModuleType("utils")
        utils.get_ocr_text_blocks = lambda _device: []

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

    def _record_browse_task(self, device, min_duration=0, max_wait=120, extra_seconds=5):
        self.browse_calls.append((device, min_duration, max_wait, extra_seconds))
        return True

    def _record_video_task(
        self, device, task_name, btn_cx, btn_cy, duration=None, **_kwargs
    ):
        self.video_calls.append((device, task_name, btn_cx, btn_cy, duration))
        return True

    def load_extra_yuanbao_module(self):
        script_path = Path(__file__).resolve().parents[1] / "点淘鸭摇一摇额外元宝.py"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            module_globals = runpy.run_path(str(script_path))
        module_globals["time"].sleep = lambda _seconds: None
        return module_globals

    def test_browse_reserves_scan_time_and_returns_only_after_success(self):
        module_globals = self.load_extra_yuanbao_module()
        with contextlib.redirect_stdout(io.StringIO()):
            completed = module_globals["execute_extra_yuanbao_task"](
                "browse", "再得30元宝", 540, 1200
            )
        self.assertTrue(completed)
        self.assertEqual(self.browse_calls, [(self.fake_device, 30, 70, 10)])
        self.assertEqual(self.fake_device.presses, ["back"])

    def test_browse_timeout_keeps_page_and_does_not_report_completion(self):
        module_globals = self.load_extra_yuanbao_module()
        execute = module_globals["execute_extra_yuanbao_task"]
        execute.__globals__["execute_browse_task"] = lambda *_a, **_k: False
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            completed = execute("browse", "再得30元宝", 540, 1200)
        self.assertFalse(completed)
        self.assertEqual(self.fake_device.presses, [])
        self.assertNotIn("✅ 完成", output.getvalue())

    def test_scan_stops_without_counting_failed_task(self):
        module_globals = self.load_extra_yuanbao_module()
        scan = module_globals["scan_and_execute"]
        blocks = [{"text": "再得30元宝", "cx": 540, "cy": 1200}]
        output = io.StringIO()
        with patch.dict(scan.__globals__, {
            "get_ocr_text_blocks": lambda _d: blocks,
            "execute_extra_yuanbao_task": lambda *_a: False,
        }), contextlib.redirect_stdout(output):
            scan()
        self.assertNotIn("已完成 1 个", output.getvalue())

    def test_scan_extra_yuanbao_task_returns_matching_reward_text(self):
        # Given: OCR sees the extra reward entry on the shake task screen.
        module_globals = self.load_extra_yuanbao_module()
        blocks = [
            {"text": "今日任务", "cx": 200, "cy": 400},
            {"text": "额外获得30元宝", "cx": 540, "cy": 1200},
            {"text": "去完成", "cx": 900, "cy": 1800},
        ]

        # When: the shake script scans for the extra yuanbao entry.
        result = module_globals["scan_extra_yuanbao_task"](blocks)

        # Then: it targets the reward entry itself.
        self.assertEqual(result, ("video", "额外获得30元宝", 540, 1200))

    def test_do_extra_yuanbao_video_task_runs_for_thirty_plus_ten_seconds(self):
        # Given: a detected extra reward entry.
        module_globals = self.load_extra_yuanbao_module()
        output = io.StringIO()

        # When: the shake script executes the extra reward task.
        with contextlib.redirect_stdout(output):
            module_globals["execute_extra_yuanbao_task"]("video", "额外获得30元宝", 540, 1200)

        # Then: it clicks through and runs the video task for thirty plus ten seconds.
        self.assertEqual(self.fake_device.clicks, [(540, 1200)])
        self.assertEqual(
            self.video_calls,
            [(self.fake_device, "额外获得30元宝", 540, 1200, 40)],
        )
        self.assertEqual(self.browse_calls, [])
        self.assertEqual(self.fake_device.presses, [])


if __name__ == "__main__":
    unittest.main()
