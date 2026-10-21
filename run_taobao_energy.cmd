@echo off
cd /d "%~dp0"
if exist ".venv-energy\Scripts\python.exe" (
    rtk proxy ".venv-energy\Scripts\python.exe" -u tools\run_taobao_energy.py %*
) else (
    rtk proxy uv run --no-project python -u tools\run_taobao_energy.py %*
)
