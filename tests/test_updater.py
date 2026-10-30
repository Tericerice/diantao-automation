import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest
from fastapi import HTTPException

from workbench import updater


def manifest(version="v0.3.1", sha="0" * 64, size=10):
    return {
        "schema": 1,
        "version": version,
        "tag": version,
        "notes_url": "https://github.com/example/repo/releases/tag/" + version,
        "notes": ["测试"],
        "min_supported": "v0.3.0",
        "worker_protocol": 1,
        "asset": {"url": "https://example.invalid/update.zip", "sha256": sha, "size": size},
    }


def test_version_compare_and_normalize():
    assert updater.normalize_version("v0.3.1") == "0.3.1"
    assert updater.is_newer("v0.3.1", "0.3.0")
    assert not updater.is_newer("v0.3.0", "0.3.0")
    assert not updater.is_newer("v0.2.9", "0.3.0")
    assert updater.is_newer("v0.3.0", "0.3.0-rc.1")


def test_manifest_validation_rejects_invalid_fields():
    assert updater.validate_manifest(manifest())["version"] == "0.3.1"
    for bad in (
        {"schema": 2},
        {**manifest(), "asset": {"url": "http://evil.example/x", "sha256": "0" * 64, "size": 1}},
        {**manifest(), "asset": {"url": "https://example.invalid/x", "sha256": "bad", "size": 1}},
    ):
        with pytest.raises(ValueError):
            updater.validate_manifest(bad)


def build_zip(tmp_path: Path, version="v0.3.1", corrupt=False):
    staging = tmp_path / "source"
    files = {
        "启动大管家.cmd": "echo hi\n",
        "启动工作台.cmd": "echo hi\n",
        "配置本机.cmd": "echo hi\n",
        "local_config.py": "# config\n",
        "VERSION.json": json.dumps({"version": version}),
        "workbench/app.py": "# app\n",
        "workbench/updater.py": "# updater\n",
        "workbench/update_worker.py": "# worker\n",
        "workbench/uv.lock": "lock\n",
    }
    manifest_files = {}
    for name, text in files.items():
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        data = target.read_bytes()
        manifest_files[name] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
    (staging / "manifest.json").write_text(json.dumps({
        "schema": 1, "version": version, "files": manifest_files,
    }), encoding="utf-8")
    archive_path = tmp_path / "update.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for source in staging.rglob("*"):
            if source.is_file():
                name = source.relative_to(staging).as_posix()
                data = source.read_bytes()
                if corrupt and name == "workbench/app.py":
                    data = b"corrupt"
                archive.writestr(f"diantao-workbench-{version}/{name}", data)
    return archive_path


def test_extract_zip_verifies_and_strips_prefix(tmp_path):
    archive = build_zip(tmp_path)
    staging = tmp_path / "staging"
    result = updater._extract_zip(archive, staging, "0.3.1")
    assert result["version"] == "v0.3.1"
    assert (staging / "workbench" / "app.py").is_file()
    assert (staging / "VERSION.json").is_file()


def test_extract_zip_rejects_bad_hash_and_traversal(tmp_path):
    bad = build_zip(tmp_path, corrupt=True)
    with pytest.raises(ValueError, match="校验失败"):
        updater._extract_zip(bad, tmp_path / "s1", "0.3.1")

    archive_path = tmp_path / "traversal.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("diantao-workbench-v0.3.1/../evil.py", "x")
    with pytest.raises(ValueError, match="路径无效"):
        updater._extract_zip(archive_path, tmp_path / "s2", "0.3.1")


def test_install_is_blocked_while_task_runs(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "VERSION.json").write_text('{"version": "v0.3.0"}', encoding="utf-8")
    manager = updater.UpdateManager(
        root, tmp_path / "runtime",
        running_check=lambda: ["diantao-coupon"],
        stop_tasks=lambda: None,
        exit_process=lambda code: None,
    )
    manager.latest = updater.validate_manifest(manifest())
    with pytest.raises(HTTPException) as error:
        manager.install()
    assert error.value.status_code == 409
    snapshot = manager.snapshot()
    assert snapshot["simulation"] is False
    assert "任务正在运行" in snapshot["blocked_reason"]
