import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


sys.modules.setdefault("uiautomator2", types.ModuleType("uiautomator2"))

import u2_scanner


class _Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Device:
    def __init__(self):
        self.swipes = []
        self.presses = []
        self.clicks = []

    def window_size(self):
        return 1080, 2400

    def click(self, *args):
        self.clicks.append(args)

    def swipe(self, *args, **kwargs):
        self.swipes.append((args, kwargs))

    def press(self, key):
        self.presses.append(key)


class VideoTaskContractTest(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.device = _Device()
        self.originals = {
            "time": u2_scanner.time.time,
            "sleep": u2_scanner.time.sleep,
            "scan_page": u2_scanner.scan_page,
            "handle_open_allow_popup": u2_scanner.handle_open_allow_popup,
            "close_live_popups": u2_scanner.close_live_popups,
            "detect_live_completion": u2_scanner.detect_live_completion,
        }
        u2_scanner.time.time = self.clock.time
        u2_scanner.time.sleep = self.clock.sleep
        u2_scanner.scan_page = self._unexpected_call("scan_page")
        u2_scanner.handle_open_allow_popup = self._unexpected_call(
            "handle_open_allow_popup"
        )
        u2_scanner.close_live_popups = self._unexpected_call("close_live_popups")
        u2_scanner.detect_live_completion = self._unexpected_call(
            "detect_live_completion"
        )

    def tearDown(self):
        u2_scanner.time.time = self.originals["time"]
        u2_scanner.time.sleep = self.originals["sleep"]
        u2_scanner.scan_page = self.originals["scan_page"]
        u2_scanner.handle_open_allow_popup = self.originals[
            "handle_open_allow_popup"
        ]
        u2_scanner.close_live_popups = self.originals["close_live_popups"]
        u2_scanner.detect_live_completion = self.originals[
            "detect_live_completion"
        ]

    @staticmethod
    def _unexpected_call(name):
        def fail(*_args, **_kwargs):
            raise AssertionError(f"video task must not call {name}")

        return fail

    def test_video_task_only_swipes_until_deadline_then_exits(self):
        completed = u2_scanner.execute_video_task(
            self.device, "看视频10秒", 0, 0, duration=10
        )

        self.assertTrue(completed)
        self.assertGreaterEqual(self.clock.now, 13)
        self.assertGreater(len(self.device.swipes), 0)
        self.assertEqual(self.device.presses, ["back"])
        self.assertEqual(self.device.clicks, [])

    def test_video_swipe_count_range_maps_sixty_seconds_to_eight_to_twelve(self):
        # Given: the requested duration is one minute.
        # When: the shared video policy calculates its base swipe range.
        swipe_range = u2_scanner.video_swipe_count_range(60)

        # Then: the base plan fluctuates between eight and twelve swipes.
        self.assertEqual(swipe_range, (8, 12))

    def test_video_task_adds_three_extra_swipes_to_the_duration_plan(self):
        # Given: a one-minute task and a deterministic minimum base plan.
        with patch.object(u2_scanner.random, "randint", return_value=8):
            # When: the executor receives the requested three extra swipes.
            completed = u2_scanner.execute_video_task(
                self.device,
                "看视频60秒",
                0,
                0,
                duration=60,
                extra_swipes=3,
            )

        # Then: eight planned swipes plus three extra swipes are dispatched.
        self.assertTrue(completed)
        self.assertEqual(len(self.device.swipes), 11)

    def test_video_task_default_adds_seven_to_nine_extra_swipes_to_the_duration_plan(self):
        # Given: a one-minute task using the shared default video policy.
        with patch.object(u2_scanner.random, "randint", side_effect=[8, 9]):
            # When: the executor runs without an explicit extra swipe override.
            completed = u2_scanner.execute_video_task(
                self.device,
                "看视频60秒",
                0,
                0,
                duration=60,
            )

        # Then: eight base swipes plus a default value in the seven-to-nine range
        # are dispatched.
        self.assertTrue(completed)
        self.assertEqual(len(self.device.swipes), 17)

    def test_video_task_ignores_popup_and_countdown_signals(self):
        completed = u2_scanner.execute_video_task(
            self.device, "看视频", 0, 0, duration=5
        )

        self.assertTrue(completed)
        self.assertEqual(self.device.presses, ["back"])

    def test_slow_device_still_completes_all_planned_swipes(self):
        starts = []

        def slow_swipe(*args, **kwargs):
            starts.append(self.clock.now)
            self.clock.sleep(8)

        self.device.swipe = slow_swipe
        with patch.object(u2_scanner.random, "randint", return_value=8):
            completed = u2_scanner.execute_video_task(
                self.device, "看视频60秒", 0, 0, duration=60, extra_swipes=7,
            )
        self.assertTrue(completed)
        self.assertEqual(len(starts), 15)
        self.assertTrue(all(b - a >= 4 for a, b in zip(starts, starts[1:])))
        self.assertEqual(self.device.presses, ["back"])

    def test_failed_swipe_is_not_reported_as_completed(self):
        with patch.object(self.device, "swipe", side_effect=RuntimeError("offline")):
            completed = u2_scanner.execute_video_task(
                self.device, "看视频5秒", 0, 0, duration=5, extra_swipes=0,
            )
        self.assertFalse(completed)
        self.assertEqual(self.device.presses, ["back"])

    def test_walk_script_routes_video_name_to_video_executor(self):
        events = []
        device = _RouteDevice(events)

        scanner = types.ModuleType("u2_scanner")
        scanner.execute_live_task = lambda *_args: events.append("live")

        def record_video_task(*_args, **kwargs):
            events.append(("video", kwargs))

        scanner.execute_video_task = record_video_task
        scanner.execute_browse_task = lambda *_args: events.append("browse")
        scanner.handle_guess_price_game = lambda *_args: events.append("guess")

        utils = types.ModuleType("utils")
        utils.connect_device = lambda: device
        utils.get_ocr_text_blocks = lambda *_args: []
        utils.check_can_open = lambda *_args: events.append("check")
        utils.log_task_completed = lambda *_args: None
        utils.show_today_summary = lambda *_args: None
        utils.DT_APP = "com.taobao.live"
        utils.get_current_app = lambda *_args: (utils.DT_APP, "")
        utils.pause_global_watcher = lambda *_args: events.append("pause")
        utils.resume_global_watcher = lambda *_args: events.append("resume")

        path = Path(__file__).parents[1] / "走路赚元宝.py"
        spec = importlib.util.spec_from_file_location("walk_video_route_under_test", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"utils": utils, "u2_scanner": scanner}):
            spec.loader.exec_module(module)

        module.time = types.SimpleNamespace(sleep=lambda _seconds: None)
        task_type = module.match_task_type("看视频60秒")
        self.assertEqual(task_type, "video")
        self.assertEqual(module.match_task_type("浏览看视频60秒"), "video")
        module.execute_task(task_type, "看视频60秒", 100, 200)

        self.assertEqual(events[0:2], ["pause", ("click", 100, 200)])
        self.assertEqual(events[2][0], "video")
        self.assertNotIn("extra_swipes", events[2][1])
        self.assertEqual(events[3], "resume")


class _RouteDevice:
    def __init__(self, events):
        self.events = events

    def window_size(self):
        return 1080, 2400

    def click(self, x, y):
        self.events.append(("click", x, y))

    def press(self, key):
        self.events.append(("press", key))


if __name__ == "__main__":
    unittest.main()
