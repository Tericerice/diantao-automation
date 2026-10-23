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
