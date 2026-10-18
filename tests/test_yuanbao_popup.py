"""活动弹窗的循环、白名单和导航阻断，不连接手机或 OCR 服务。"""
import ast
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

import yuanbao_popup


def block(text, x=500, y=950):
    return {"text": text, "cx": x, "cy": y}


def popup(title="看李佳琦直播10秒", button_x=500):
    return [block("元宝中心", y=200), block(title),
            block("立即领奖", x=button_x, y=1400)]


CENTER = [block("元宝中心", y=200), block("走路赚元宝", y=1500)]
LIVE = [block("直播间"), block("说点什么")]
VIDEO = [block("上滑查看更多视频"), block("发放奖励")]


class YuanbaoPopupTests(unittest.TestCase):
    def run_handler(self, frames, **kwargs):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "u2_scanner.py").read_text(encoding="utf-8"))
        classifier = next(node for node in tree.body
                          if isinstance(node, ast.FunctionDef) and node.name == "classify_media_page")
        namespace = {}
        exec(compile(ast.Module(body=[classifier], type_ignores=[]), "u2_scanner.py", "exec"), namespace)
        scanner = types.ModuleType("u2_scanner")
        scanner.classify_media_page = namespace["classify_media_page"]
        utils = types.ModuleType("utils")
        utils.get_ocr_text_blocks = Mock(side_effect=frames)
        device = Mock()
        device.window_size.return_value = (1000, 2000)
        with patch.dict(sys.modules, {"utils": utils, "u2_scanner": scanner}), \
                patch.object(yuanbao_popup.time, "sleep") as sleep:
            result = yuanbao_popup.handle_yuanbao_live_popups(device, **kwargs)
        return result, device, sleep

    def test_chained_popups_rescan_and_use_each_new_button(self):
        result, device, sleep = self.run_handler([
            popup(), LIVE, popup("看10秒直播立得", button_x=620), LIVE, CENTER, CENTER,
        ])
        self.assertTrue(result)
        self.assertEqual(device.click.call_args_list, [unittest.mock.call(500, 1400),
                                                      unittest.mock.call(620, 1400)])
        self.assertEqual(device.press.call_count, 2)
        self.assertEqual([c.args for c in sleep.call_args_list].count((12,)), 2)

    def test_delayed_popup_is_caught_by_clear_page_recheck(self):
        result, device, _ = self.run_handler([CENTER, popup(), LIVE, CENTER, CENTER])
        self.assertTrue(result)
        device.click.assert_called_once_with(500, 1400)

    def test_no_popup_does_not_click_or_back(self):
        result, device, _ = self.run_handler([CENTER, CENTER])
        self.assertTrue(result)
        device.click.assert_not_called()
        device.press.assert_not_called()

    def test_other_tasks_and_durations_are_not_claimed(self):
        for title in ("看视频10秒", "看直播30秒", "浏览商品10秒", "邀请好友"):
            with self.subTest(title=title):
                result, device, _ = self.run_handler([popup(title)])
                self.assertFalse(result)
                device.click.assert_not_called()

    def test_background_live_text_does_not_enable_non_live_popup(self):
        result, device, _ = self.run_handler([
            popup("看视频10秒") + [block("看直播10秒", y=300)],
        ])
        self.assertFalse(result)
        device.click.assert_not_called()

    def test_split_text_and_whitespace_match(self):
        frames = popup("看 李佳琦 直播") + [block("10 秒", x=700)]
        result, _, _ = self.run_handler([frames, LIVE, CENTER, CENTER])
        self.assertTrue(result)

    def test_empty_ocr_retries_and_does_not_report_clear(self):
        result, device, _ = self.run_handler([[], [], []])
        self.assertFalse(result)
        device.click.assert_not_called()

    def test_transient_empty_ocr_recovers(self):
        result, _, _ = self.run_handler([[], popup(), [], LIVE, CENTER, CENTER])
        self.assertTrue(result)

    def test_button_click_did_not_enter_live(self):
        result, device, sleep = self.run_handler([popup(), popup(), popup(), popup()])
        self.assertFalse(result)
        device.click.assert_called_once()
        device.press.assert_not_called()
        self.assertNotIn(unittest.mock.call(12), sleep.call_args_list)

    def test_video_landing_does_not_run_live_task(self):
        result, device, sleep = self.run_handler([popup(), VIDEO])
        self.assertFalse(result)
        device.press.assert_not_called()
        self.assertNotIn(unittest.mock.call(12), sleep.call_args_list)

    def test_return_failure_stops_instead_of_advancing(self):
        result, device, _ = self.run_handler([popup(), LIVE, LIVE])
        self.assertFalse(result)
        device.press.assert_called_once_with("back")

    def test_execution_limit_does_not_report_complete(self):
        result, device, _ = self.run_handler([popup(), LIVE, popup()], max_tasks=1)
        self.assertFalse(result)
        device.click.assert_called_once()


class NavigationIntegrationTests(unittest.TestCase):
    def load_function(self, filename, name, namespace):
        tree = ast.parse((Path(__file__).resolve().parents[1] / filename).read_text(encoding="utf-8"))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == name)
        exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
        return namespace[name]

    def test_navigation_chain_blocks_next_entry_until_popups_are_clear(self):
        for cleared in (True, False):
            with self.subTest(cleared=cleared):
                clicks = Mock(return_value=True)
                guard = Mock(return_value=cleared)
                nav = self.load_function("u2_scanner.py", "navigate_chain", {
                    "u2_click_text": clicks, "time": types.SimpleNamespace(sleep=Mock()),
                    "handle_yuanbao_live_popups": guard,
                })
                device = Mock()
                self.assertEqual(nav(device, [("中心", "元宝中心"), ("打工", "打工赚元宝")]), cleared)
                guard.assert_called_once_with(device)
                self.assertEqual(clicks.call_count, 2 if cleared else 1)

    def test_connectivity_attempt_stops_before_target_when_guard_fails(self):
        namespace = {"time": types.SimpleNamespace(sleep=Mock()), "DT_APP": "com.taobao.live",
                     "ATTEMPTS_PER_ENTRY": 3, "APP_START_WAIT_SECONDS": 8,
                     "CENTER_OCR_PRE_SCAN_DELAY_SECONDS": 5, "STEP_SETTLE_SECONDS": 3,
                     "_enter_yuanbao_center_ocr": Mock(return_value=False)}
        run = self.load_function("连通性脚本.py", "_run_attempt", namespace)
        target = Mock()
        run(Mock(), "打工", target, 1000, 2000, 1)
        target.assert_not_called()

    def test_money_card_navigation_failure_stops_subtasks(self):
        live, browse, guess = Mock(), Mock(), Mock()
        main = self.load_function("赚钱卡.py", "main", {
            "navigate_to_money_card": Mock(return_value=False),
            "run_live_subtask": live, "run_browse_subtask": browse,
            "run_guess_price_subtask": guess, "time": types.SimpleNamespace(sleep=Mock()),
        })
        main()
        live.assert_not_called()
        browse.assert_not_called()
        guess.assert_not_called()


if __name__ == "__main__":
    unittest.main()
