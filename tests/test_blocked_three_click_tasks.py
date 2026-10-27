"""Three-product tasks must stop before any device action, including legacy routes."""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from task_exclusions import is_blocked_boutique_task


ROOT = Path(__file__).resolve().parents[1]
BLOCKED = (
    "查看3个特惠卖场宝贝(0/3)",
    "查看三件优惠宝贝",
    "看３个优 惠宝贝",
    "点击三次精选商品",
    "查看3个精选",
    "查看3个(0/3)",
    "查看3个(0/10)",
    "点击3次领优惠",
    "查看优惠商品3次",
    "浏览优惠宝贝(0/3)",
)


def load_function(filename, name, **namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8-sig"))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace.update(re=re, is_blocked_boutique_task=is_blocked_boutique_task)
    exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("name", BLOCKED)
def test_three_product_names_are_excluded(name):
    assert is_blocked_boutique_task(name)


@pytest.mark.parametrize("name", [
    "浏览精选推荐60秒(0/3)", "浏览省钱专区60秒",
    "搜索宝贝后浏览30秒(0/3)", "看直播60秒(0/3)", "看3个视频",
])
def test_regular_browse_search_and_media_remain_allowed(name):
    assert not is_blocked_boutique_task(name)


def test_legacy_three_click_executor_never_touches_phone():
    device = Mock()
    device.window_size.return_value = (1264, 2780)
    executor = load_function(
        "u2_scanner.py", "click_three_selected_items",
        time=SimpleNamespace(sleep=Mock()),
        random=SimpleNamespace(uniform=lambda *args: 0),
    )
    assert executor(device) is False
    assert device.mock_calls == []


@pytest.mark.parametrize("name,kind", [
    ("查看3个特惠卖场宝贝", "browse"),
    ("点击3次领优惠", "click_three"),
    ("OCR未完整识别任务名称", "click_three"),
])
def test_coin_executor_rejects_names_and_legacy_type_before_entry_click(name, kind):
    device = Mock()
    executor = load_function(
        "淘金币任务.py", "exec_task", d=device,
        time=SimpleNamespace(sleep=Mock()), screen_width=1264, screen_height=2780,
        browse_loop=Mock(),
    )
    assert executor({"name": name, "type": kind, "cx": 1000, "cy": 1500}) is False
    assert device.mock_calls == []


@pytest.mark.parametrize("name", BLOCKED)
def test_shared_execution_gate_rejects_blocked_names_without_clicking(name):
    device = Mock()
    executor = load_function(
        "u2_scanner.py", "execute_task", time=SimpleNamespace(sleep=Mock()),
        handle_open_allow_popup=Mock(), is_search_low_price_task=lambda _: False,
        execute_browse_task=Mock(),
    )
    assert executor(device, name, 1000, 1500) is False
    assert device.mock_calls == []


@pytest.mark.parametrize("parts", [
    ("查看3个", "特惠卖场宝贝(0/10)"),
    ("查看３个优", "惠宝贝(0/3)"),
    ("查看",),
])
def test_shopping_classifier_skips_split_or_truncated_click_tasks(parts):
    classifier = load_function(
        "点淘购物赚钱.py", "detect_task_name_before_click",
        is_blacklisted=is_blocked_boutique_task, _TITLE_BLACKLIST=[],
        is_search_low_price_task=lambda _: False,
    )
    blocks = [{"text": part, "cx": 300 + index * 250, "cy": 1500}
              for index, part in enumerate(parts)]
    button = {"text": "去完成", "cx": 1000, "cy": 1500}
    assert classifier([*blocks, button], button)[0] == "skip"


def test_shopping_legacy_click_type_cannot_run_with_missing_name():
    device = Mock()
    executor = load_function("点淘购物赚钱.py", "do_task", d=device)
    assert executor("click", 0) is False
    assert device.mock_calls == []
