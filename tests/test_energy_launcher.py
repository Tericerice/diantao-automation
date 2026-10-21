import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

from tools import run_taobao_energy as launcher


def environment(tmp_path, monkeypatch):
    env = tmp_path / "energy"
    python = env / "python.exe"
    ready = env / ".energy-ready"
    monkeypatch.setattr(launcher, "ENV", env)
    monkeypatch.setattr(launcher, "PYTHON", python)
    monkeypatch.setattr(launcher, "READY", ready)
    return env, python, ready


def test_prepared_environment_starts_without_uv(tmp_path, monkeypatch, capsys):
    env, python, ready = environment(tmp_path, monkeypatch)
    env.mkdir()
    python.touch()
    ready.touch()
    find_uv = Mock(side_effect=AssertionError("warm start must not resolve uv"))
    monkeypatch.setattr(launcher.shutil, "which", find_uv)
    launch = Mock(return_value=7)
    monkeypatch.setattr(launcher.subprocess, "call", launch)
    assert launcher.main(["run", "--repeat", "1"]) == 7
    assert launch.call_args.args[0][-3:] == ["run", "--repeat", "1"]
    assert "环境已就绪" in capsys.readouterr().out


def test_failed_install_is_not_marked_ready(tmp_path, monkeypatch):
    env, python, ready = environment(tmp_path, monkeypatch)
    env.mkdir()
    python.touch()
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "uv")
    monkeypatch.setattr(
        launcher.subprocess, "run",
        Mock(side_effect=subprocess.CalledProcessError(1, "uv")),
    )
    launch = Mock()
    monkeypatch.setattr(launcher.subprocess, "call", launch)
    assert launcher.main(["run"]) == 1
    assert not ready.exists()
    launch.assert_not_called()


def test_scan_forwards_child_json_and_sends_startup_notice_to_stderr(
    tmp_path, monkeypatch, capfd
):
    _, _, ready = environment(tmp_path, monkeypatch)
    ready.parent.mkdir()
    ready.touch()
    monkeypatch.setattr(launcher, "PYTHON", Path(sys.executable))
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "taobao_energy.py").write_text(
        'print(\'{"blocks": []}\')', encoding="utf-8"
    )
    assert launcher.main(["scan"]) == 0
    captured = capfd.readouterr()
    assert captured.out.strip() == '{"blocks": []}'
    assert "环境已就绪" in captured.err
