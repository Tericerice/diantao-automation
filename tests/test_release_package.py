import importlib.util
from pathlib import Path
import subprocess
import zipfile

import pytest

spec = importlib.util.spec_from_file_location("build_release", Path(__file__).resolve().parents[1] / "tools/build_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.mark.parametrize("name", [
    ".env", ".env.backup", "nested/.env", ".venv/a.py", "screenshots/a.png",
    "logs/a.txt", ".workbuddy/memory/a.md", "task_log.json", "tests/test_x.py",
])
def test_private_and_development_files_excluded(name):
    assert not release.distributable(name)


@pytest.mark.parametrize("content", [
    b"http://192.168.1.2:9999/predict_ocr", b"sk-" + b"x" * 24,
    b"http://user:password@example.invalid/", b"C:\\Users\\Alice\\secret",
    b"-----BEGIN PRIVATE KEY-----",
])
def test_generic_sensitive_values_are_rejected_without_echo(content):
    with pytest.raises(ValueError) as error:
        release.check_content("example.py", content)
    assert content.decode() not in str(error.value)


def test_known_private_value_check():
    with pytest.raises(ValueError, match="本机私有配置"):
        release.check_content("example.py", b"private.example.invalid", [b"private.example.invalid"])
    release.check_content(".env.example", b"http://127.0.0.1:8888/predict_ocr")


def test_archive_uses_commit_and_omits_untracked_ignored_settings(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    def git(*args):
        subprocess.run(["rtk", "proxy", "git", *args], cwd=root, check=True, capture_output=True)
    git("init")
    git("config", "user.name", "Release Test")
    git("config", "user.email", "release@example.invalid")
    for name in ("启动大管家.cmd", "启动工作台.cmd", "启动旧版大管家.cmd",
                 "配置本机.cmd", "local_config.py", ".env.example", "VERSION.json",
                 "tools/launch_update_preview.py", "workbench_update_preview/app.py",
                 "workbench/app.py", "workbench/pyproject.toml", "workbench/uv.lock",
                 "养优惠.py", "tools/taobao_energy.py"):
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(
            '{"version":"v0.1.0","commit":null}\n' if name == "VERSION.json" else "# example\n",
            encoding="utf-8",
        )
    (root / ".gitignore").write_text(".env\n.runtime/\n")
    git("add", ".")
    git("commit", "-m", "test fixture")
    (root / ".env").write_text("PRIVATE=never-package-this\n")
    target = release.build_release(root, "v0.1.0", tmp_path / "out")
    with zipfile.ZipFile(target) as archive:
        assert not any(n.endswith("/.env") for n in archive.namelist())
        assert any(n.endswith("/VERSION.json") for n in archive.namelist())
        assert not any(b"never-package-this" in archive.read(n) for n in archive.namelist())
    with pytest.raises(ValueError, match="不一致"):
        release.build_release(root, "v0.1.1", tmp_path / "out")
    (root / "VERSION.json").write_text('{"version":"v0.1.1"}\n', encoding="utf-8")
    (root / "local_config.py").write_text("uncommitted")
    with pytest.raises(ValueError, match="未提交"):
        release.build_release(root, "v0.1.1", tmp_path / "out")
