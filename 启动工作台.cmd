@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
    echo Please install uv first: https://docs.astral.sh/uv/getting-started/installation/
    if not "%DIANTAO_NO_PAUSE%"=="1" pause
    exit /b 1
)
set "VENV=%~dp0workbench\.venv"
if not exist "%VENV%\pyvenv.cfg" (
    if exist "%~dp0workbench\.venv-fixed\pyvenv.cfg" set "VENV=%~dp0workbench\.venv-fixed"
)
if not exist "%VENV%\pyvenv.cfg" (
    if exist "%VENV%" (
        echo Removing incomplete workbench environment...
        rmdir /s /q "%VENV%"
    )
    if exist "%VENV%" (
        echo The workbench environment is still in use. Close the workbench window and run this launcher again.
        if not "%DIANTAO_NO_PAUSE%"=="1" pause
        exit /b 1
    )
    echo Preparing the workbench environment. First launch requires a download.
    uv sync --project "%~dp0workbench" --python 3.11 --no-dev
    if errorlevel 1 (
        if not "%DIANTAO_NO_PAUSE%"=="1" pause
        exit /b 1
    )
)
set "PYTHON_EXE=%VENV%\Scripts\python.exe"
"%PYTHON_EXE%" -c "import fastapi, uvicorn, webview, qrcode, uiautomator2, requests, dotenv, cv2, numpy, PIL"
if errorlevel 1 (
    echo Dependencies are incomplete. Run: uv sync --project workbench --python 3.11 --no-dev
    if not "%DIANTAO_NO_PAUSE%"=="1" pause
    exit /b 1
)
set "PYTHON_HOME="
for /f "tokens=1,* delims==" %%A in ('findstr /b "home =" "%VENV%\pyvenv.cfg"') do set "PYTHON_HOME=%%B"
for /f "tokens=* delims= " %%A in ("%PYTHON_HOME%") do set "PYTHON_HOME=%%A"
if not exist "%PYTHON_HOME%\pythonw.exe" (
    echo The windowless Python runtime is unavailable.
    if not "%DIANTAO_NO_PAUSE%"=="1" pause
    exit /b 1
)
set "PYTHONPATH=%VENV%\Lib\site-packages;%~dp0;%PYTHONPATH%"
start "" "%PYTHON_HOME%\pythonw.exe" "%~dp0workbench\app.py"
exit /b 0
