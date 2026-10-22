import base64
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

import workbuddy_vision as vision


def payload(width=600, height=900):
    return dict(width=width, height=height, blocks=[dict(text="去完成", cx=483, cy=272)])


def result(value):
    return dict(type="result", subtype="success", is_error=False, result=value)


@pytest.mark.parametrize("wrap", [
    lambda value: value,
    lambda value: result(json.dumps(value)),
    lambda value: result("```json\n" + json.dumps(value) + "\n```"),
    lambda value: dict(result(""), structured_output=value),
    lambda value: [{"type": "reasoning", "content": "not coordinates"},
                   {"type": "function_call_result", "output": {"cx": 1, "cy": 2}},
                   result(json.dumps(value))],
])
def test_accepts_only_final_observation_across_cli_envelopes(wrap):
    assert vision.parse_reply(json.dumps(wrap(payload())), 600, 900) == payload()["blocks"]


@pytest.mark.parametrize("value", [
    {"type": "result", "is_error": True, "subtype": "error", "result": json.dumps(payload())},
    dict(result(json.dumps(payload())), permission_denials=[{"tool": "Read"}]),
    [result(json.dumps(payload())), result(json.dumps(payload()))],
    [{"type": "reasoning", "content": json.dumps(payload())}],
    result("Here is the JSON: " + json.dumps(payload())),
    result("```json\n" + json.dumps(payload()) + "\n```\nexplanation"),
    result("{bad json}"),
    dict(payload(), action="click"),
    dict(payload(), width=1440),
    dict(payload(), width=True),
    dict(payload(), blocks="not a list"),
    dict(payload(), blocks=[{"text": "去完成", "cx": 600, "cy": 200}]),
    dict(payload(), blocks=[{"text": "去完成", "cx": -1, "cy": 200}]),
    dict(payload(), blocks=[{"text": "去完成", "cx": True, "cy": 200}]),
    dict(payload(), blocks=[{"text": "去完成", "cx": 20.5, "cy": 200}]),
    dict(payload(), blocks=[{"text": " ", "cx": 20, "cy": 200}]),
    dict(payload(), blocks=[{"text": 123, "cx": 20, "cy": 200}]),
])
def test_rejects_errors_ambiguous_output_prose_and_bad_coordinates(value):
    with pytest.raises(vision.VisionError):
        vision.parse_reply(json.dumps(value), 600, 900)


@pytest.fixture
def client(monkeypatch, tmp_path):
    cli = tmp_path / "codebuddy.js"
    cli.touch()
    monkeypatch.setenv("WORKBUDDY_CLI", str(cli))
    monkeypatch.delenv("WORKBUDDY_MODEL", raising=False)
    monkeypatch.setattr(vision, "config_path", lambda: tmp_path / "private.json")
    monkeypatch.setattr(vision.shutil, "which", lambda _: "node")
    return vision.WorkBuddyVision()


