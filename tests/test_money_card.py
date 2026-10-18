"""赚钱卡入口的导航与任务白名单回归测试。"""
import ast
import re
import sys
from unittest.mock import Mock
import pytest
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / "签到赢元宝.py"


@pytest.mark.parametrize("kind,name", [("live", "看直播60秒"), ("browse", "浏览精选推荐60秒")])
def test_money_card_returns_after_media_task(kind, name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    names = {"main", "exec_live", "exec_browse", "parse_seconds"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    device = Mock()
    local_browse = Mock(return_value=True)
    cloud_browse = Mock(side_effect=AssertionError("赚钱卡浏览不应等待云端 OCR"))
    live = Mock(return_value=True)
    scans = iter([[{"text": name}], [], [], [], []])
    ns = dict(re=re, sys=sys, d=device, time=SimpleNamespace(sleep=lambda _: None),
              navigate=lambda: True, find_money_card=lambda: True,
              get_ocr_text_blocks=lambda _: next(scans, []),
              parse_tasks_from_blocks=lambda *args: [(kind, name, 900, 600)],
              select_entry_tasks=lambda tasks, entry: tasks,
              execute_live_task=live, browse_task=cloud_browse,
              execute_browse_task=local_browse, show_today_summary=lambda: None)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    ns["main"]("赚钱卡")
    device.click.assert_called_once_with(900, 600)
    device.press.assert_called_once_with("back")
    if kind == "browse":
        local_browse.assert_called_once_with(device, min_duration=60, max_wait=90)
        cloud_browse.assert_not_called()
    else:
        live.assert_called_once_with(device, name, 900, 600)


@pytest.mark.parametrize("function,executor", [("exec_live", "execute_live_task"), ("exec_browse", "browse_task")])
def test_media_exception_still_attempts_return(function, executor):
    device = Mock()
    execute = load_function(function, d=device, time=SimpleNamespace(sleep=lambda _: None),
                            parse_seconds=lambda *args, **kwargs: 60,
                            **{executor: Mock(side_effect=RuntimeError("任务中断"))})
    with pytest.raises(RuntimeError, match="任务中断"):
        execute(900, 600, "看直播60秒" if function == "exec_live" else "浏览精选推荐60秒")
    device.press.assert_called_once_with("back")


def money_parser():
    names = {"parse_tasks_from_blocks", "parse_money_card_tasks", "detect_sign_task_name", "match_task_type"}
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = {"re": re, "NAME_ABOVE_GAP": 200, "NAME_H_OFFSET": 50,
                 "DONE_BTN_KEYWORDS": ["去完成", "去浏览", "去观看"], "BLACKLIST_KEYWORDS": ["购买", "下单"]}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["parse_tasks_from_blocks"]


def test_money_card_matches_full_names_left_of_buttons():
    blocks = [
        {"text": "看直播60秒", "cx": 250, "cy": 600},
        {"text": "去完成", "cx": 900, "cy": 610},
        {"text": "浏览精选推荐60秒", "cx": 300, "cy": 850},
        {"text": "去浏览", "cx": 900, "cy": 855},
    ]
    assert money_parser()(blocks, "赚钱卡") == [
        ("browse", "浏览精选推荐60秒", 900, 855),
        ("live", "看直播60秒", 900, 610),
    ]


def test_money_card_matches_above_button_with_ocr_spaces():
    blocks = [{"text": "浏览 精选推荐 60 秒", "cx": 250, "cy": 600},
              {"text": "去完成", "cx": 250, "cy": 760}]
    assert money_parser()(blocks, "赚钱卡") == [("browse", "浏览精选推荐60秒", 250, 760)]


def test_money_card_does_not_pair_unknown_or_distant_tasks():
    blocks = [{"text": "购买精选推荐60秒", "cx": 250, "cy": 600},
              {"text": "去完成", "cx": 900, "cy": 600},
              {"text": "看直播60秒", "cx": 250, "cy": 1000}]
    assert money_parser()(blocks, "赚钱卡") == []


def test_sign_parser_still_uses_original_column_layout():
    blocks = [{"text": "看直播60秒", "cx": 250, "cy": 600},
              {"text": "去完成", "cx": 250, "cy": 760}]
    assert money_parser()(blocks) == [("live", "看直播60秒", 250, 760)]


def test_money_card_preserves_guess_price_and_parses_sixty_seconds():
    blocks = [{"text": "玩1次猜价格", "cx": 250, "cy": 600},
              {"text": "去完成", "cx": 250, "cy": 760}]
    assert money_parser()(blocks, "赚钱卡") == [("guess_price", "玩1次猜价格", 250, 760)]
    parse = load_function("parse_seconds", re=re)
    assert parse("看直播60秒") == 60
    assert parse("浏览精选推荐60秒") == 60


def test_money_card_skips_ambiguous_pairing():
    blocks = [{"text": "看直播60秒", "cx": 200, "cy": 600},
              {"text": "浏览精选推荐60秒", "cx": 450, "cy": 600},
              {"text": "去完成", "cx": 900, "cy": 600}]
    assert money_parser()(blocks, "赚钱卡") == []


def load_function(name, **globals_):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = dict(globals_)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace[name]


def test_money_card_only_allows_three_activities():
    select = load_function("select_entry_tasks")
    tasks = [(kind, kind, 10, 20) for kind in ("live", "browse", "guess_price", "video")]
    assert select(tasks, "赚钱卡") == tasks[:3]
    assert select(tasks, "签到赢元宝") == tasks


def test_money_card_uses_exact_entry_without_sign_fallback():
    clicks = []
    selectors = []
    def device(**selector):
        selectors.append(selector)
        return SimpleNamespace(exists=lambda timeout: True)
    find = load_function(
        "find_money_card", d=device, MAX_SCROLL=2,
        click_u2_control=lambda *args: clicks.append(args[-1]),
        time=SimpleNamespace(sleep=lambda _: None),
    )
    assert find() is True
    assert selectors == [{"text": "赚钱卡"}]
    assert clicks == ["赚钱卡"]


def test_missing_money_card_stops_after_bounded_search():
    class Device:
        def __call__(self, **selector):
            return SimpleNamespace(exists=lambda timeout: False)
        def swipe(self, *args):
            pass
    find = load_function(
        "find_money_card", d=Device(), MAX_SCROLL=2, screen_width=1080,
        screen_height=2400, get_ocr_text_blocks=lambda _: [],
        time=SimpleNamespace(sleep=lambda _: None),
    )
    assert find() is False
