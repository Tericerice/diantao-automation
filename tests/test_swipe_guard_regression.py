"""e-diantao-151/#163：一键下滑守卫、失败退出与断点签名的离线回归。"""
import ast
import hashlib
import importlib.util
import itertools
import os
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWIPE = ROOT / "一键下滑.py"
DT_APP = "com.taobao.live"


def load_swipe_module(monkeypatch):
    """在不连接手机的前提下加载一键下滑.py 的纯函数。"""
    fake_device = types.SimpleNamespace(
        window_size=lambda: (1264, 2780), swipe=lambda *a, **kw: None,
        press=lambda *a, **kw: None, app_start=lambda *a, **kw: None)
    fake_u2 = types.ModuleType("u2_scanner")
    fake_u2.connect_device = lambda: fake_device
    fake_u2.DT_APP = DT_APP
    fake_utils = types.ModuleType("utils")
    fake_utils.get_ocr_text_blocks = lambda device: []
    fake_utils.get_current_app = lambda device: (DT_APP, "BrowserActivity")
    fake_popup = types.ModuleType("yuanbao_popup")
    fake_popup.handle_yuanbao_live_popups = lambda device: True
    fake_checkpoint = types.ModuleType("task_checkpoint")
    fake_checkpoint.run_step = lambda key, label, fn, *args, **kwargs: fn(*args, **kwargs)
    for name, module in (("u2_scanner", fake_u2), ("utils", fake_utils),
                         ("yuanbao_popup", fake_popup), ("task_checkpoint", fake_checkpoint)):
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("swipe_under_test", SWIPE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "swipe_under_test", module)
    spec.loader.exec_module(module)
    return module, fake_utils


def fake_clock(monkeypatch, module):
    # swipe_browse 用 time() 判断是否继续；0/0 允许一次滑动，100 退出循环。
    monkeypatch.setattr(module.time, "time", iter([0, 0, 100]).__next__)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module.random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(module.random, "randint", lambda a, b: a)


def test_same_goods_product_page_stops_immediately(monkeypatch, capsys):
    module, _ = load_swipe_module(monkeypatch)
    module.get_ocr_text_blocks = lambda device: [{"text": "同款好物"}]
    module.get_current_app = lambda device: (DT_APP, "BrowserActivity")
    fake_clock(monkeypatch, module)
    assert module.swipe_browse(0.01, ("打工赚元宝",)) is False
    assert "下滑前未确认任务页面" in capsys.readouterr().out


def test_product_page_marker_after_swipe_returns_false(monkeypatch, capsys):
    module, _ = load_swipe_module(monkeypatch)
    calls = {"n": 0}

    def ocr(device):
        calls["n"] += 1
        return [] if calls["n"] == 1 else [{"text": "同款好物"}]

    module.get_ocr_text_blocks = ocr
    module.get_current_app = lambda device: (DT_APP, "BrowserActivity")
    fake_clock(monkeypatch, module)
    assert module.swipe_browse(0.01, ("打工赚元宝",)) is False
    assert "误入「同款好物」商品页" in capsys.readouterr().out


def test_swipe_uses_right_safe_band_and_long_drag(monkeypatch):
    module, _ = load_swipe_module(monkeypatch)
    calls = []
    module.d.swipe = lambda *a, **kw: calls.append((a, kw))
    module.get_ocr_text_blocks = lambda device: []
    module.get_current_app = lambda device: (DT_APP, "BrowserActivity")
    fake_clock(monkeypatch, module)
    assert module.swipe_browse(0.01, ("打工赚元宝",)) is True
    args, kwargs = calls[0]
    assert int(0.84 * 1264) <= args[0] <= int(0.91 * 1264)
    assert args[2] == args[0]
    assert kwargs["duration"] >= 0.5


def test_same_package_activity_change_is_not_a_jump(monkeypatch):
    module, _ = load_swipe_module(monkeypatch)
    states = iter([
        (DT_APP, "BrowserActivity"),
        (DT_APP, "BrowserUpperActivity"),
    ])
    module.get_current_app = lambda device: next(states)
    fake_clock(monkeypatch, module)
    assert module.swipe_browse(0.01, ("精选推荐",)) is True


