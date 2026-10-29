@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
    echo Please install uv first: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)
if not exist "%~dp0workbench\.venv\pyvenv.cfg" (
    echo Preparing the workbench environment. First launch requires a download.
    uv sync --project "%~dp0workbench" --python 3.11 --no-dev
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
set "PYTHON_EXE=%~dp0workbench\.venv\Scripts\python.exe"
"%PYTHON_EXE%" -c "import fastapi, uvicorn, webview, qrcode, uiautomator2, requests, dotenv, cv2, numpy, PIL"
if errorlevel 1 (
    echo Dependencies are incomplete. Run: uv sync --project workbench --python 3.11 --no-dev
    pause
    exit /b 1
)
set "PYTHON_HOME="
for /f "tokens=1,* delims==" %%A in ('findstr /b "home =" "%~dp0workbench\.venv\pyvenv.cfg"') do set "PYTHON_HOME=%%B"
for /f "tokens=* delims= " %%A in ("%PYTHON_HOME%") do set "PYTHON_HOME=%%A"
if not exist "%PYTHON_HOME%\pythonw.exe" (
    echo The windowless Python runtime is unavailable.
    pause
    exit /b 1
)
set "PYTHONPATH=%~dp0workbench\.venv\Lib\site-packages;%~dp0;%PYTHONPATH%"
start "" "%PYTHON_HOME%\pythonw.exe" "%~dp0workbench\app.py"
exit /b 0
