import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("filename, function_name, extra_args", [
    ("点淘购物赚钱.py", "enter_shopping_tasks", ()),
    ("一键下滑.py", "_nav_to_shop", ()),
    ("连通性脚本.py", "_nav_to_shop", (1264, 2780)),
])
def test_shopping_routes_click_fixed_card_without_requiring_entry_text(filename, function_name, extra_args):
    tree = ast.parse((Path(__file__).resolve().parents[1] / filename).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function_name)
    ocr = Mock(side_effect=AssertionError("入口改名，不应依赖文字"))
    device = SimpleNamespace(click=Mock())
    namespace = {"_ocr_click_target": ocr, "d": device,
                 "time": SimpleNamespace(sleep=Mock()),
                 "OCR_CLICK_WAIT_SECONDS": 5, "ACTION_SETTLE_SECONDS": 5}
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    args = () if function_name == "enter_shopping_tasks" else (device, *extra_args)
    namespace[function_name](*args)
    ocr.assert_not_called()
    device.click.assert_called_once_with(934, 1530)


def load_shopping_navigation(namespace):
    filename = "点淘购物赚钱.py"
    tree = ast.parse((Path(__file__).resolve().parents[1] / filename).read_text(encoding="utf-8"))
    names = {
        "_find_ocr_block",
        "_find_show_more_block",
        "_shopping_task_list_open",
        "_shopping_task_list_ready",
        "_scan_shopping_page",
        "unlock_shopping_task_list",
        "navigate",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), namespace)
    return namespace["navigate"]


@pytest.mark.parametrize("pages, success, clicks", [
    ([[{"text": "点淘鸭家园"}]], False, []),
    ([[{"text": "查看更多", "cx": 634, "cy": 966}], [{"text": "点淘鸭家园"}]], False, [(634, 966)]),
    ([[{"text": "查看更多", "cx": 634, "cy": 966}], [{"text": "做任务领元宝"}]], True, [(634, 966)]),
])
def test_shopping_navigation_requires_confirmed_task_list(pages, success, clicks):
    device = Mock()
    namespace = {
        "d": device, "DT_APP": "com.taobao.live",
        "time": SimpleNamespace(sleep=Mock()),
        "click_ocr_text": Mock(return_value=True),
        "handle_yuanbao_live_popups": Mock(return_value=True),
        "enter_shopping_tasks": Mock(), "get_ocr_text_blocks": Mock(side_effect=pages),
        "re": __import__("re"), "TASK_BTN_KW": ["去完成", "去浏览"],
    }
    navigate = load_shopping_navigation(namespace)
    assert navigate() is success
    assert [call.args for call in device.click.call_args_list] == clicks


def test_shopping_navigation_signs_in_before_opening_quick_claim_list():
    pages = [
        [
            {"text": "立即签到", "cx": 632, "cy": 890},
            {"text": "快速领", "cx": 720, "cy": 470},
            {"text": "去完成", "cx": 900, "cy": 1200},
        ],
        [{"text": "快速领", "cx": 720, "cy": 470}],
        [{"text": "查看更多", "cx": 500, "cy": 780}],
        [{"text": "做任务领元宝"}],
    ]
    device = Mock()
    namespace = {
        "d": device, "DT_APP": "com.taobao.live",
        "time": SimpleNamespace(sleep=Mock()),
        "click_ocr_text": Mock(return_value=True),
        "handle_yuanbao_live_popups": Mock(return_value=True),
        "enter_shopping_tasks": Mock(), "get_ocr_text_blocks": Mock(side_effect=pages),
        "re": __import__("re"), "TASK_BTN_KW": ["去完成", "去浏览"],
    }
    assert load_shopping_navigation(namespace)() is True
    assert [call.args for call in device.click.call_args_list] == [
        (632, 890),
        (720, 470),
        (500, 780),
    ]


def load_task_area_helpers():
    filename = "点淘购物赚钱.py"
    tree = ast.parse((Path(__file__).resolve().parents[1] / filename).read_text(encoding="utf-8"))
    names = {"_find_show_more_block", "_task_area_top", "_task_buttons"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"re": __import__("re")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), namespace)
    return namespace


def test_task_buttons_use_dynamic_anchor_instead_of_fixed_threshold():
    # 双11 快速领面板标题在 782，看直播按钮在 838，旧版 852 阈值会把它全部过滤。
    blocks = [
        {"text": "做任务领元宝", "cx": 631, "cy": 782},
        {"text": "看直播60秒(2/10)", "cx": 416, "cy": 976},
        {"text": "去完成", "cx": 1078, "cy": 838},
        {"text": "查看3个精选宝贝(3/3)", "cx": 468, "cy": 1212},
        {"text": "已完成", "cx": 1078, "cy": 1258},
    ]
    namespace = load_task_area_helpers()
    assert namespace["_task_area_top"](blocks) == 782
    buttons = namespace["_task_buttons"](blocks)
    assert [(b["cx"], b["cy"]) for b in buttons] == [(1078, 838)]


def test_task_area_falls_back_to_tab_row_when_panel_title_absent():
    # 面板尚未展开时没有标题，只能用标签行定位任务区域。
    blocks = [
        {"text": "快速领", "cx": 660, "cy": 642},
        {"text": "去完成", "cx": 1078, "cy": 838},
        {"text": "领取", "cx": 1102, "cy": 466},
    ]
    namespace = load_task_area_helpers()
    assert namespace["_task_area_top"](blocks) == 642
    assert [b["cy"] for b in namespace["_task_buttons"](blocks)] == [838]


def test_show_more_matcher_ignores_media_page_text():
    namespace = load_task_area_helpers()
    assert namespace["_find_show_more_block"]([{"text": "查看更多视频", "cx": 1, "cy": 2}]) is None
    block = {"text": "查看更多", "cx": 631, "cy": 1154}
    assert namespace["_find_show_more_block"]([block]) is block