def test_image_is_passed_directly_with_no_tools_and_coordinates_map_back(client, monkeypatch):
    folders = []
    def run(command, **kwargs):
        assert command[command.index("--tools") + 1] == ""
        assert command[command.index("--input-format") + 1] == "stream-json"
        assert "--json-schema" not in command
        assert "--strict-mcp-config" in command
        assert "--system-prompt" in command
        assert kwargs.get("shell", False) is False
        assert kwargs["timeout"] == 90
        folder = Path(kwargs["cwd"])
        folders.append(folder)
        assert list(folder.iterdir()) == []
        message = json.loads(kwargs["input"])
        parts = message["message"]["content"]
        image = Image.open(io.BytesIO(base64.b64decode(parts[1]["source"]["data"])))
        width, height = image.size
        assert max(image.size) == 1440
        assert image.mode == "RGB"
        answer = dict(width=width, height=height,
                      blocks=[dict(text="去完成", cx=width // 2, cy=height // 2)])
        return SimpleNamespace(returncode=0, stdout=json.dumps([result(json.dumps(answer))]))
    monkeypatch.setattr(vision.subprocess, "run", run)
    blocks = client.recognize(Image.new("RGBA", (1264, 2780)))
    assert abs(blocks[0]["cx"] - 632) <= 2
    assert blocks[0]["cy"] == 1390
    assert all(not folder.exists() for folder in folders)


@pytest.mark.parametrize("failure,match", [
    (subprocess.TimeoutExpired(["private-command"], 90), "timed out"),
    (OSError("private-path"), "could not be started"),
])
def test_invocation_errors_are_concise_and_hide_private_values(client, monkeypatch, failure, match):
    monkeypatch.setattr(vision.subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(vision.VisionError, match=match) as raised:
        client.recognize(Image.new("RGB", (600, 900)))
    assert "private-" not in str(raised.value)


def test_cli_failure_is_not_used_as_observation(client, monkeypatch):
    monkeypatch.setattr(vision.subprocess, "run", Mock(return_value=SimpleNamespace(
        returncode=1, stdout=json.dumps(payload()), stderr="private-details")))
    with pytest.raises(vision.VisionError, match="CLI failed"):
        client.recognize(Image.new("RGB", (600, 900)))


def test_json_only_command_has_clean_stdout(tmp_path, monkeypatch, capsys):
    image = tmp_path / "input.png"
    Image.new("RGB", (600, 900)).save(image)
    monkeypatch.setattr(vision, "WorkBuddyVision", lambda: SimpleNamespace(
        recognize=lambda _: payload()["blocks"]))
    assert vision.main([str(image)]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == payload()
    assert output.err == ""


def test_failed_json_only_command_has_no_fake_success(tmp_path, monkeypatch, capsys):
    image = tmp_path / "input.png"
    Image.new("RGB", (600, 900)).save(image)
    monkeypatch.setattr(vision, "WorkBuddyVision", Mock(side_effect=vision.VisionError("not logged in")))
    assert vision.main([str(image)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "not logged in" in output.err


def test_workbuddy_scan_skips_ocr_and_outputs_scan_json(tmp_path, monkeypatch, capsys):
    from tools import taobao_energy as task
    phone = Mock()
    phone.screenshot.return_value = Image.new("RGB", (600, 900))
    phone.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    observe = Mock(return_value=payload()["blocks"])
    monkeypatch.setattr(vision, "WorkBuddyVision", lambda: SimpleNamespace(recognize=observe))
    for name in ("prepare_ocr", "ocr_server_url"):
        if hasattr(task, name):
            monkeypatch.setattr(task, name, Mock(side_effect=AssertionError("OCR must not initialize")))
    monkeypatch.setattr(task, "_raw_scan", False)
    monkeypatch.setattr(task, "_vision_recognize", None)
    monkeypatch.setattr(task, "_vision_source", "test")
    monkeypatch.setattr(task, "OUT", tmp_path)
    monkeypatch.setattr(task, "connect_with_retry", lambda _: phone)
    monkeypatch.setattr(task.sys, "argv", ["taobao_energy.py", "scan", "--serial", "test-device",
                                        "--vision", "workbuddy"])
    task.main()
    output = json.loads(capsys.readouterr().out)
    assert output["source"] == "WorkBuddy视觉"
    assert output["blocks"] == payload()["blocks"]
    observe.assert_called_once()
    phone.click.assert_not_called()


def test_missing_workbuddy_configuration_fails_before_phone_connection(monkeypatch):
    from tools import taobao_energy as task
    monkeypatch.setattr(vision, "WorkBuddyVision", Mock(side_effect=vision.VisionError("CLI not found")))
    monkeypatch.setattr(task, "_raw_scan", False)
    monkeypatch.setattr(task, "_vision_recognize", None)
    monkeypatch.setattr(task, "_vision_source", "test")
    monkeypatch.setattr(task.sys, "argv", ["taobao_energy.py", "scan", "--vision", "workbuddy"])
    connect = Mock()
    monkeypatch.setattr(task, "connect_with_retry", connect)
    with pytest.raises(vision.VisionError, match="CLI not found"):
        task.main()
    connect.assert_not_called()


@pytest.mark.parametrize("text", ["0/50", "当前进度 0/50", "当前进度0 / 50"])
def test_task_counter_accepts_workbuddy_merged_label(text):
    from tools.taobao_energy import task_progress
    assert task_progress([dict(text=text, cx=135, cy=819)]) == 0
    assert task_progress([dict(text="好物(1/50)", cx=135, cy=1500)]) is None
