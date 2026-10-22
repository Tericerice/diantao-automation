"""Exercise the real local server, replacing only the native window boundary."""
import importlib
import json
import sys
from types import SimpleNamespace
import urllib.request

desktop = importlib.import_module("workbench.app")


def test_desktop_launches_one_window_with_full_catalog_and_persistent_theme(monkeypatch):
    windows, settings = [], []

    def create_window(title, *, url, **options):
        with urllib.request.urlopen(url + "/api/apps", timeout=3) as response:
            payload = json.load(response)
        with urllib.request.urlopen(url, timeout=3) as response:
            html = response.read().decode("utf-8")
        windows.append((title, payload, html))

    def start(**options):
        settings.append(options)

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(
        create_window=create_window, start=start,
    ))
    desktop.desktop()
    assert len(windows) == 1
    assert windows[0][0] == "点淘 · 自动化大管家"
    assert {task["id"] for task in windows[0][1]["apps"]} == set(desktop.TASKS)
    assert len(windows[0][1]["apps"]) > 20
    assert 'id="connect-phone"' in windows[0][2]
    assert settings[0]["private_mode"] is False
