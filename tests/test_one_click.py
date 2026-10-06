import importlib.util
from pathlib import Path
from threading import Event


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("one_click", ROOT / "一键顺序执行.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_sequence_continues_after_failure(monkeypatch):
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        return len(calls) != 2, 0, "成功" if len(calls) != 2 else "超时"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute() == 1
    assert calls == [
        "连通性脚本.py", "一键下滑.py", "主播打卡粉丝礼.py", "签到赢元宝.py",
        "睡觉赚元宝.py", "点淘鸭钻石任务.py", "点淘鸭摇一摇.py",
        "点淘购物赚钱.py", "打工得体力.py",
    ]


def test_stop_prevents_next_script(monkeypatch):
    stop = Event()
    calls = []

    def fake_run(filepath, **kwargs):
        calls.append(filepath.name)
        stop.set()
        return False, 0, "用户停止"

    monkeypatch.setattr(module, "run_script", fake_run)
    assert module.execute(stop) == 130
    assert calls == ["连通性脚本.py"]


def test_missing_script_prevents_partial_run(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "SCRIPT_DIR", tmp_path)
    monkeypatch.setattr(module, "run_script", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    assert module.execute() == 1
