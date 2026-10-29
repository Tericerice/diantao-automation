@echo off
cd /d "%~dp0"
"%~dp0workbench\.venv\Scripts\python.exe" "%~dp0tools\launch_update_preview.py"
if errorlevel 1 pause
exit /b 0