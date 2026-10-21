import os
from pathlib import Path
import subprocess
import sys

import pytest

import local_config as config


@pytest.fixture
def settings(monkeypatch, tmp_path):
    monkeypatch.delenv("DIANTAO_CONFIG_FILE", raising=False)
    monkeypatch.delenv("DIANTAO_OCR_SERVER_URL", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user"))
    root = tmp_path / "project"
    root.mkdir()
    (root / ".env.example").write_text("DIANTAO_OCR_SERVER_URL=http://127.0.0.1:8888/predict_ocr\n")
    monkeypatch.setattr(config, "ROOT", root)
    return root


def test_user_config_wins_over_legacy_but_not_environment(settings, monkeypatch):
    (settings / ".env").write_text("DIANTAO_OCR_SERVER_URL=legacy\n")
    path = config.prepare_config()
    path.write_text("DIANTAO_OCR_SERVER_URL=external\n")
    config.load_config()
    assert os.environ["DIANTAO_OCR_SERVER_URL"] == "external"
    monkeypatch.setenv("DIANTAO_OCR_SERVER_URL", "process")
    config.load_config()
    assert os.environ["DIANTAO_OCR_SERVER_URL"] == "process"


def test_legacy_fallback_and_no_overwrite_migration(settings):
    original = b"DIANTAO_OCR_SERVER_URL=http://ocr.example.invalid/predict_ocr\n"
    (settings / ".env").write_bytes(original)
    config.load_config()
    assert os.environ["DIANTAO_OCR_SERVER_URL"].endswith("/predict_ocr")
    path = config.prepare_config(import_legacy=True)
    assert path.read_bytes() == original
    assert (settings / ".env").read_bytes() == original
    path.write_text("keep-me\n")
    config.prepare_config(import_legacy=True)
    assert path.read_text() == "keep-me\n"


def test_explicit_config_does_not_fall_back(settings, monkeypatch):
    (settings / ".env").write_text("DIANTAO_OCR_SERVER_URL=legacy\n")
    target = settings / "custom.env"
    monkeypatch.setenv("DIANTAO_CONFIG_FILE", str(target))
    with pytest.raises(FileNotFoundError):
        config.load_config()
    target.write_text("DIANTAO_OCR_SERVER_URL=explicit\n")
    config.load_config()
    assert os.environ["DIANTAO_OCR_SERVER_URL"] == "explicit"


def test_clean_child_process_loads_external_settings(settings):
    config.prepare_config().write_text("DIANTAO_OCR_SERVER_URL=http://ocr.example.invalid/predict_ocr\n")
    result = subprocess.run(
        [sys.executable, "-c", "from local_config import load_config; import os; load_config(); "
         "assert os.environ['DIANTAO_OCR_SERVER_URL']=='http://ocr.example.invalid/predict_ocr'"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
