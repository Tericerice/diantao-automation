import importlib.util
from pathlib import Path

from task_rescan import build_rescan_rounds


def test_build_rescan_rounds_when_selected_tasks_include_targets() -> None:
    # Given: the selected tasks include targets and an explicitly excluded task.
    selected = [
        {"name": "签到赢元宝"},
        {"name": "点淘鸭摇一摇额外元宝"},
        {"name": "点淘鸭钻石任务"},
        {"name": "淘金币任务"},
    ]

    # When: the two permitted restart-and-rescan rounds are planned.
    rounds = build_rescan_rounds(selected)

    # Then: only the requested task types are scanned in both rounds.
    assert [[task["name"] for task in task_round] for task_round in rounds] == [
        ["签到赢元宝", "点淘鸭钻石任务"],
        ["签到赢元宝", "点淘鸭钻石任务"],
    ]


def test_build_rescan_rounds_when_no_target_is_selected() -> None:
    # Given: no selected task needs the restart-and-rescan policy.
    selected = [{"name": "淘金币任务"}]

    # When: restart-and-rescan rounds are planned.
    rounds = build_rescan_rounds(selected)

    # Then: no extra run is scheduled.
    assert rounds == ()


def test_main_runs_only_target_tasks_in_two_rescan_rounds(
    monkeypatch,
) -> None:
    # Given: selected tasks include a normal task, a target, and the excluded extra-yuanbao task.
    module_path = Path(__file__).parents[1] / "全部执行.py"
    spec = importlib.util.spec_from_file_location("all_execution", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tasks = [
        {"name": "淘金币任务", "file": "coins.py", "timeout": 1},
        {"name": "签到赢元宝", "file": "sign.py", "timeout": 1},
        {"name": "点淘鸭摇一摇额外元宝", "file": "extra.py", "timeout": 1},
    ]
    executed_names: list[str] = []

    def run_task(task):
        executed_names.append(task["name"])
        return task["name"], True, 0

    monkeypatch.setattr(module, "load_task_config", lambda: tasks)
    monkeypatch.setattr(module, "run_task", run_task)
    monkeypatch.setattr(module, "save_run_log", lambda results, elapsed: None)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    module.stop_flag = False

    # When: the main scheduler completes its initial execution and two rescan rounds.
    module.main()

    # Then: the extra-yuanbao task only runs in the initial execution.
    assert executed_names == [
        "淘金币任务",
        "签到赢元宝",
        "点淘鸭摇一摇额外元宝",
        "签到赢元宝",
        "签到赢元宝",
    ]
