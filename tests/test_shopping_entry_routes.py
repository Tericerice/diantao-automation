import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("filename, extra_args", [("一键下滑.py", ()), ("连通性脚本.py", (1264, 2780))])
@pytest.mark.parametrize("found", [True, False])
def test_shopping_routes_require_ocr_and_never_click_fixed_position(filename, extra_args, found):
    tree = ast.parse((Path(__file__).resolve().parents[1] / filename).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_nav_to_shop")
    ocr = Mock(return_value=found)
    device = SimpleNamespace(click=Mock())
    namespace = {"_ocr_click_target": ocr}
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    if found:
        namespace["_nav_to_shop"](device, *extra_args)
    else:
        with pytest.raises(RuntimeError, match="领元宝兑权益"):
            namespace["_nav_to_shop"](device, *extra_args)
    ocr.assert_called_once_with(device, "领元宝兑权益")
    device.click.assert_not_called()
