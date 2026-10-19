@echo off
cd /d "%~dp0"
rtk proxy uv --quiet run --with uiautomator2 --with rapidocr-onnxruntime python -u tools\taobao_energy.py %*
