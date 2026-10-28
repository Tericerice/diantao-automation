"""Contract tests for the isolated in-memory update preview."""
import importlib
import inspect
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


def test_preview_contract_is_isolated_and_serves_safe_mock_data(client):
    health = client.get("/api/health").json()
    assert health == {"ok": True, "preview": True, "running_count": 0,
                      "version": preview.CURRENT_VERSION}
    apps = client.get("/api/apps").json()["apps"]
    assert apps and all(item["status"] == "stopped" for item in apps)
    assert client.get("/api/adb/status").json()["mock"] is True
    status = client.get("/api/update/status").json()
    assert status["mock"] is True
    assert status["security"] == {"signed": True, "verified": True, "rollback": True}
    source = inspect.getsource(preview)
    assert "workbench.phone" not in source
    assert "workbench.tasks" not in source
    assert "task_host" not in source
    assert "subprocess" not in source


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
    assert windows[0][0] == "Tearice · 自动更新预览"
    assert preview.APP_USER_MODEL_ID != "DianTao.AutomationButler"
    assert settings[0]["storage_path"].endswith(
        ".runtime\\workbench_update_preview\\webview"
    ) or settings[0]["storage_path"].endswith(
        ".runtime/workbench_update_preview/webview"
    )
    assert settings[0]["private_mode"] is False