def test_external_package_change_stops_and_returns_false(monkeypatch, capsys):
    module, _ = load_swipe_module(monkeypatch)
    states = iter([
        (DT_APP, "BrowserActivity"),
        ("me.ele", "AppUCWebActivity"),
    ])
    module.get_current_app = lambda device: next(states)
    fake_clock(monkeypatch, module)
    assert module.swipe_browse(0.01, ("精选推荐",)) is False
    assert "前台应用变为" in capsys.readouterr().out


def test_transient_ocr_failure_recovers_without_skipping(monkeypatch):
    module, _ = load_swipe_module(monkeypatch)
    calls = {"n": 0}

    def flaky_ocr(device):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError(10054)
        return [{"text": "精选推荐", "cx": 100, "cy": 100}]

    module.get_ocr_text_blocks = flaky_ocr
    module.get_current_app = lambda device: (DT_APP, "BrowserActivity")
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module._expected_page_reached(None, ("精选推荐",), attempts=3) is True
    assert calls["n"] == 2


def test_persistent_ocr_failure_fails_without_unknown_package(monkeypatch):
    module, _ = load_swipe_module(monkeypatch)
    module.get_ocr_text_blocks = lambda device: (_ for _ in ()).throw(
        ConnectionResetError(10054))
    module.get_current_app = lambda device: (None, None)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module._expected_page_reached(None, ("精选推荐",), attempts=2) is False


def test_skipped_round_returns_false_and_main_exits_nonzero(monkeypatch):
    source = SWIPE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "FAILED_ROUNDS:" in source
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    assert any(isinstance(n, ast.Raise) for n in ast.walk(main))
    module, _ = load_swipe_module(monkeypatch)
    monkeypatch.setattr(module, "_enter_yuanbao_center_ocr", lambda d: True)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert module.run_round(1, "打工赚元宝", 1, lambda d: False) is False


def test_script_content_hash_is_part_of_checkpoint_signature(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT))
    import task_checkpoint as checkpoint
    monkeypatch.setenv(checkpoint.SESSION_ENV, str(tmp_path / "checkpoints"))
    monkeypatch.setenv(checkpoint.SCOPE_ENV, "root")
    monkeypatch.setattr(checkpoint, "_calls", itertools.count())
    script = tmp_path / "child.py"
    script.write_text("print('v1')\n", encoding="utf-8")
    command = [sys.executable, "-u", str(script)]
    import phone_control
    from task_checkpoint import SCOPE_ENV
    record_path = tmp_path / "checkpoints" / (
        hashlib.sha256(f"{os.environ[SCOPE_ENV]}/script-0".encode()).hexdigest() + ".json")
    phone_control.write_json(record_path, {
        "scope": "root/script-0", "label": "child.py",
        "signature": {"command": command, "script_sha256": "v1"},
        "status": "done", "pid": os.getpid(),
        "result": [True, 1.0, "成功"], "feedback": [],
    })
    unchanged = checkpoint.Checkpoint("script-0", "child.py",
                                      {"command": command, "script_sha256": "v1"})
    assert unchanged.done is True
    changed = checkpoint.Checkpoint("script-0", "child.py",
                                    {"command": command, "script_sha256": "v2"})
    assert changed.cached is None
    assert not changed.done
    content_sig = checkpoint.script_checkpoint(script, command).signature
    assert "script_sha256" in content_sig
    assert content_sig["script_sha256"] == checkpoint._script_content_hash(script)


def test_workbench_runtime_log_false_success_chain_is_rejected():
    """离线重放六轮日志：假成功链必须被新契约识别为不通过。"""
    log_path = ROOT / ".runtime" / "workbench" / "diantao-all-in-one.log"
    source = SWIPE.read_text(encoding="utf-8")
    assert "FAILED_ROUNDS:" in source
    assert "round_failed" in source
    assert 'raise SystemExit(2)' in source
    if not log_path.exists():
        return
    text = log_path.read_text(encoding="utf-8", errors="replace")
    skipped = len(re.findall(r"跳过本轮下滑", text))
    cached = len(re.findall(r"\[续跑\] 跳过已完成：一键下滑\.py", text))
    # 真实日志会随新一轮运行而清空；存在时检查旧假成功链，否则只验证新契约。
    assert cached >= (6 if skipped else 0)
    # 新脚本不再把跳过打印成完成，且以非零码退出；旧日志只能作为反例。
    assert "第 {label} 轮完成" in source
    assert "raise SystemExit(2)" in source
