@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo [Tearice] 未找到 uv，请先安装工作台运行环境。
  pause
  exit /b 1
)

uv run --project workbench python -m workbench_update_preview.app
if errorlevel 1 (
  echo.
  echo [Tearice] 更新预览启动失败。
  pause
)
endlocal
