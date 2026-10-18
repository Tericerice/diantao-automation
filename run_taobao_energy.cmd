@echo off
cd /d "%~dp0"
rtk proxy uv run --no-project --with uiautomator2 --with rapidocr-onnxruntime python tools\taobao_energy.py %*
