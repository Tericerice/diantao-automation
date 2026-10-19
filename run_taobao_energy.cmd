@echo off
cd /d "%~dp0"
rtk proxy uv --quiet run --with uiautomator2 --with requests --with python-dotenv python -u tools\taobao_energy.py %*
