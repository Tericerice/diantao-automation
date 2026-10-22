"""隔离执行打工加速的分类函数，不连接真机。"""
import ast
import contextlib
import io
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class DagongAccelerationRoutingTest(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "打工加速.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        self.device = Mock()
        self.browse = Mock(return_value=True)
        self.ocr = Mock(return_value=[])
        self.ns = {
            "re": re, "d": self.device, "time": SimpleNamespace(sleep=lambda _s: None),
            "execute_browse_task": self.browse, "get_ocr_text_blocks": self.ocr,
        }
        exec(compile(tree, str(path), "exec"), self.ns)

    def call(self, name, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.ns[name](*args)

    def test_search_browse_is_excluded_from_all_browse_fallbacks(self):
        for text in ("搜索后浏览30秒", "搜索后浏览精选推荐30秒", "搜 索 后 浏 览30秒",
                     "搜索宝贝后浏览45秒+100元宝"):
            with self.subTest(text=text):
                self.assertIsNone(self.call("find_browse_task", [
                    {"text": text, "cx": 300, "cy": 400}
                ]))

    def test_split_search_name_does_not_hide_separate_normal_task(self):
        blocks = [
            {"text": "搜索后", "cx": 150, "cy": 400},
            {"text": "浏览30秒", "cx": 320, "cy": 400},
            {"text": "浏览精选推荐30秒", "cx": 300, "cy": 650},
        ]
        self.assertEqual(self.call("find_browse_task", blocks),
                         ("浏览精选推荐30秒", 300, 650))

    def test_sliding_browse_countdown_is_never_selected(self):
        for text in ("滑动浏览30秒", "滑动浏览11秒", "元滑动浏览30秒￥+0.1元",
                     "滑动 浏览 45 秒", "滑动浏览4"):
            with self.subTest(text=text):
                self.assertIsNone(self.call("find_browse_task", [
                    {"text": text, "cx": 900, "cy": 1200}
                ]))

    def test_sliding_browse_without_seconds_is_ignored_by_fallbacks(self):
        blocks = [
            {"text": "滑动浏览", "cx": 300, "cy": 1200},
            {"text": "30", "cx": 500, "cy": 1200},
            {"text": "秒", "cx": 560, "cy": 1200},
        ]
        self.assertIsNone(self.call("find_browse_task", blocks))

    def test_sliding_countdown_does_not_hide_real_browse_task(self):
        blocks = [
            {"text": "滑动浏览11秒", "cx": 900, "cy": 1200},
            {"text": "浏览精选推荐30秒", "cx": 300, "cy": 650},
        ]
        self.assertEqual(self.call("find_browse_task", blocks),
                         ("浏览精选推荐30秒", 300, 650))

    def test_direct_sliding_task_does_not_click_or_browse(self):
        self.assertFalse(self.call("exec_browse", 300, 400, "滑动浏览11秒"))
        self.device.click.assert_not_called()
        self.browse.assert_not_called()

    def test_direct_search_task_does_not_click_or_browse(self):
        self.assertFalse(self.call("exec_browse", 300, 400, "搜索后浏览30秒"))
        self.device.click.assert_not_called()
        self.browse.assert_not_called()

    def test_embedded_search_reward_does_not_interrupt_outer_browse(self):
        self.ocr.return_value = [
            {"text": "搜索宝贝后浏览45秒+100元宝", "cx": 300, "cy": 400},
            {"text": "领元宝", "cx": 900, "cy": 400},
            {"text": "滑动浏览11秒", "cx": 900, "cy": 1200},
        ]
        self.assertTrue(self.call("exec_browse", 300, 400, "浏览精选推荐30秒"))
        self.browse.assert_called_once_with(self.device, min_duration=30, max_wait=60)
        self.assertEqual(self.device.click.call_args.args, (300, 400))
        self.device.press.assert_called_once_with("back")

    def test_normal_browse_still_runs_and_returns(self):
        self.assertTrue(self.call("exec_browse", 300, 400, "浏览精选推荐30秒"))
        self.browse.assert_called_once_with(self.device, min_duration=30, max_wait=60)
        self.device.press.assert_called_once_with("back")

    def test_rejected_task_is_not_counted_or_logged(self):
        self.ocr.return_value = [{"text": "浏览精选推荐30秒", "cx": 300, "cy": 400}]
        self.browse.return_value = False
        log = Mock()
        self.ns.update(log_task_completed=log, show_today_summary=Mock(),
                       sys=SimpleNamespace(stdout=SimpleNamespace(encoding="utf-8")))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.ns["main"]()
        self.assertIn("共完成 0 个任务", output.getvalue())
        log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
