import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import cloud_ocr
from tools.ocr_compat_server import create_app


@pytest.mark.parametrize("endpoint", [
    "http://127.0.0.1:8888/predict_ocr",
    "https://ocr.example.invalid/predict_ocr",
])
def test_configured_service_contract_round_trip_and_temporary_cleanup(monkeypatch, endpoint):
    paths = []
    class Engine:
        def predict(self, input):
            path = Path(input)
            paths.append(path)
            with Image.open(path) as image:
                assert image.size == (1264, 2780)
            return [SimpleNamespace(json={"res": {
                "rec_texts": ["去完成"],
                "rec_scores": [0.98],
                "rec_boxes": [[1000, 1400, 1200, 1600]],
            }})]
    monkeypatch.setenv("DIANTAO_OCR_SERVER_URL", endpoint)
    with TestClient(create_app(Engine())) as service:
        assert service.get("/health").json()["status"] == "ready"
        def post(url, **kwargs):
            assert url == endpoint
            return service.post("/predict_ocr", files=kwargs["files"])
        monkeypatch.setattr(cloud_ocr.requests, "post", post)
        assert cloud_ocr.recognize(Image.new("RGB", (1264, 2780))) == [
            dict(text="去完成", cx=1100, cy=1500),
        ]
    assert paths and all(not path.exists() for path in paths)


def test_service_address_can_be_changed_without_rewriting_task(monkeypatch):
    monkeypatch.setenv("DIANTAO_OCR_SERVER_URL", " http://127.0.0.1:8888/predict_ocr ")
    assert cloud_ocr.ocr_server_url() == "http://127.0.0.1:8888/predict_ocr"
    monkeypatch.setenv("DIANTAO_OCR_SERVER_URL", "https://ocr.example.invalid/predict_ocr")
    assert cloud_ocr.ocr_server_url() == "https://ocr.example.invalid/predict_ocr"


def test_image_error_does_not_leave_uploaded_file(monkeypatch, tmp_path):
    from tools import ocr_compat_server as server
    monkeypatch.setattr(server, "TEMP_FILE_DIRECTORY", str(tmp_path))
    engine = Mock()
    engine.predict.side_effect = RuntimeError("test inference error")
    with TestClient(create_app(engine)) as service:
        result = service.post("/predict_ocr", files={"image": ("test.jpg", b"invalid", "image/jpeg")})
    assert result.status_code == 500
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("filename", [
    "diantao_1024_auto.py", "tools/test_ocr_screenshot.py",
    "tools/analyze_screenshot.py", "tools/test_adb_screenshot.py",
])
def test_diagnostic_entrypoints_use_shared_ocr_configuration(filename):
    source = (Path(__file__).resolve().parents[1] / filename).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert any(isinstance(n, ast.ImportFrom) and n.module == "cloud_ocr"
               and any(a.name == "ocr_server_url" for a in n.names) for n in tree.body)
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "ocr_server_url" for n in ast.walk(tree))
    assert not any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and n.value.startswith(("http://", "https://"))
                   and "/predict_ocr" in n.value for n in ast.walk(tree))
