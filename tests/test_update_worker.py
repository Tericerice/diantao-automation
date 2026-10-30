import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location(
    "update_worker",
    Path(__file__).resolve().parents[1] / "workbench" / "update_worker.py",
)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

VERSION = "v0.3.1"
REQUIRED = {
    "启动大管家.cmd": "new launcher\n",
    "启动工作台.cmd": "new workbench\n",
    "配置本机.cmd": "new config\n",
    "local_config.py": "# new local config\n",
    "VERSION.json": json.dumps({"version": VERSION}),
    "workbench/app.py": "# new app\n",
    "workbench/updater.py": "# new updater\n",
    "workbench/update_worker.py": "# new worker\n",
    "workbench/uv.lock": "new lock\n",
}


def make_staging(tmp_path: Path, *, corrupt=False) -> Path:
    staging = tmp_path / "staging"
    files = {}
    for name, text in REQUIRED.items():
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        data = target.read_bytes()
        if corrupt and name == "workbench/app.py":
            data = b"corrupt"
        files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    (staging / "manifest.json").write_text(json.dumps({
        "schema": 1, "version": VERSION, "files": files,
    }), encoding="utf-8")
    return staging


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    (root / "workbench").mkdir(parents=True)
    (root / "workbench" / "app.py").write_text("# old app\n", encoding="utf-8")
    (root / "task_config.json").write_text('{"old": true}', encoding="utf-8")
    (root / ".env").write_text("PRIVATE=keep\n", encoding="utf-8")
    (root / ".runtime").mkdir()
    (root / ".runtime" / "keep.txt").write_text("runtime", encoding="utf-8")
    return root


def args(root, staging, backup, log):
    return SimpleNamespace(
        root=str(root), staging=str(staging), backup=str(backup),
        parent_pid=0, token="token", launcher=str(root / "启动大管家.cmd"),
        uv="", health_timeout=1, log=str(log),
    )


def test_verify_staging_detects_hash_mismatch(tmp_path):
    staging = make_staging(tmp_path, corrupt=True)
    with pytest.raises(ValueError, match="校验失败"):
        worker.verify_staging(staging, "0.3.1")


def test_success_swaps_files_preserves_user_data(monkeypatch, tmp_path):
    root = make_root(tmp_path)
    staging = make_staging(tmp_path)
    backup = tmp_path / "backup"
    log = tmp_path / "worker.log"
    monkeypatch.setattr(worker, "run_uv", lambda *args: True)
    monkeypatch.setattr(worker, "launch", lambda *args: None)
    monkeypatch.setattr(worker, "wait_for_health",
                        lambda *args: (True, {"pid": os.getpid(), "version": VERSION}))
    assert worker.run(args(root, staging, backup, log)) == 0
    assert (root / "workbench" / "app.py").read_text(encoding="utf-8") == "# new app\n"
    assert (root / "task_config.json").read_text(encoding="utf-8") == '{"old": true}'
    assert (root / ".env").read_text(encoding="utf-8") == "PRIVATE=keep\n"
    assert (root / ".runtime" / "keep.txt").read_text(encoding="utf-8") == "runtime"
    result = json.loads((root / ".runtime" / "update" / "last_result.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert (root / ".runtime" / "workbench" / "installed_manifest.json").is_file()


def test_failure_rolls_back_old_files(monkeypatch, tmp_path):
    root = make_root(tmp_path)
    staging = make_staging(tmp_path)
    backup = tmp_path / "backup"
    log = tmp_path / "worker.log"
    monkeypatch.setattr(worker, "run_uv", lambda *args: True)
    monkeypatch.setattr(worker, "launch", lambda *args: None)
    monkeypatch.setattr(worker, "wait_for_health",
                        lambda *args: (False, {"pid": os.getpid(), "version": VERSION}))
    monkeypatch.setattr(worker, "kill_pid", lambda pid: None)
    assert worker.run(args(root, staging, backup, log)) == 1
    assert (root / "workbench" / "app.py").read_text(encoding="utf-8") == "# old app\n"
    result = json.loads((root / ".runtime" / "update" / "last_result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
