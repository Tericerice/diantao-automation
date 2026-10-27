"""屏蔽“查看3个精选宝贝 / 精选宝贝”类任务的回归测试。

不连接设备：用 AST 读取各脚本的常量，并直接验证 utils/u2_scanner 的黑名单函数。
优惠/特惠商品的三次点击也排除，普通精选浏览继续保留。
"""
import ast
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from task_exclusions import is_blocked_boutique_task

ROOT = Path(__file__).resolve().parents[1]

BLOCKED_NAMES = (
    "查看3个精选宝贝",
    "查看3个精选宝贝(0/3)",
    "查看3个精选宝贝 (0/3) + 150 160000 退款扣回",
    "看3个精选宝贝",
    "精选宝贝",
    "查看 3 个精 选宝贝",
    "查看3个精\u200b选宝贝",
    "查看3个特惠卖场宝贝",
    "查看3个特惠卖场宝贝（0/10）",
    "查看三件优惠宝贝",
    "查看3个精选",
)
ALLOWED_NAMES = (
    "浏览精选推荐60秒",
    "浏览精选推荐",
    "看直播60秒",
    "猜价格游戏",
)


def _load_module(filename, module_name):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _literal_assignments(filename):
    """读取模块顶层的字面量常量，不执行脚本（避免连接设备）。"""
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8-sig"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = value
    return values


@pytest.mark.parametrize("name", BLOCKED_NAMES)
def test_utils_blacklist_blocks_boutique_tasks(name):
    assert _load_module("utils.py", "utils_under_test").is_blacklisted(name)


@pytest.mark.parametrize("name", BLOCKED_NAMES)
def test_u2_scanner_blacklist_blocks_boutique_tasks(name):
    assert _load_module("u2_scanner.py", "u2_scanner_under_test").is_blacklisted(name)


@pytest.mark.parametrize("name", ALLOWED_NAMES)
def test_shared_blacklists_keep_marketplace_boutique_and_other_tasks(name):
    assert not _load_module("utils.py", "utils_under_test").is_blacklisted(name)
    assert not _load_module("u2_scanner.py", "u2_scanner_under_test").is_blacklisted(name)


@pytest.mark.parametrize("filename", [
    "打工得体力.py", "元宝中心小任务.py", "签到赢元宝.py", "走路赚元宝.py",
])
def test_script_blacklists_contain_boutique_keyword(filename):
    keywords = _literal_assignments(filename)["BLACKLIST_KEYWORDS"]
    assert "精选宝贝" in keywords


def test_sleep_script_blocks_boutique_bubbles():
    values = _literal_assignments("睡觉赚元宝.py")
    assert "精选宝贝" in values["BLOCKED_TASK_KEYWORDS"]


def test_diamond_whitelist_drops_both_marketplace_and_boutique_clicks():
    whitelist = _literal_assignments("点淘鸭钻石任务.py")["WHITELIST"]
    assert "查看3个特惠卖场宝贝" not in whitelist
    assert "查看3个精选宝贝" not in whitelist
    assert "精选宝贝" not in whitelist


def test_shake_whitelist_drops_boutique():
    whitelist = _literal_assignments("点淘鸭摇一摇.py")["TASK_WHITELIST"]
    assert "查看3个精选宝贝" not in whitelist
    assert "精选宝贝" not in whitelist


@pytest.mark.parametrize("filename,function,kwargs", [
    ("签到赢元宝.py", "exec_browse", dict(btn_cx=100, btn_cy=200)),
    ("打工得体力.py", "exec_browse", dict(btn_cx=100, btn_cy=200)),
    ("元宝中心小任务.py", "execute_task", dict(btn_cx=100, btn_cy=200)),
    ("点淘鸭摇一摇.py", "do_task", dict(btn_cx=100, btn_cy=200)),
    ("点淘鸭钻石任务.py", "do_task", dict(btn_cx=100, btn_cy=200)),
    ("点淘购物赚钱.py", "do_task", dict(tp="click", sec=0)),
    ("睡觉赚元宝.py", "do_bubble_task", dict(btn_cx=100, btn_cy=200)),
])
@pytest.mark.parametrize("name", [
    "查看3个精选宝贝", "看3个精选宝贝(0/3)", "查看3个精 选宝贝",
    "查看3个特惠卖场宝贝", "查看三件优惠宝贝", "查看3个精选",
])
def test_execution_entrypoints_never_touch_device_for_blocked_task(filename, function, kwargs, name):
    # 仅加载执行函数，避免模块顶层的设备连接及导航。
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
    device = Mock()
    namespace = {"d": device, "is_blocked_boutique_task": is_blocked_boutique_task}
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    keyword = "name" if function == "do_bubble_task" else "task_name"
    assert namespace[function](**kwargs, **{keyword: name}) is False
    assert device.mock_calls == []
