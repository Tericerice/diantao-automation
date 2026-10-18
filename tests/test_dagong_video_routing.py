import ast
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_function(filename, function_name, extra_globals=None):
    source = (ROOT / filename).read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=filename)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    namespace = {"re": __import__("re")}
    if extra_globals:
        namespace.update(extra_globals)
    exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
    return namespace[function_name]


def load_named_mapping(name):
    source = (ROOT / "打工得体力.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename="打工得体力.py")
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == name
    )
    namespace = {}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]), "打工得体力.py", "exec"), namespace)
    return namespace[name]


def load_match_task_type():
    normalize_task_name = load_function("打工得体力.py", "normalize_task_name")
    return load_function(
        "打工得体力.py",
        "match_task_type",
        {
            "normalize_task_name": normalize_task_name,
            "TASK_TYPE_MAP": load_named_mapping("TASK_TYPE_MAP"),
            "TASK_CATEGORY_MAP": load_named_mapping("TASK_CATEGORY_MAP"),
        },
    )


def load_parse_tasks_from_blocks():
    normalize_task_name = load_function("打工得体力.py", "normalize_task_name")
    match_task_type = load_function(
        "打工得体力.py",
        "match_task_type",
        {
            "normalize_task_name": normalize_task_name,
            "TASK_TYPE_MAP": load_named_mapping("TASK_TYPE_MAP"),
            "TASK_CATEGORY_MAP": load_named_mapping("TASK_CATEGORY_MAP"),
        },
    )
    detect_task_name = load_function(
        "打工得体力.py",
        "detect_task_name",
        {
            "re": __import__("re"),
            "NAME_ABOVE_GAP": 200,
            "NAME_H_OFFSET": 690,
        },
    )
    return load_function(
        "打工得体力.py",
        "parse_tasks_from_blocks",
        {
            "DONE_BTN_KEYWORDS": ["去完成"],
            "detect_task_name": detect_task_name,
            "BLACKLIST_KEYWORDS": [],
            "match_task_type": match_task_type,
        },
    )


class DagongVideoRoutingTest(unittest.TestCase):
    def test_exact_video_name_maps_to_video(self):
        match_task_type = load_match_task_type()

        self.assertEqual(match_task_type("看视频60秒(0/1)"), "video")

    def test_exact_browse_name_maps_to_browse(self):
        match_task_type = load_match_task_type()

        self.assertEqual(match_task_type("浏览精选推荐60秒(0/1)"), "browse")

    def test_browse_video_task_name_has_an_explicit_video_mapping(self):
        match_task_type = load_match_task_type()

        self.assertEqual(match_task_type("浏览看视频60秒"), "video")

    def test_single_category_word_maps_without_a_full_name_entry(self):
        match_task_type = load_match_task_type()

        self.assertEqual(match_task_type("视频任务60秒"), "video")
        self.assertEqual(match_task_type("直播任务90秒"), "live")
        self.assertEqual(match_task_type("浏览任务60秒"), "browse")

    def test_name_without_category_word_remains_unknown(self):
        match_task_type = load_match_task_type()

        self.assertEqual(match_task_type("特殊任务60秒"), "other")

    def test_dagong_video_name_stays_on_video_executor(self):
        parse_tasks_from_blocks = load_parse_tasks_from_blocks()

        blocks = [
            {"text": "看视频60秒(0/1)", "cx": 400, "cy": 100},
            {"text": "去完成", "cx": 1080, "cy": 160},
        ]

        tasks = parse_tasks_from_blocks(blocks)

        self.assertEqual(
            tasks,
            [("video", "看视频60秒(0/1)", 1080, 160)],
        )

    def test_dagong_other_video_names_stay_on_video_executor(self):
        parse_tasks_from_blocks = load_parse_tasks_from_blocks()

        blocks = [
            {"text": "浏览看视频60秒(0/1)", "cx": 400, "cy": 100},
            {"text": "去完成", "cx": 1080, "cy": 160},
        ]

        tasks = parse_tasks_from_blocks(blocks)

        self.assertEqual(
            tasks,
            [("video", "浏览看视频60秒(0/1)", 1080, 160)],
        )

    def test_dagong_video_passes_explicit_duration_and_two_extra_swipes(self):
        calls = []
        parse_seconds = load_function("打工得体力.py", "parse_seconds")

        class Device:
            def click(self, x, y):
                calls.append(("click", x, y))

            def swipe(self, *args, **kwargs):
                calls.append(("swipe", args, kwargs))

        def record_video_task(*args, **kwargs):
            calls.append(("video", args, kwargs))

        exec_video = load_function(
            "打工得体力.py",
            "exec_video",
            {
                "d": Device(),
                "time": types.SimpleNamespace(sleep=lambda _seconds: None),
                "screen_width": 1080,
                "screen_height": 2400,
                "parse_seconds": parse_seconds,
                "execute_video_task": record_video_task,
            },
        )

        exec_video(100, 200, "看视频60s")

        self.assertEqual(calls[0], ("click", 100, 200))
        self.assertEqual(calls[1][0], "video")
        self.assertEqual(calls[1][2]["duration"], 60)
        self.assertEqual(calls[1][2]["extra_swipes"], 7)
        self.assertEqual(calls[1][2]["swipe_interval_extra_seconds"], 1)
        self.assertTrue(calls[1][2]["verify_media_page"])
        self.assertTrue(calls[1][2]["initial_swipe"])


if __name__ == "__main__":
    unittest.main()
