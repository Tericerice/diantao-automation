import sys
import types
import unittest
from unittest.mock import patch


sys.modules.setdefault("uiautomator2", types.ModuleType("uiautomator2"))

import u2_scanner
import utils


class _Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Selector:
    @property
    def exists(self):
        return True


class _Device:
    def __init__(self):
        self.presses = []
        self.swipes = []

    def window_size(self):
        return 1080, 2400

    def __call__(self, **_kwargs):
        return _Selector()

    def swipe(self, *_args, **_kwargs):
        self.swipes.append((_args, _kwargs))
        return None

    def press(self, key):
        self.presses.append(key)


class _TimedDevice(_Device):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.swipe_times = []

    def swipe(self, *args, **kwargs):
        self.swipe_times.append(self.clock.now)
        super().swipe(*args, **kwargs)


class TaskTimingGuardsTest(unittest.TestCase):
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
            "get_ocr_text_blocks": utils.get_ocr_text_blocks,
        }
        u2_scanner.time.time = self.clock.time
        u2_scanner.time.sleep = self.clock.sleep
        u2_scanner.handle_open_allow_popup = lambda _device: False
        u2_scanner.close_live_popups = lambda _device: False
        u2_scanner.detect_live_completion = lambda _device: False

    def tearDown(self):
        u2_scanner.time.time = self.originals["time"]
        u2_scanner.time.sleep = self.originals["sleep"]
        u2_scanner.scan_page = self.originals["scan_page"]
        u2_scanner.handle_open_allow_popup = self.originals["handle_open_allow_popup"]
        u2_scanner.close_live_popups = self.originals["close_live_popups"]
        u2_scanner.detect_live_completion = self.originals["detect_live_completion"]
        utils.get_ocr_text_blocks = self.originals["get_ocr_text_blocks"]

    def _countdown_then_missing(self):
        scans = iter(
            [
                [{"text": "10秒后完成"}],
                [],
            ]
        )
        u2_scanner.scan_page = lambda _device: next(scans, [])

    def test_live_task_waits_full_duration_when_countdown_temporarily_disappears(self):
        # Given: the live countdown is visible once, then missing from U2 scans.
        self._countdown_then_missing()

        # When: a ten-second live task runs.
        completed = u2_scanner.execute_live_task(self.device, "看直播10秒", 0, 0, duration=10)

        # Then: transient text loss is remembered, but never bypasses the minimum duration.
        self.assertTrue(completed)
        self.assertGreaterEqual(self.clock.now, 17)

    def test_video_task_waits_full_duration_without_countdown_scans(self):
        # Given: the video executor is deliberately independent of U2 text scans.
        self._countdown_then_missing()

        # When: a ten-second video task runs.
        completed = u2_scanner.execute_video_task(self.device, "看视频10秒", 0, 0, duration=10)

        # Then: the video remains open for the requested duration before returning.
        self.assertTrue(completed)
        self.assertGreaterEqual(self.clock.now, 13)
        self.assertTrue(all(call[0][1] == 1680 for call in self.device.swipes))
        self.assertTrue(all(call[0][3] == 720 for call in self.device.swipes))
        self.assertEqual(self.device.presses, ["back"])

    def test_video_task_adds_ten_seconds_to_time_based_task(self):
        # Given: the video task is time-based and has no swipe-count marker.
        u2_scanner.scan_page = lambda _device: []

        # When: a ten-second video task runs.
        u2_scanner.execute_video_task(
            self.device, "看视频10秒", 0, 0, duration=10, extra_time_seconds=10
        )

        # Then: it stays for the requested time plus ten seconds.
        self.assertGreaterEqual(self.clock.now, 23)

    def test_video_task_honors_extra_swipes_and_uses_deadline(self):
        # Given: a short task with two explicitly requested extra swipes.
        u2_scanner.scan_page = lambda _device: self.fail(
            "video task must not scan count markers"
        )

        # When: the video task runs.
        completed = u2_scanner.execute_video_task(
            self.device, "看视频", 0, 0, duration=5, extra_swipes=2
        )

        # Then: it stays until the deadline and dispatches one base plus two extra swipes.
        self.assertTrue(completed)
        self.assertGreaterEqual(self.clock.now, 8)
        self.assertEqual(len(self.device.swipes), 3)
        self.assertTrue(all(call[0][1] == 1680 for call in self.device.swipes))
        self.assertTrue(all(call[0][3] == 720 for call in self.device.swipes))
        self.assertEqual(self.device.presses, ["back"])

    def test_video_task_adds_one_second_between_planned_swipes(self):
        # Given: one base swipe, one extra swipe, and a one-second interval extension.
        device = _TimedDevice(self.clock)
        with patch.object(u2_scanner.random, "randint", return_value=1):
            # When: the video task runs with the scoped interval extension.
            completed = u2_scanner.execute_video_task(
                device,
                "看视频5秒",
                0,
                0,
                duration=5,
                extra_swipes=1,
                swipe_interval_extra_seconds=1,
            )

        # Then: the full plan is preserved and the gap is base 2.5s + 1s.
        self.assertTrue(completed)
        self.assertEqual(len(device.swipes), 2)
        self.assertAlmostEqual(device.swipe_times[1] - device.swipe_times[0], 3.5)
        self.assertGreaterEqual(self.clock.now, 9.0)

    def test_browse_task_does_not_exit_when_three_seconds_remain_too_early(self):
        # Given: U2 repeatedly reports that three seconds remain.
        u2_scanner.scan_page = lambda _device: [{"text": "滑动浏览3秒"}]

        # When: the browse executor monitors the countdown.
        completed = u2_scanner.execute_browse_task(self.device, max_wait=30)

        # Then: it honors the detected duration plus the short-task safety buffer.
        self.assertTrue(completed)
        self.assertGreaterEqual(self.clock.now, 13)

    def test_browse_task_adds_two_extra_finish_swipes(self):
        # Given: the browse countdown reaches its minimum duration immediately.
        u2_scanner.scan_page = lambda _device: self._finish_browse_at_minimum(
            [{"text": "滑动浏览3秒"}]
        )

        # When: the U2 browse executor finishes the task.
        completed = u2_scanner.execute_browse_task(self.device, max_wait=30)

        # Then: the initial swipe plus four finish swipes are dispatched.
        self.assertTrue(completed)
        self.assertEqual(len(self.device.swipes), 5)

    def test_browse_task_ignores_early_completion_prompt_until_minimum_duration(self):
        # Given: no countdown text is available and a completion prompt appears immediately.
        u2_scanner.scan_page = lambda _device: []

        # When: a ten-second fixed-duration browse task runs.
        completed = u2_scanner.execute_browse_task(self.device, min_duration=10, max_wait=30)

        # Then: the prompt cannot cause an early return.
        self.assertTrue(completed)
        self.assertGreaterEqual(self.clock.now, 20)

    def test_shared_browse_task_does_not_exit_when_three_seconds_remain_too_early(self):
        # Given: OCR repeatedly reports that three seconds remain.
        utils.get_ocr_text_blocks = lambda _device: [{"text": "滑动浏览3秒"}]

        # When: the shared browse executor monitors the countdown.
        completed = utils.browse_task(self.device, max_wait=30)

        # Then: it honors the detected duration plus the short-task safety buffer.
        self.assertTrue(completed)
        self.assertGreaterEqual(self.clock.now, 13)

    def test_shared_browse_task_adds_two_extra_finish_swipes(self):
        # Given: OCR reports the browse countdown at its minimum duration.
        utils.get_ocr_text_blocks = lambda _device: self._finish_browse_at_minimum(
            [{"text": "滑动浏览3秒"}]
        )

        # When: the shared OCR browse executor finishes the task.
        completed = utils.browse_task(self.device, max_wait=30)

        # Then: the initial swipe plus four finish swipes are dispatched.
        self.assertTrue(completed)
        self.assertEqual(len(self.device.swipes), 5)

    def test_shared_browse_task_ignores_early_completion_prompt_until_minimum_duration(self):
        # Given: OCR finds no countdown and a completion prompt appears immediately.
        utils.get_ocr_text_blocks = lambda _device: []

        # When: a ten-second fixed-duration browse task runs through the shared utility.
        completed = utils.browse_task(self.device, min_duration=10, max_wait=30)

        # Then: the prompt cannot cause an early return.
        self.assertTrue(completed)
        self.assertGreaterEqual(self.clock.now, 20)

    def test_fixed_browse_waits_full_duration_and_buffer_after_slow_scan(self):
        for executor in (u2_scanner.execute_browse_task, utils.browse_task):
            for duration, extra, expected in ((30, 5, 40), (60, 5, 65), (30, 20, 50)):
                with self.subTest(executor=executor.__name__, duration=duration, extra=extra):
                    self.clock.now = 0
                    device = _TimedDevice(self.clock)
                    scan_finished = []

                    def slow_scan(_device):
                        self.clock.sleep(5)
                        scan_finished.append(self.clock.now)
                        return []

                    with patch.object(u2_scanner, "scan_page", side_effect=slow_scan), \
                         patch.object(utils, "get_ocr_text_blocks", side_effect=slow_scan):
                        completed = executor(device, min_duration=duration, extra_seconds=extra)

                    self.assertTrue(completed)
                    self.assertGreaterEqual(self.clock.now - scan_finished[0], expected)
                    # 浏览期间持续滑动，不能仅在返回前静等补足时间。
                    self.assertGreaterEqual(device.swipe_times[-1] - scan_finished[0], expected - 0.8)

    def test_fixed_browse_timeout_before_safety_buffer_is_not_success(self):
        for executor in (u2_scanner.execute_browse_task, utils.browse_task):
            with self.subTest(executor=executor.__name__):
                self.clock.now = 0
                with patch.object(u2_scanner, "scan_page", return_value=[]), \
                     patch.object(utils, "get_ocr_text_blocks", return_value=[]):
                    completed = executor(self.device, min_duration=30, max_wait=35)
                self.assertFalse(completed)

    def test_browse_countdown_cannot_shorten_requested_duration(self):
        for countdown in (3, 5):
            with self.subTest(countdown=countdown):
                self.clock.now = 0
                device = _TimedDevice(self.clock)
                scans = iter([[{"text": f"滑动浏览{countdown}秒"}]])
                with patch.object(u2_scanner, "scan_page", side_effect=lambda _d: next(scans, [])):
                    completed = u2_scanner.execute_browse_task(
                        device, min_duration=30, max_wait=70, extra_seconds=10
                    )
                self.assertTrue(completed)
                self.assertGreaterEqual(self.clock.now, 40)
                self.assertGreaterEqual(device.swipe_times[-1], 40)

    def _finish_browse_at_minimum(self, blocks):
        self.clock.now = 13
        return blocks


if __name__ == "__main__":
    unittest.main()
