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


@pytest.mark.parametrize("pages, success, clicks", [
    ([[{"text": "点淘鸭家园"}]], False, []),
    ([[{"text": "查看更多", "cx": 634, "cy": 966}], [{"text": "点淘鸭家园"}]], False, [(634, 966)]),
    ([[{"text": "查看更多", "cx": 634, "cy": 966}], [{"text": "做任务领元宝"}]], True, [(634, 966)]),
])
def test_shopping_navigation_requires_confirmed_task_list(pages, success, clicks):
    filename = "点淘购物赚钱.py"
    tree = ast.parse((Path(__file__).resolve().parents[1] / filename).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "navigate")
    device = Mock()
    namespace = {
        "d": device, "DT_APP": "com.taobao.live",
        "time": SimpleNamespace(sleep=Mock()),
        "click_ocr_text": Mock(return_value=True),
        "handle_yuanbao_live_popups": Mock(return_value=True),
        "enter_shopping_tasks": Mock(), "get_ocr_text_blocks": Mock(side_effect=pages),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    assert namespace["navigate"]() is success
    assert [call.args for call in device.click.call_args_list] == clicks
