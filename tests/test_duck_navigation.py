import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class DuckNavigationTest(unittest.TestCase):
    def test_click_duck_entry_uses_visible_label_before_fixed_fallback(self):
        # Given: the visible duck-entry control is exposed through the UI hierarchy.
        module = self._load_script_with_stubbed_runtime()
        device = _FakeDevice()

        # When: the navigation helper looks for the duck entry.
        clicked = module.click_duck_entry(device)

        # Then: it clicks the labeled entry and does not need a coordinate fallback.
        self.assertTrue(clicked)
        self.assertEqual(device.clicked, [(520, 1730)])

    def test_duck_entry_fallback_coordinates_match_device_measurement(self):
        # Given: the device cannot expose the entry label through its UI hierarchy.
        module = self._load_script_with_stubbed_runtime()

        # Then: the fixed fallback remains the measured point requested for this device.
        self.assertEqual((module.DUCK_ENTRY_X, module.DUCK_ENTRY_Y), (824, 1771))

    def test_task_list_click_waits_three_extra_seconds_after_duck_page_load(self):
        # Given: navigation has clicked the visible duck-home entry.
        module = self._load_script_with_stubbed_runtime()
        device = _FakeDevice()
        events = []

        # When: navigation proceeds to the fixed task-list entry.
        with patch.object(
            module.time,
            "sleep",
            side_effect=lambda seconds: events.append(("sleep", seconds)),
        ), patch.object(
            device,
            "click",
            side_effect=lambda x, y: events.append(("click", (x, y))),
        ):
            module.navigate_to_duck_page(device)

        # Then: a dedicated three-second load delay immediately precedes that tap.
        task_click_index = events.index(("click", (182, 2595)))
        self.assertEqual(events[task_click_index - 1], ("sleep", 3))

    def test_ninety_second_live_task_is_whitelisted(self):
        # Given: OCR returns the 90-second golden-slot live task with progress text.
        module = self._load_script_with_stubbed_runtime()

        # Then: the whitelist-mode script accepts the live task.
        for task_name in (
            "看黄金8点档直播90秒(0/10)",
            "看黄金八点档直播90秒（0/10）",
        ):
            with self.subTest(task_name=task_name):
                self.assertTrue(module.is_whitelisted(task_name))

    def test_duck_shake_whitelist_accepts_ocr_spacing_and_latin_s_variants(self):
        # Given: OCR inserts spaces or recognizes 秒 as the Latin letter S.
        module = self._load_script_with_stubbed_runtime("点淘鸭摇一摇.py")

        # Then: all equivalent 90-second live task names remain whitelisted.
        task_names = (
            "看黄金8点档直播90秒(0/10)",
            "看黄金8点档直播90 秒(0/10)",
            "看黄金8点档直播90S(0/10)",
            "看黄金8点档直播 90秒(0/10)",
            "看黄金８点檔直播９０Ｓ（０/１）",
            "看黄金8点擋直播90秒(0/1)",
            # Actual OCR output captured from the task runner.
            "看黄8点档直播90秒(0/10)",
            "看8点档直播90秒(0/10)",
        )
        for task_name in task_names:
            with self.subTest(task_name=task_name):
                self.assertTrue(module.is_whitelisted(task_name))

    def test_duck_shake_passes_normalized_duration_to_live_executor(self):
        # Given: OCR recognizes the seconds unit as a Latin S.
        module = self._load_script_with_stubbed_runtime("点淘鸭摇一摇.py")
        device = _TaskDevice()
        module.d = device

        # When: the 90-second live task is executed.
        with patch.object(module.time, "sleep"), patch.object(
            module, "execute_live_task"
        ) as execute_live_task:
            module.do_task("看8点档直播90秒(0/1)", 100, 200)

        # Then: the executor receives the intended duration instead of falling
        # back to its generic live-task timeout.
        execute_live_task.assert_called_once_with(
            device,
            "看8点档直播90秒(0/1)",
            100,
            200,
            duration=90,
        )

    @staticmethod
    def _load_script_with_stubbed_runtime(script_name="点淘鸭钻石任务.py"):
        automation = types.ModuleType("uiautomator2")
        scanner = types.ModuleType("u2_scanner")
        scanner.connect_device = lambda: types.SimpleNamespace(
            window_size=lambda: (1264, 2780),
        )
        scanner.DT_APP = "com.taobao.live"
        scanner.execute_browse_task = lambda *args: None
        scanner.execute_live_task = lambda *args, **kwargs: None
        scanner.is_stale_no_buttons = lambda *args: False
        scanner.click_three_selected_items = lambda *args: None
        scanner.click_u2_control = lambda *args: True

        utils = types.ModuleType("utils")
        utils.get_ocr_text_blocks = lambda *args: []
        utils.log_task_completed = lambda *args: None
        utils.show_today_summary = lambda *args: None

        path = Path(__file__).parents[1] / script_name
        spec = importlib.util.spec_from_file_location("diamond_task_under_test", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with patch.dict(
            sys.modules,
            {"uiautomator2": automation, "u2_scanner": scanner, "utils": utils},
        ):
            spec.loader.exec_module(module)
        return module


class _FakeDevice:
    def __init__(self):
        self.clicked = []

    def click(self, x, y):
        self.clicked.append((x, y))

    def app_start(self, *args, **kwargs):
        pass

    def __call__(self, **kwargs):
        return _FakeControl(self)


class _FakeControl:
    def __init__(self, device):
        self.device = device
        self.exists = True

    def click(self):
        raise AssertionError("selector.click() should not be used for the device tap")

    def center(self):
        return (520, 1730)


class _TaskDevice:
    def click(self, x, y):
        pass

    def press(self, key):
        pass


if __name__ == "__main__":
    unittest.main()
