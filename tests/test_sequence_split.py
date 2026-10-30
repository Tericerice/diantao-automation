"""连通性入口 / 下滑轮次拆分与断点复用；不连接手机。"""
import argparse
import ast
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from task_checkpoint import run_step

ROOT = Path(__file__).resolve().parents[1]
ENTRY_NAMES = (
    "打工赚元宝", "睡觉赚元宝", "签到赢元宝",
    "购物赚钱", "摇一摇", "走路赚元宝",
)


def load_functions(filename, names, namespace):
    path = ROOT / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"),
         namespace)
    return namespace


def connectivity_main(monkeypatch, tmp_path, args, calls):
    routes = tuple((name, lambda device: None) for name in ENTRY_NAMES)
    namespace = {
        "argparse": argparse,
        "sys": SimpleNamespace(stdout=SimpleNamespace()),
        "ENTRY_ROUTES": routes,
        "ATTEMPTS_PER_ENTRY": 3,
        "run_step": run_step,
        "connect_device": lambda: SimpleNamespace(
            window_size=lambda: (1264, 2780)
        ),
        "_run_attempt": lambda device, name, nav, sw, sh, index: calls.append(
            (name, index)
        ),
    }
    load_functions("连通性脚本.py", {"_entry_choices", "main"}, namespace)
    monkeypatch.setenv("DIANTAO_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("DIANTAO_CHECKPOINT_SCOPE", "root")
    monkeypatch.setattr(sys, "argv", ["连通性脚本.py", *args])
    return namespace["main"]


def swipe_main(monkeypatch, args, keys):
    rounds = [
        {"label": str(index), "name": f"round{index}",
         "swipe_seconds": 10, "nav_func": None}
        for index in range(1, 7)
    ]

    def fake_run_step(key, checkpoint_label, function, *args, **kwargs):
        keys.append(key)

    namespace = {
        "argparse": argparse,
        "sys": SimpleNamespace(stdout=SimpleNamespace(encoding="utf-8")),
        "ROUNDS_CONFIG": rounds,
        "run_step": fake_run_step,
        "run_round": lambda **kwargs: None,
    }
    load_functions("一键下滑.py", {"_round_choices", "main"}, namespace)
    monkeypatch.setattr(sys, "argv", ["一键下滑.py", *args])
    return namespace["main"]


def test_selected_connectivity_attempt_is_not_replayed(monkeypatch, tmp_path):
    calls = []
    main = connectivity_main(
        monkeypatch, tmp_path, ["--entry-index", "2", "--attempt", "1"], calls,
    )

    main()
    main()

    assert calls == [("睡觉赚元宝", 1)]


def test_selected_connectivity_entry_runs_all_three_attempts(monkeypatch, tmp_path):
    calls = []
    main = connectivity_main(
        monkeypatch, tmp_path, ["--entry-index", "3"], calls,
    )

    main()

    assert calls == [
        ("签到赢元宝", 1), ("签到赢元宝", 2), ("签到赢元宝", 3),
    ]


def test_connectivity_attempt_requires_entry(monkeypatch, tmp_path):
    calls = []
    main = connectivity_main(
        monkeypatch, tmp_path, ["--attempt", "1"], calls,
    )

    with pytest.raises(SystemExit):
        main()

    assert calls == []


def test_swipe_round_selection_runs_only_selected_round(monkeypatch):
    keys = []
    main = swipe_main(monkeypatch, ["--round", "3"], keys)

    main()

    assert keys == ["swipe-3"]


def test_swipe_without_round_selection_runs_all_rounds(monkeypatch):
    keys = []
    main = swipe_main(monkeypatch, [], keys)

    main()

    assert keys == [f"swipe-{index}" for index in range(1, 7)]
