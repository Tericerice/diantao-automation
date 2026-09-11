import ast
import re
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_function(filename, function_name, extra_globals=None):
    source = (ROOT / filename).read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=filename)
    function = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    namespace = {"re": re}
    if extra_globals:
        namespace.update(extra_globals)
    code = compile(ast.Module(body=[function], type_ignores=[]), filename, "exec")
    exec(code, namespace)
    return namespace[function_name]


class VideoTaskRoutingTest(unittest.TestCase):
    def test_shopping_ocr_keeps_video_name_as_pre_click_type(self):
        detect_task = load_function(
            "点淘购物赚钱.py",
            "detect_task_name_before_click",
            {
                "_TITLE_BLACKLIST": [],
                "is_blacklisted": lambda _text: False,
                "normalize_task_name": load_function(
                    "点淘购物赚钱.py", "normalize_task_name"
                ),
                "SHOPPING_TASK_ROUTE_OVERRIDE_MAP": {"看视频": "live"},
            },
        )
        blocks = [
            {"text": "看视频60秒(4/10)", "cx": 400, "cy": 1000},
            {"text": "去完成", "cx": 1000, "cy": 1000},
        ]

        task_type, seconds, task_name = detect_task(blocks, blocks[1])

        self.assertEqual((task_type, seconds), ("video", 60))
        self.assertEqual(task_name, "看视频60秒(4/10)")

    def test_shopping_ocr_classifies_live_landing_page(self):
        classify_media_page = load_function(
            "点淘购物赚钱.py",
            "classify_media_page",
        )

        blocks = [
            {"text": "关注", "cx": 436, "cy": 200},
            {"text": "12072观看", "cx": 252, "cy": 224},
            {"text": "欢迎来到午夜徘徊直播间", "cx": 450, "cy": 2410},
            {"text": "说点什么", "cx": 149, "cy": 2622},
            {"text": "57秒后完成", "cx": 1170, "cy": 1126},
        ]

        self.assertEqual(classify_media_page(blocks), "live")

    def test_shopping_ocr_classifies_video_landing_page(self):
        classify_media_page = load_function(
            "点淘购物赚钱.py",
            "classify_media_page",
        )

        blocks = [
            {"text": "57秒后发放奖励", "cx": 246, "cy": 229},
            {"text": "查看详情", "cx": 639, "cy": 2460},
            {"text": "上滑查看更多视频", "cx": 638, "cy": 2624},
        ]

        self.assertEqual(classify_media_page(blocks), "video")

    def test_shopping_media_timer_starts_after_post_click_ocr(self):
        events = []

        class Clock:
            def __init__(self):
                self.now = 0.0

            def time(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        clock = Clock()

        def detect_media_type(_task_type, _task_name):
            events.append(("ocr", clock.time()))
            clock.sleep(4)
            return "video"

        def execute_video(*_args, **_kwargs):
            events.append(("video", clock.time()))

        do_task = load_function(
            "点淘购物赚钱.py",
            "do_task",
            {
                "d": types.SimpleNamespace(),
                "time": clock,
                "check_can_open": lambda _device: None,
                "detect_entered_media_type": detect_media_type,
                "execute_video_task": execute_video,
                "back_to_task": lambda *_args, **_kwargs: events.append(
                    ("back", clock.time())
                ),
                "TASK_BTN_KW": [],
                "SHOPPING_TASK_ROUTE_OVERRIDE_MAP": {"看视频": "live"},
                "normalize_task_name": lambda text: "看视频" if "看视频" in text else text,
            },
        )

        started_at = do_task("video", 60, "看视频60秒")

        self.assertEqual(started_at, 7.0)
        self.assertEqual(events, [("ocr", 3.0), ("video", 7.0), ("back", 7.0)])

    def test_shopping_video_type_dispatches_video_executor(self):
        events = []

        class Device:
            def click(self, x, y):
                events.append(("click", x, y))

        do_task = load_function(
            "点淘购物赚钱.py",
            "do_task",
            {
                "d": types.SimpleNamespace(),
                "time": types.SimpleNamespace(
                    sleep=lambda _seconds: None,
                    time=lambda: 0.0,
                ),
                "check_can_open": lambda _device: None,
                "detect_entered_media_type": lambda _tp, _name: "video",
                "execute_video_task": lambda *_args, **_kwargs: events.append("video"),
                "back_to_task": lambda *_args, **_kwargs: events.append("back"),
                "TASK_BTN_KW": [],
            },
        )

        do_task("video", 60)

        self.assertEqual(events, ["video", "back"])

    def test_shopping_live_type_does_not_dispatch_video_executor(self):
        events = []

        class Clock:
            def __init__(self):
                self.now = 0.0

            def time(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        clock = Clock()
        do_task = load_function(
            "点淘购物赚钱.py",
            "do_task",
            {
                "d": types.SimpleNamespace(),
                "time": clock,
                "check_can_open": lambda _device: None,
                "detect_entered_media_type": lambda _tp, _name: "live",
                "execute_video_task": lambda *_args, **_kwargs: events.append("video"),
                "get_ocr_text_blocks": lambda _device: [],
                "back_to_task": lambda *_args, **_kwargs: events.append("back"),
                "TASK_BTN_KW": [],
                "screen_width": 1080,
                "screen_height": 2400,
            },
        )

        do_task("live", 1, "看视频60秒")

        self.assertEqual(events, ["back"])

    def test_yuanbao_center_routes_video_name_to_video(self):
        match_task_type = load_function("元宝中心小任务.py", "match_task_type")

        self.assertEqual(match_task_type("看视频60秒(4/10)"), "video")

    def test_synthesis_routes_video_name_to_video(self):
        match_task_type = load_function(
            "合成百元大红包.py",
            "match_task_type",
            {
                "GUESS_PRICE_KEYWORDS": ["猜价格"],
                "VIDEO_KEYWORDS": ["看视频"],
                "LIVE_KEYWORDS": ["看视频", "直播"],
                "BROWSE_KEYWORDS": ["浏览"],
            },
        )

        self.assertEqual(match_task_type("看视频60秒(4/10)"), "video")

    def test_sleep_routes_live_name_to_live_executor(self):
        events = []

        class Device:
            def click(self, x, y):
                events.append(("click", x, y))

            def press(self, key):
                events.append(("press", key))

        do_bubble_task = load_function(
            "睡觉赚元宝.py",
            "do_bubble_task",
            {
                "d": Device(),
                "time": types.SimpleNamespace(sleep=lambda _seconds: None),
                "execute_live_task": lambda *_args, **_kwargs: events.append("live"),
                "execute_video_task": lambda *_args, **_kwargs: events.append("video"),
                "click_device_point": lambda *_args: events.append("entry"),
                "log_task_completed": lambda *_args: None,
            },
        )

        do_bubble_task("看直播60秒", 100, 200)

        self.assertEqual(events, ["entry", "live", ("press", "back")])

    def test_sleep_video_task_uses_shared_video_swipe_default(self):
        video_calls = []

        class Device:
            def click(self, x, y):
                video_calls.append(("click", x, y))

        def record_video_task(*args, **kwargs):
            video_calls.append((args, kwargs))

        do_bubble_task = load_function(
            "睡觉赚元宝.py",
            "do_bubble_task",
            {
                "d": Device(),
                "time": types.SimpleNamespace(sleep=lambda _seconds: None),
                "execute_live_task": lambda *_args, **_kwargs: None,
                "execute_video_task": record_video_task,
                "click_device_point": lambda *_args: video_calls.append("entry"),
                "log_task_completed": lambda *_args: None,
            },
        )

        do_bubble_task("看视频60秒", 100, 200)

        self.assertEqual(video_calls[0], "entry")
        self.assertNotIn("extra_swipes", video_calls[1][1])


if __name__ == "__main__":
    unittest.main()
