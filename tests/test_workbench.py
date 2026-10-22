"""The publication's workbench contracts; these tests never operate a real phone."""
import base64
from copy import deepcopy
import importlib
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

desktop = importlib.import_module("workbench.app")
phone = importlib.import_module("workbench.phone")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(desktop, "PROCESSES", {})
    monkeypatch.setattr(desktop, "STARTED", {})
    monkeypatch.setattr(desktop, "LOGS", {})
    monkeypatch.setattr(desktop, "SEQUENCES", {})
    monkeypatch.setattr(desktop, "EXIT_CODES", {})
    monkeypatch.setattr(phone, "SESSIONS", {})
    monkeypatch.setenv("DIANTAO_OCR_SERVER_URL", "http://ocr.example.test/predict_ocr")
    with TestClient(desktop.app) as connection:
        yield connection


def test_dashboard_contains_all_business_tasks_and_one_qr_entry(client):
    from task_catalog import TASK_FILES

    tasks = client.get("/api/apps").json()["apps"]
    assert len(tasks) == len(desktop.TASKS)
    assert TASK_FILES <= {t["script"] for t in desktop.TASKS.values()}
    assert {"diantao-all-in-one", "diantao-one-click", "diantao-one-click-tasks",
            "diantao-saved-tasks", "taobao-double11-energy", "taobao-double11-workbuddy",
            "diantao-coupon"} <= {t["id"] for t in tasks}
    assert all((desktop.ROOT / t["script"]).is_file()
               for t in desktop.TASKS.values() if not t["script"].startswith("../"))
    assert all("command" not in t and "script" not in t for t in tasks)
    html = client.get("/").text
    assert html.count('id="connect-phone"') == 1
    assert 'data-tab="web"' not in html
    assert 'data-tab="ai"' not in html
    assert client.get("/api/health").json()["running_count"] == 0
    assert client.post("/api/start/unknown").status_code == 404


def test_missing_external_task_remains_visible_and_cannot_spawn(client, monkeypatch, tmp_path):
    tasks = deepcopy(desktop.TASKS)
    tasks["taobao-618-external"]["script"] = str(tmp_path / "missing.py")
    monkeypatch.setattr(desktop, "TASKS", tasks)
    task = next(t for t in client.get("/api/apps").json()["apps"]
                if t["id"] == "taobao-618-external")
    assert task["available"] is False
    assert "缺少脚本" in task["unavailable_reason"]
    assert client.post("/api/start/taobao-618-external").status_code == 400
    assert not desktop.PROCESSES


@pytest.mark.parametrize("task_id", [
    "diantao-all-in-one", "diantao-one-click", "diantao-one-click-tasks",
    "diantao-saved-tasks", "diantao-signin", "taobao-double11-workbuddy",
])
def test_migrated_entry_spawns_its_script_and_arguments(client, monkeypatch, task_id):
    from io import StringIO
    from types import SimpleNamespace

    task = desktop.TASKS[task_id]
    process = SimpleNamespace(pid=123, stdout=StringIO(""), poll=lambda: None)
    with patch.object(desktop.subprocess, "Popen", return_value=process) as spawn, \
            patch.object(desktop, "threading", SimpleNamespace(
                Thread=lambda **kwargs: SimpleNamespace(start=lambda: None)
            )):
        assert client.post("/api/start/" + task_id).status_code == 200
    command = spawn.call_args.args[0]
    assert command[1:] == ["-u", str(desktop.ROOT / task["script"]), *task["args"]]
    assert spawn.call_args.kwargs["cwd"] == desktop.ROOT
    assert spawn.call_args.kwargs["env"]["DIANTAO_OCR_SERVER_URL"]
    desktop.PROCESSES.clear()


def test_workbuddy_does_not_require_cloud_ocr(client, monkeypatch, tmp_path):
    prepare_dummy(monkeypatch, tmp_path, "print('WorkBuddy entry ready')\n")
    monkeypatch.delenv("DIANTAO_OCR_SERVER_URL")
    assert client.post("/api/start/taobao-double11-workbuddy").status_code == 200
    desktop.PROCESSES["taobao-double11-workbuddy"].wait(timeout=5)


def prepare_dummy(monkeypatch, tmp_path, source):
    script = tmp_path / "task.py"
    script.write_text(source, encoding="utf-8")
    tasks = deepcopy(desktop.TASKS)
    for task in tasks.values():
        task["script"], task["args"] = str(script), []
    monkeypatch.setattr(desktop, "TASKS", tasks)
    monkeypatch.setattr(desktop, "RUNTIME", tmp_path / "logs")


def test_start_captures_utf8_output_and_stream_replays_finished_task(client, monkeypatch, tmp_path):
    prepare_dummy(monkeypatch, tmp_path, "print('任务测试完成', flush=True)\n")
    result = client.post("/api/start/taobao-double11-energy")
    assert result.status_code == 200
    process = desktop.PROCESSES["taobao-double11-energy"]
    process.wait(timeout=5)
    for _ in range(100):
        lines = client.get("/api/logs/taobao-double11-energy").json()["lines"]
        if any("[结束]" in text for text in lines):
            break
        time.sleep(.01)
    assert "任务测试完成" in lines
    stream = client.get("/api/logs/taobao-double11-energy/stream")
    assert "任务测试完成" in stream.text
    assert '"type":"exit"' in stream.text
    assert client.get("/api/health").json()["running_count"] == 0


