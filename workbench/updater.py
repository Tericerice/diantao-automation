"""Real update service: manifest check, download, verify, stage and hand off.

The FastAPI app configures this module with its root/runtime and task callbacks.
The actual file replacement runs in a separate stdlib-only worker process.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable
from urllib.parse import urlsplit

import requests
from fastapi import APIRouter, HTTPException

DEFAULT_MANIFEST_URL = (
    "https://github.com/Tericerice/diantao-automation"
    "/releases/latest/download/latest.json"
)
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 64 * 1024
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_ENTRIES = 5000
REQUIRED_FILES = (
    "启动大管家.cmd", "启动工作台.cmd", "配置本机.cmd", "local_config.py",
    "VERSION.json", "workbench/app.py", "workbench/updater.py",
    "workbench/update_worker.py", "workbench/uv.lock",
)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime" / "update"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_router = APIRouter(prefix="/api/update")
_manager: "UpdateManager | None" = None
_running_check: Callable[[], list[str]] = lambda: []
_stop_tasks: Callable[[], None] = lambda: None
_exit_process: Callable[[int], None] = lambda code: os._exit(code)


def normalize_version(value) -> str:
    match = SEMVER.match(str(value or "").strip())
    if not match:
        raise ValueError(f"版本格式无效：{value}")
    base = f"{int(match.group(1))}.{int(match.group(2))}.{int(match.group(3))}"
    return f"{base}-{match.group(4)}" if match.group(4) else base


def parse_version(value) -> tuple[int, int, int, str | None]:
    match = SEMVER.match(str(value or "").strip())
    if not match:
        raise ValueError(f"版本格式无效：{value}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)),
            match.group(4))


def is_newer(remote, local) -> bool:
    r = parse_version(remote)
    l = parse_version(local)
    if r[:3] != l[:3]:
        return r[:3] > l[:3]
    if r[3] is None and l[3] is not None:
        return True
    if r[3] is not None and l[3] is None:
        return False
    if r[3] == l[3]:
        return False
    return str(r[3]) > str(l[3])


def current_version(root: Path | None = None) -> str:
    root = Path(root or ROOT)
    path = root / "VERSION.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("version")
        return normalize_version(value)
    except (OSError, ValueError, AttributeError, TypeError):
        return "0.0.0-dev"


def is_development(root: Path | None = None) -> bool:
    return not (Path(root or ROOT) / "VERSION.json").is_file()


def _safe_url(url: str) -> bool:
    if not isinstance(url, str) or not url:
        return False
    parsed = urlsplit(url)
    if parsed.scheme == "https" and parsed.netloc:
        return True
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}


def validate_manifest(payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("更新清单格式无效")
    version = normalize_version(payload.get("version"))
    asset = payload.get("asset")
    if not isinstance(asset, dict):
        raise ValueError("更新清单缺少 asset")
    url = asset.get("url")
    if not _safe_url(url):
        raise ValueError("更新包地址必须使用 HTTPS")
    digest = str(asset.get("sha256", "")).lower()
    if not SHA256.fullmatch(digest):
        raise ValueError("更新清单 SHA-256 无效")
    try:
        size = int(asset["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("更新清单缺少文件大小") from exc
    if not 0 < size <= MAX_ARCHIVE_BYTES:
        raise ValueError("更新包大小超出限制")
    notes = payload.get("notes", [])
    if notes is None:
        notes = []
    if not isinstance(notes, list):
        notes = [str(notes)]
    return {
        "schema": 1,
        "version": version,
        "tag": str(payload.get("tag") or f"v{version}"),
        "release_date": str(payload.get("release_date") or ""),
        "notes_url": str(payload.get("notes_url") or ""),
        "notes": [str(item) for item in notes],
        "min_supported": (normalize_version(payload["min_supported"])
                          if payload.get("min_supported") else ""),
        "worker_protocol": int(payload.get("worker_protocol") or 1),
        "asset": {
            "url": url,
            "sha256": digest,
            "size": size,
        },
    }


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def mark_startup(*, version: str | None = None, ok: bool = False,
                 phase: str = "", error: str = "", port: int | None = None) -> None:
    """Write the health marker used by the update worker. Safe to call often."""
    runtime = RUNTIME
    data = {
        "token": os.environ.get("DIANTAO_UPDATE_TOKEN", ""),
        "pid": os.getpid(),
        "version": normalize_version(version or current_version(ROOT)),
        "port": port,
        "ok": bool(ok),
        "phase": phase,
        "error": str(error),
        "ts": time.time(),
    }
    try:
        _atomic_json(runtime / "startup.json", data)
    except OSError:
        pass


def _last_result() -> dict:
    try:
        return json.loads((RUNTIME / "last_result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _zip_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = Path(normalized)
    if (not normalized or normalized.startswith("/") or ".." in path.parts
            or re.match(r"^[A-Za-z]:", normalized)):
        raise ValueError(f"更新包路径无效：{name}")
    return normalized


def _extract_zip(archive_path: Path, staging: Path, version: str) -> dict:
    import zipfile

    staging.mkdir(parents=True, exist_ok=True)
    prefix = f"diantao-workbench-v{version}/"
    manifest = None
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        files = [entry for entry in archive.infolist() if not entry.is_dir()]
        if not files or len(files) > MAX_ENTRIES:
            raise ValueError("更新包文件数量异常")
        for entry in files:
            name = _zip_member_name(entry.filename)
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("更新包不允许符号链接")
            if not name.startswith(prefix):
                raise ValueError("更新包顶层目录与版本不匹配")
            total += entry.file_size
            if total > MAX_ARCHIVE_BYTES:
                raise ValueError("更新包解压后体积超出限制")
            relative = name[len(prefix):]
            if not relative:
                continue
            if relative == "manifest.json":
                data = archive.read(entry)
                manifest = json.loads(data.decode("utf-8"))
                (staging / "manifest.json").write_bytes(data)
                continue
            destination = (staging / relative).resolve()
            if staging.resolve() not in destination.parents and destination != staging.resolve():
                raise ValueError("更新包路径越界")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
    if not isinstance(manifest, dict):
        raise ValueError("更新包缺少 manifest.json")
    if normalize_version(manifest.get("version")) != version:
        raise ValueError("更新包 manifest 版本不匹配")
    entries = manifest.get("files")
    if not isinstance(entries, dict):
        raise ValueError("更新包 manifest 缺少文件清单")
    for relative, meta in entries.items():
        relative = _zip_member_name(relative)
        target = staging / relative
        if not target.is_file():
            raise ValueError(f"更新包缺少文件：{relative}")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != str(meta.get("sha256", "")).lower():
            raise ValueError(f"更新包文件校验失败：{relative}")
    for required in REQUIRED_FILES:
        if not (staging / required).is_file():
            raise ValueError(f"更新包缺少必需文件：{required}")
    if normalize_version(json.loads((staging / "VERSION.json").read_text(encoding="utf-8"))["version"]) != version:
        raise ValueError("更新包 VERSION.json 版本不匹配")
    return manifest


class UpdateManager:
    def __init__(self, root: Path, runtime: Path,
                 running_check: Callable[[], list[str]],
                 stop_tasks: Callable[[], None],
                 exit_process: Callable[[int], None]):
        self.root = Path(root)
        self.runtime = Path(runtime)
        self.running_check = running_check
        self.stop_tasks = stop_tasks
        self.exit_process = exit_process
        self.lock = threading.Lock()
        self.state = "idle"
        self.progress = 0
        self.phase = "等待检查"
        self.message = "点击检查更新"
        self.error = ""
        self.latest: dict | None = None
        self.started_at = 0.0
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._zip: Path | None = None
        self._staging: Path | None = None

    def _snapshot_unlocked(self) -> dict:
        current = current_version(self.root)
        latest = self.latest or {}
        running = []
        try:
            running = list(self.running_check())
        except Exception:
            running = []
        blocked = ""
        if is_development(self.root):
            blocked = "开发版不支持自动更新"
        elif running:
            blocked = "检测到任务正在运行，请先停止任务"
        elif latest and latest.get("min_supported") and is_newer(latest["min_supported"], current):
            blocked = "当前版本过低，请手动下载完整包"
        can_install = (self.state in {"available", "downloaded"}
                       or (self.state == "failed" and bool(latest)))
        can_install = can_install and not blocked and not is_development(self.root)
        return {
            "status": self.state,
            "current_version": current,
            "latest_version": latest.get("version", ""),
            "progress": self.progress,
            "phase": self.phase,
            "message": self.message,
            "error": self.error,
            "update_available": bool(latest) and self.state in {
                "available", "downloading", "downloaded", "installing", "failed",
            },
            "can_install": can_install,
            "can_cancel": self.state == "downloading",
            "blocked_reason": blocked,
            "simulation": False,
            "release_notes": latest.get("notes", []),
            "latest": latest,
            "last_result": _last_result(),
            "is_dev": is_development(self.root),
        }

    def snapshot(self) -> dict:
        with self.lock:
            return self._snapshot_unlocked()

    def _set(self, **values) -> None:
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)

    def check(self) -> dict:
        with self.lock:
            if self.state in {"checking", "downloading", "installing"}:
                raise HTTPException(409, "更新正在进行")
            self.state = "checking"
            self.phase = "检查更新"
            self.message = "正在读取更新清单…"
            self.error = ""
            self.progress = 0
        self._thread = threading.Thread(target=self._check_worker, daemon=True)
        self._thread.start()
        return self.snapshot()

    def _check_worker(self) -> None:
        try:
            url = os.environ.get("DIANTAO_UPDATE_MANIFEST_URL") or DEFAULT_MANIFEST_URL
            response = requests.get(url, timeout=8, headers={"User-Agent": "Tearice-Updater/1.0"})
            response.raise_for_status()
            manifest = validate_manifest(response.json())
            current = current_version(self.root)
            if is_development(self.root):
                self._set(state="failed", phase="开发版", message="开发版不支持自动更新",
                          error="缺少 VERSION.json", latest=manifest)
                return
            if not is_newer(manifest["version"], current):
                self._set(state="up_to_date", phase="已是最新", message="当前已是最新版本",
                          latest=manifest, progress=0)
                return
            self._set(state="available", phase="发现新版本",
                      message=f"发现新版本 v{manifest['version']}", latest=manifest,
                      progress=0, error="")
        except Exception as exc:
            self._set(state="failed", phase="检查失败", message="检查更新失败",
                      error=str(exc))

    def download(self) -> dict:
        with self.lock:
            if self.state in {"checking", "downloading", "installing"}:
                raise HTTPException(409, "更新正在进行")
            if self.state == "up_to_date":
                raise HTTPException(409, "当前已是最新版本")
            if not self.latest:
                raise HTTPException(409, "请先检查更新")
            self.state = "downloading"
            self.phase = "下载更新"
            self.message = "正在下载更新包…"
            self.error = ""
            self.progress = 0
            self._cancel.clear()
        self._thread = threading.Thread(target=self._download_worker, daemon=True)
        self._thread.start()
        return self.snapshot()

    def _download_worker(self) -> bool:
        try:
            latest = self.latest or {}
            asset = latest["asset"]
            version = latest["version"]
            directory = self.runtime / version
            directory.mkdir(parents=True, exist_ok=True)
            part = directory / "package.zip.part"
            target = directory / "package.zip"
            total = int(asset["size"])
            digest = hashlib.sha256()
            received = 0
            with requests.get(asset["url"], stream=True, timeout=(10, 90),
                              headers={"User-Agent": "Tearice-Updater/1.0"}) as response:
                response.raise_for_status()
                with part.open("wb") as output:
                    for chunk in response.iter_content(CHUNK):
                        if self._cancel.is_set():
                            part.unlink(missing_ok=True)
                            self._set(state="available", phase="已取消",
                                      message="已取消下载", progress=0)
                            return False
                        if not chunk:
                            continue
                        output.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        with self.lock:
                            self.progress = min(99, int(received / total * 100))
            if received != total:
                raise ValueError(f"下载大小不一致：{received} != {total}")
            if digest.hexdigest() != asset["sha256"]:
                raise ValueError("更新包 SHA-256 校验失败")
            os.replace(part, target)
            self._zip = target
            self._set(phase="解压更新包", message="正在校验并解压更新包…", progress=99)
            staging = directory / "staging"
            if staging.exists():
                shutil.rmtree(staging)
            _extract_zip(target, staging, version)
            self._staging = staging
            self._set(state="downloaded", phase="准备安装",
                      message="更新包已就绪，可以安装", progress=100, error="")
            return True
        except Exception as exc:
            self._set(state="failed", phase="下载失败", message="更新下载失败",
                      error=str(exc))
            return False

    def install(self) -> dict:
        with self.lock:
            if self.state in {"checking", "downloading", "installing"}:
                raise HTTPException(409, "更新正在进行")
            if self.state == "up_to_date":
                raise HTTPException(409, "当前已是最新版本")
            if not self.latest:
                raise HTTPException(409, "请先检查更新")
            running = list(self.running_check())
            if running:
                raise HTTPException(409, "检测到任务正在运行，请先停止任务")
            if is_development(self.root):
                raise HTTPException(409, "开发版不支持自动更新")
            min_supported = self.latest.get("min_supported")
            if min_supported and is_newer(min_supported, current_version(self.root)):
                raise HTTPException(409, "当前版本过低，请手动下载完整包")
            if self.state == "downloaded":
                self._thread = threading.Thread(target=self._apply, daemon=True)
                self._thread.start()
                return self.snapshot()
            self.state = "downloading"
            self.phase = "下载更新"
            self.message = "正在下载更新包…"
            self.error = ""
            self.progress = 0
            self._cancel.clear()
        self._thread = threading.Thread(target=self._download_then_apply, daemon=True)
        self._thread.start()
        return self.snapshot()

    def _download_then_apply(self) -> None:
        if not self._download_worker():
            return
        self._apply()

    def _apply(self) -> None:
        try:
            with self.lock:
                running = list(self.running_check())
                if running:
                    raise RuntimeError("检测到任务正在运行，请先停止任务")
                if not self._staging or not self.latest:
                    raise RuntimeError("更新包尚未准备完成")
                version = self.latest["version"]
                directory = self.runtime / version
                worker_source = self.root / "workbench" / "update_worker.py"
                worker_path = directory / "update_worker.py"
                shutil.copy2(worker_source, worker_path)
                backup = self.runtime / "backup" / f"{version}-{int(time.time())}"
                log = directory / "worker.log"
                token = secrets.token_urlsafe(32)
                environment = os.environ.copy()
                for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
                    environment.pop(key, None)
                environment.update({
                    "DIANTAO_UPDATE_TOKEN": token,
                    "DIANTAO_NO_PAUSE": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                })
                command = [
                    str(sys.executable), str(worker_path),
                    "--root", str(self.root),
                    "--staging", str(self._staging),
                    "--backup", str(backup),
                    "--parent-pid", str(os.getpid()),
                    "--token", token,
                    "--launcher", str(self.root / "启动大管家.cmd"),
                    "--uv", shutil.which("uv") or "",
                    "--health-timeout", "120",
                    "--log", str(log),
                ]
                with log.open("ab") as output:
                    worker = subprocess.Popen(
                        command, cwd=str(self.root), env=environment,
                        stdin=subprocess.DEVNULL, stdout=output,
                        stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                    )
                self.state = "installing"
                self.phase = "正在安装"
                self.message = "正在退出并安装更新，请勿关闭电脑…"
                self.progress = 100
                self.error = ""
                worker_pid = worker.pid
            threading.Timer(1.0, self._exit_for_update).start()
            return
        except Exception as exc:
            self._set(state="failed", phase="安装失败", message="无法启动更新器",
                      error=str(exc))
        # unreachable when Popen succeeds
        return

    def _exit_for_update(self) -> None:
        try:
            self.stop_tasks()
        finally:
            self.exit_process(0)

    def cancel(self) -> dict:
        with self.lock:
            if self.state != "downloading":
                raise HTTPException(409, "当前没有可取消的下载")
            self._cancel.set()
            self.phase = "正在取消"
            self.message = "正在取消下载…"
        return self.snapshot()

    def is_installing(self) -> bool:
        with self.lock:
            return self.state == "installing"


def configure_updater(root: Path, runtime: Path,
                      running_check: Callable[[], list[str]],
                      stop_tasks: Callable[[], None],
                      exit_process: Callable[[int], None]) -> None:
    global _manager, ROOT, RUNTIME, _running_check, _stop_tasks, _exit_process
    ROOT = Path(root)
    RUNTIME = Path(runtime)
    _running_check = running_check
    _stop_tasks = stop_tasks
    _exit_process = exit_process
    _manager = UpdateManager(ROOT, RUNTIME, running_check, stop_tasks, exit_process)


def manager() -> UpdateManager:
    if _manager is None:
        raise HTTPException(503, "更新服务未初始化")
    return _manager


def is_installing() -> bool:
    return _manager.is_installing() if _manager is not None else False


@_router.get("/status")
def update_status():
    return manager().snapshot()


@_router.post("/check")
def update_check():
    return {"ok": True, "message": "已开始检查更新", "update": manager().check()}


@_router.post("/download")
def update_download():
    return {"ok": True, "message": "已开始下载更新", "update": manager().download()}


@_router.post("/install")
def update_install():
    return {"ok": True, "message": "已开始安装更新", "update": manager().install()}


@_router.post("/cancel")
def update_cancel():
    return {"ok": True, "message": "已取消下载", "update": manager().cancel()}


router = _router
