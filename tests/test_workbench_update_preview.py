"""Contract tests for the isolated in-memory update preview."""
import importlib
import importlib.util
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.request

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

preview = importlib.import_module("workbench_update_preview.app")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(preview, "_STATE", preview.UpdateState(duration=60))
    with TestClient(preview.app) as connection:
        yield connection


def test_dashboard_serves_explicit_simulation_data(client):
    health = client.get("/api/health").json()
    assert health == {"ok": True, "running_count": 0,
                      "version": preview.CURRENT_VERSION,
                      "update_mode": "simulation"}
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"ok":true,"running_count":0}'

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(preview.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    upstream = client.get("/api/upstream/status").json()
    monkeypatch.undo()
    assert upstream["ok"] is True
    assert upstream["upstream"] == "http://127.0.0.1:9060"
    status = client.get("/api/update/status").json()
    assert status["simulation"] is True
    assert status["update_mode"] == "simulation"
    assert status["current_version"] == "0.3.0"
    assert status["latest_version"] == "0.3.1-demo"
    assert "security" not in status
    source = inspect.getsource(preview)
    assert "workbench.phone" not in source
    assert "workbench.tasks" not in source
    assert "task_host" not in source
    assert "subprocess" not in source


def test_launcher_reuses_compatible_backend_and_only_stops_owned_process(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "tools/launch_update_preview.py"
    spec = importlib.util.spec_from_file_location("launch_dashboard", path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    class Process:
        def __init__(self):
            self.terminated = False
        def poll(self):
            return None
        def terminate(self):
            self.terminated = True
        def wait(self, timeout=None):
            return 0

    reused = Process()
    launcher._stop_owned_backend(None)
    assert reused.terminated is False
    launcher._stop_owned_backend(reused)
    assert reused.terminated is True


def test_update_check_install_cancel_and_reset_are_in_memory(client):
    checked = client.post("/api/update/check")
    assert checked.status_code == 200
    assert checked.json()["update"]["status"] == "available"

    installed = client.post("/api/update/install")
    assert installed.status_code == 200
    assert installed.json()["update"]["status"] == "installing"
    assert client.post("/api/update/install").status_code == 409

    cancelled = client.post("/api/update/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["update"]["status"] == "cancelled"
    assert client.post("/api/update/cancel").status_code == 409

    reset = client.post("/api/update/reset").json()["update"]
    assert reset["status"] == "available"
    assert reset["progress"] == 0


def test_progress_completes_without_background_workers(client, monkeypatch):
    monkeypatch.setattr(preview, "_STATE", preview.UpdateState(duration=1))
    assert client.post("/api/update/install").status_code == 200
    preview._STATE.started_at -= 2
    result = client.get("/api/update/status").json()
    assert result["status"] == "installed"
    assert result["progress"] == 100
    assert result["can_install"] is False


def test_static_paths_are_confined_to_preview_directory(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/tearice-logo.svg").status_code == 200
    assert client.get("/static/../app.py").status_code == 404


def test_desktop_uses_dedicated_identity_storage_and_port_fallback(monkeypatch):
    windows, settings = [], []

    def create_window(title, *, url, **options):
        with urllib.request.urlopen(url + "/api/health", timeout=3) as response:
            assert response.status == 200
        windows.append((title, url, options))

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(
        create_window=create_window,
        start=lambda **options: settings.append(options),
    ))
    preview.desktop()
    assert windows[0][0] == "Tearice · 自动化大管家"
    assert preview.APP_USER_MODEL_ID != "DianTao.AutomationButler"
    assert settings[0]["storage_path"].endswith(
        ".runtime\\workbench_update_preview\\webview"
    ) or settings[0]["storage_path"].endswith(
        ".runtime/workbench_update_preview/webview"
    )
    assert settings[0]["private_mode"] is False