def test_tasks_cannot_compete_for_phone_and_stop_reaps_process(client, monkeypatch, tmp_path):
    prepare_dummy(monkeypatch, tmp_path, "import time\nprint('started', flush=True)\ntime.sleep(60)\n")
    started = client.post("/api/start/diantao-coupon")
    assert started.status_code == 200
    second = client.post("/api/start/taobao-double11-energy")
    assert second.status_code == 409
    assert client.post("/api/stop/diantao-coupon").json()["ok"]
    assert desktop.PROCESSES["diantao-coupon"].poll() is not None


def test_missing_ocr_configuration_stops_before_any_process(client, monkeypatch):
    monkeypatch.delenv("DIANTAO_OCR_SERVER_URL")
    response = client.post("/api/start/diantao-coupon")
    assert response.status_code == 400
    assert desktop.PROCESSES == {}


def test_child_process_has_no_console_and_no_temporary_dependency_resolution(client, monkeypatch, tmp_path):
    prepare_dummy(monkeypatch, tmp_path, "print('ready')\n")
    original = subprocess.Popen
    captured = []

    def spawn(*args, **kwargs):
        captured.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(desktop.subprocess, "Popen", spawn)
    assert client.post("/api/start/diantao-coupon").status_code == 200
    desktop.PROCESSES["diantao-coupon"].wait(timeout=5)
    command, options = captured[0]
    assert Path(command[0][0]).name.lower() == "python.exe" if sys.platform == "win32" else command[0][0] == sys.executable
    assert "uv" not in command[0]
    assert options["creationflags"] == desktop.NO_WINDOW


@pytest.mark.parametrize("line,expected", [
    ("studio-demo\t_adb-tls-pairing._tcp\t192.0.2.5:37001", "192.0.2.5:37001"),
    ("studio-demo _adb-tls-pairing._tcp. [2001:db8::1]:37001", "[2001:db8::1]:37001"),
    ("List of discovered mdns services", None),
])
def test_mdns_parser(line, expected):
    result = phone.parse_mdns(line)
    assert (result["endpoint"] if result else None) == expected


def test_qr_pairs_only_its_own_service_and_verifies_device_connection(client, monkeypatch):
    monkeypatch.setattr(phone, "find_adb", lambda: "adb")
    qr = client.post("/api/adb/qr-generate").json()
    session = phone.SESSIONS[qr["session_id"]]
    assert b"<svg" in base64.b64decode(qr["qr_image"].split(",", 1)[1])
    assert "password" not in qr
    calls = []

    def adb(args, timeout=15):
        calls.append(args)
        if args == ["mdns", "services"]:
            output = (
                "studio-other _adb-tls-pairing._tcp 192.0.2.9:37001\n"
                f"{session['service']} _adb-tls-pairing._tcp 192.0.2.5:37001\n"
                "adb-test _adb-tls-connect._tcp 192.0.2.5:37002\n"
            )
        elif args[0] == "pair":
            output = "Successfully paired to 192.0.2.5:37001"
        elif args[0] == "connect":
            output = "connected to 192.0.2.5:37002"
        else:
            output = "List of devices attached\n192.0.2.5:37002\tdevice\n"
        return {"ok": True, "stdout": output, "message": output}

    monkeypatch.setattr(phone, "exec_adb", adb)
    assert client.get("/api/adb/qr-poll/" + qr["session_id"]).json()["status"] == "paired"
    assert client.post("/api/adb/qr-connect/" + qr["session_id"]).json()["ok"]
    assert next(call for call in calls if call[0] == "pair")[1] == "192.0.2.5:37001"
    client.post("/api/adb/qr-cancel/" + qr["session_id"])
    assert client.get("/api/adb/qr-poll/" + qr["session_id"]).json()["status"] == "expired"


def test_qr_requires_adb_and_connect_does_not_trust_exit_code_zero(client, monkeypatch):
    monkeypatch.setattr(phone, "find_adb", lambda: None)
    assert client.post("/api/adb/qr-generate").status_code == 400
    monkeypatch.setattr(phone, "find_adb", lambda: "adb")
    qr = client.post("/api/adb/qr-generate").json()
    session = phone.SESSIONS[qr["session_id"]]
    session.update(status="paired", device={"host": "192.0.2.5"})

    def adb(args, timeout=15):
        output = "adb-test _adb-tls-connect._tcp 192.0.2.5:37002" if args == ["mdns", "services"] else ""
        return {"ok": True, "stdout": output, "message": "cannot connect"}

    monkeypatch.setattr(phone, "exec_adb", adb)
    assert not client.post("/api/adb/qr-connect/" + qr["session_id"]).json()["ok"]
    session["created"] -= phone.TTL + 1
    assert client.get("/api/adb/qr-poll/" + qr["session_id"]).json()["status"] == "expired"


def test_adb_background_queries_never_open_console():
    with patch.object(phone, "find_adb", return_value="adb"), patch.object(
        phone.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")
    ) as run:
        assert phone.exec_adb(["devices"])["ok"]
    assert run.call_args.kwargs["creationflags"] == phone.NO_WINDOW
