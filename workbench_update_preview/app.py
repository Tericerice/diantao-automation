"""Completely isolated, in-memory preview of the workbench update experience.

This module intentionally does not import production phone, task, hosting, or updater code.
It never launches ADB, automation tasks, installers, or child processes.
"""
from __future__ import annotations

import atexit
import ctypes
from dataclasses import asdict, dataclass
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import urlsplit
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
RUNTIME = ROOT.parent / ".runtime" / "workbench_update_preview"
APP_USER_MODEL_ID = "Tearice.DianTao.UpdatePreview"
DEFAULT_PORT = 9070
CURRENT_VERSION = "0.2.1"
LATEST_VERSION = "0.3.0-preview"

APPS = (
    {"id": "diantao-all-in-one", "category": "script", "name": "点淘一键全部执行",
     "description": "连通性 → 下滑 → 日常任务 → 养优惠", "status": "stopped", "available": True},
    {"id": "diantao-work-guard", "category": "script", "name": "打工与体力守护",
     "description": "按倒计时守护打工和体力领取", "status": "stopped", "available": True},
    {"id": "diantao-signin", "category": "script", "name": "签到赢元宝",
     "description": "签到、视频与日常奖励", "status": "stopped", "available": True},
)


@dataclass
class UpdateState:
    status: str = "available"
    current_version: str = CURRENT_VERSION
    latest_version: str = LATEST_VERSION
    progress: int = 0
    phase: str = "发现新版本"
    message: str = "新版本已准备好，可以先查看更新内容。"
    checked_at: float | None = None
    started_at: float | None = None
    duration: float = 8.0


_LOCK = threading.Lock()
_STATE = UpdateState()


def _snapshot() -> dict:
    with _LOCK:
        if _STATE.status == "installing" and _STATE.started_at is not None:
            elapsed = max(0.0, time.monotonic() - _STATE.started_at)
            progress = min(100, int(elapsed / _STATE.duration * 100))
            _STATE.progress = progress
            if progress < 22:
                _STATE.phase = "验证更新包"
                _STATE.message = "正在核对签名与文件清单。"
            elif progress < 68:
                _STATE.phase = "准备新版本"
                _STATE.message = "仅模拟写入预览环境，不会修改现有程序。"
            elif progress < 100:
                _STATE.phase = "完成安全检查"
                _STATE.message = "正在确认回退点和启动文件。"
            else:
                _STATE.status = "installed"
                _STATE.phase = "更新已就绪"
                _STATE.message = "模拟安装完成。关闭弹窗后可继续预览。"
        payload = asdict(_STATE)
    payload.update({
        "update_available": payload["status"] in {"available", "installing", "cancelled"},
        "can_install": payload["status"] in {"available", "cancelled"},
        "can_cancel": payload["status"] == "installing",
        "mock": True,
        "security": {"signed": True, "verified": True, "rollback": True},
        "release_notes": [
            "新增启动前更新提示，不打断正在查看的任务。",
            "更新过程显示验证、准备和完成阶段。",
            "保留当前版本，模拟失败时可安全回退。",
        ],
    })
    return payload


app = FastAPI(title="Tearice 更新预览", docs_url=None, redoc_url=None)


@app.get("/")
def index():
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/static/{name}", include_in_schema=False)
def static_asset(name: str):
    if urlsplit(name).path != name or name != Path(name).name:
        raise HTTPException(404, "未找到静态资源")
    path = STATIC / name
    if not path.is_file():
        raise HTTPException(404, "未找到静态资源")
    return FileResponse(path)


@app.get("/api/health")
def health():
    return {"ok": True, "preview": True, "running_count": 0, "version": CURRENT_VERSION}


@app.get("/api/apps")
def apps():
    return {"apps": [dict(item) for item in APPS]}


@app.get("/api/adb/status")
def adb_status():
    return {"installed": True, "devices": [], "mock": True, "message": "预览模式未连接手机"}


@app.get("/api/update/status")
def update_status():
    return _snapshot()


@app.post("/api/update/check")
def update_check():
    with _LOCK:
        if _STATE.status == "installing":
            raise HTTPException(409, "模拟更新正在进行")
        _STATE.status = "available"
        _STATE.progress = 0
        _STATE.phase = "发现新版本"
        _STATE.message = "检查完成：有一个经过验证的预览更新。"
        _STATE.checked_at = time.time()
        _STATE.started_at = None
    return {"ok": True, "message": "已完成模拟检查", "update": _snapshot()}


@app.post("/api/update/install")
def update_install():
    with _LOCK:
        if _STATE.status == "installing":
            raise HTTPException(409, "模拟更新正在进行")
        if _STATE.status == "installed":
            raise HTTPException(409, "模拟更新已经完成，请先重置预览")
        _STATE.status = "installing"
        _STATE.progress = 1
        _STATE.phase = "验证更新包"
        _STATE.message = "正在核对签名与文件清单。"
        _STATE.started_at = time.monotonic()
    return {"ok": True, "message": "已开始模拟安装", "update": _snapshot()}


@app.post("/api/update/cancel")
def update_cancel():
    with _LOCK:
        if _STATE.status != "installing":
            raise HTTPException(409, "当前没有可取消的模拟安装")
        _STATE.status = "cancelled"
        _STATE.phase = "更新已取消"
        _STATE.message = "当前版本保持不变，可随时重新开始。"
        _STATE.started_at = None
    return {"ok": True, "message": "已取消模拟安装", "update": _snapshot()}


@app.post("/api/update/reset")
def update_reset():
    global _STATE
    with _LOCK:
        _STATE = UpdateState()
    return {"ok": True, "message": "更新预览已重置", "update": _snapshot()}


def _bind_preview_socket() -> tuple[socket.socket, int]:
    listener = socket.socket()
    if sys.platform == "win32":
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        listener.bind(("127.0.0.1", DEFAULT_PORT))
    except OSError:
        listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.set_inheritable(True)
    return listener, port


def desktop():
    import uvicorn
    import webview

    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass

    listener, port = _bind_preview_socket()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(.1)
    else:
        listener.close()
        raise RuntimeError("更新预览启动失败")

    def shutdown():
        server.should_exit = True

    atexit.register(shutdown)
    icon_name = "tearice-logo.ico" if sys.platform == "win32" else "tearice-logo.png"
    icon = STATIC / icon_name
    webview.create_window("Tearice · 自动更新预览", url=url, width=1180, height=780,
                          resizable=True, min_size=(700, 520))
    try:
        webview.start(private_mode=False, storage_path=str(RUNTIME / "webview"),
                      icon=str(icon) if icon.is_file() else None)
    finally:
        shutdown()
        thread.join(timeout=3)
        listener.close()


if __name__ == "__main__":
    desktop()
