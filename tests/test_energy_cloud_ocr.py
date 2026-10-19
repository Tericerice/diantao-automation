import io
from unittest.mock import Mock

import pytest
import requests
from PIL import Image

import cloud_ocr
from tools import taobao_energy as task


@pytest.fixture
def endpoint(monkeypatch):
    monkeypatch.setenv("DIANTAO_OCR_SERVER_URL", "http://ocr.test.local/predict_ocr")


def response(data):
    result = Mock()
    result.json.return_value = data
    return result


def test_upload_preserves_dimensions_and_uses_cloud_centers(endpoint, monkeypatch):
    post = Mock(return_value=response({"code": 200, "data": [
        {"text": " 做任务赚能量 ", "score": .98, "center": {"x": 500, "y": 800}},
        {"text": "误识别", "score": .2, "center": {"x": 10, "y": 20}},
        {"text": " ", "score": .99, "center": {"x": 10, "y": 20}},
    ]}))
    monkeypatch.setattr(cloud_ocr.requests, "post", post)
    assert cloud_ocr.recognize(Image.new("RGBA", (1264, 2780))) == [
        dict(text="做任务赚能量", cx=500, cy=800)]
    args, kwargs = post.call_args
    assert args == ("http://ocr.test.local/predict_ocr",)
    uploaded = Image.open(io.BytesIO(kwargs["files"]["image"][1]))
    assert uploaded.size == (1264, 2780)
    assert uploaded.mode == "RGB"
    assert kwargs["timeout"] == (5, 45)


@pytest.mark.parametrize("payload", [{"code": 500, "data": []}, {"code": 200}, []])
def test_bad_service_reply_stops_task(endpoint, monkeypatch, payload):
    monkeypatch.setattr(cloud_ocr.requests, "post", Mock(return_value=response(payload)))
    with pytest.raises(RuntimeError, match="返回异常"):
        cloud_ocr.recognize(Image.new("RGB", (20, 20)))


def test_network_failure_is_concise_without_local_fallback(endpoint, monkeypatch):
    monkeypatch.setattr(cloud_ocr.requests, "post", Mock(side_effect=requests.Timeout("private endpoint")))
    with pytest.raises(RuntimeError, match="腾讯云 OCR 请求失败") as raised:
        cloud_ocr.recognize(Image.new("RGB", (20, 20)))
    assert "private endpoint" not in str(raised.value)


def test_missing_config_stops_before_phone_connection(monkeypatch):
    monkeypatch.delenv("DIANTAO_OCR_SERVER_URL", raising=False)
    monkeypatch.setattr(task.sys, "argv", ["taobao_energy.py", "scan"])
    connect = Mock()
    monkeypatch.setattr(task, "connect_with_retry", connect)
    with pytest.raises(RuntimeError, match="未配置腾讯云 OCR"):
        task.main()
    connect.assert_not_called()
    monkeypatch.setattr(task, "_raw_scan", False)


def test_activity_webview_uses_cloud_and_records_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(task, "OUT", tmp_path)
    device = Mock()
    device.screenshot.return_value = Image.new("RGB", (1264, 2780))
    device.app_current.return_value = dict(package=task.TB, activity="TMSActivity")
    recognize = Mock(return_value=[dict(text="做任务赚能量", cx=500, cy=800)])
    monkeypatch.setattr(task, "recognize", recognize)
    assert task.scan(device) == [dict(text="做任务赚能量", cx=500, cy=800)]
    recognize.assert_called_once_with(device.screenshot.return_value)
    device.dump_hierarchy.assert_not_called()
    assert '"source": "腾讯云OCR"' in (tmp_path / "current.json").read_text(encoding="utf-8")


def test_native_task_text_avoids_unnecessary_cloud_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(task, "OUT", tmp_path)
    device = Mock()
    device.screenshot.return_value = Image.new("RGB", (1264, 2780))
    device.app_current.return_value = dict(package=task.TB, activity="NativeActivity")
    device.dump_hierarchy.return_value = '<hierarchy><node package="com.taobao.taobao" text="做任务赚能量" bounds="[0,0][100,100]"/></hierarchy>'
    recognize = Mock()
    monkeypatch.setattr(task, "recognize", recognize)
    assert task.scan(device) == [dict(text="做任务赚能量", cx=50, cy=50)]
    recognize.assert_not_called()
