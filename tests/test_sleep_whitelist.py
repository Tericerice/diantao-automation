"""睡觉直播气泡的精确白名单识别，不连接真实设备。"""
import ast
import re
import unittest
from pathlib import Path


def block(text, x=400, y=800):
    return {"text": text, "cx": x, "cy": y}


class SleepWhitelistTest(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / "睡觉赚元宝.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        nodes = [node for node in tree.body
                 if (isinstance(node, ast.FunctionDef) and node.name == "match_live_bubble")
                 or (isinstance(node, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "LIVE_TASK_WHITELIST"
                             for t in node.targets))]
        self.namespace = {"re": re, "screen_height": 2400}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), self.namespace)
        self.match = self.namespace["match_live_bubble"]

    def test_three_whitelisted_titles(self):
        for name in ("看李佳琦直播60秒", "看香菇来了直播间60秒", "看福利直播30秒"):
            with self.subTest(name=name):
                self.assertEqual(self.match([block(name)]), {"name": name, "cx": 400, "cy": 800})

    def test_live_bubble_is_limited_to_upper_half(self):
        self.assertIsNotNone(self.match([block("看福利直播30秒", y=1200)]))
        self.assertIsNone(self.match([block("看福利直播30秒", y=1201)]))

    def test_screenshot_line_breaks(self):
        for first, second, expected in (
                ("看李佳琦直", "播60秒", "看李佳琦直播60秒"),
                ("看香菇来了", "直播间60秒", "看香菇来了直播间60秒"),
                ("看福利直播", "30秒", "看福利直播30秒")):
            with self.subTest(expected=expected):
                self.assertEqual(self.match([block(first), block(second, y=840)])["name"], expected)

    def test_whitespace_and_progress(self):
        self.assertEqual(self.match([block("看 李佳琦直播 60秒（0/1）")])["name"],
                         "看李佳琦直播60秒（0/1）")

    def test_no_fuzzy_or_generic_live_match(self):
        for name in ("看李佳琪直播60秒", "看香菇来啦直播间60秒", "看其他直播间60秒",
                     "看福利直播60秒", "看李佳琦直播60秒并下单", "看直播60秒"):
            with self.subTest(name=name):
                self.assertIsNone(self.match([block(name)]))

    def test_other_bubble_or_product_text_is_not_joined(self):
        self.assertIsNone(self.match([block("看李佳琦直"), block("播60秒", x=700, y=840)]))
        self.assertIsNone(self.match([block("看李佳琦直"), block("播60秒", y=1100)]))
        self.assertIsNone(self.match([block("看李佳琦直播60秒", y=1800)]))
