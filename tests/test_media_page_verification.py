import sys
import types
import unittest
from unittest.mock import patch


sys.modules.setdefault("uiautomator2", types.ModuleType("uiautomator2"))

import u2_scanner
import utils


class _Device:
    def __init__(self):
        self.presses = []
        self.swipes = []

    def window_size(self):
        return 1080, 2400

    def press(self, key):
        self.presses.append(key)

    def swipe(self, *args, **kwargs):
        self.swipes.append((args, kwargs))


class MediaPageVerificationTest(unittest.TestCase):
    def setUp(self):
        self.original_ocr = utils.get_ocr_text_blocks
        self.device = _Device()

    def tearDown(self):
        utils.get_ocr_text_blocks = self.original_ocr

    def test_classifies_live_landing_page(self):
        blocks = [
            {"text": "欢迎来到直播间"},
            {"text": "说点什么"},
            {"text": "57秒后完成"},
        ]

        self.assertEqual(u2_scanner.classify_media_page(blocks), "live")

    def test_video_entry_routes_to_live_once_when_landing_page_is_live(self):
        ocr_calls = []
        live_calls = []

        def fake_ocr(device):
            ocr_calls.append(device)
            return [
                {"text": "欢迎来到直播间"},
                {"text": "说点什么"},
                {"text": "57秒后完成"},
            ]

        def fake_live(*args, **kwargs):
            live_calls.append((args, kwargs))
            return "live-completed"

        utils.get_ocr_text_blocks = fake_ocr
        with patch.object(u2_scanner.time, "sleep", return_value=None), \
                patch.object(u2_scanner, "execute_live_task", fake_live):
            result = u2_scanner.execute_video_task(
                self.device,
                "看视频60秒",
                100,
                200,
                duration=60,
                extra_swipes=0,
                verify_media_page=True,
                initial_swipe=True,
            )

        self.assertEqual(result, "live-completed")
        self.assertEqual(len(ocr_calls), 1)
        self.assertEqual(len(live_calls), 1)
        self.assertEqual(live_calls[0][0][1:4], ("看视频60秒", 100, 200))
        self.assertEqual(live_calls[0][1]["duration"], 60)
        self.assertEqual(self.device.presses, ["back"])
        self.assertEqual(self.device.swipes, [])


if __name__ == "__main__":
    unittest.main()
