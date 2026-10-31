"""Standalone update worker: wait for the app to exit, swap files, restart, verify.

This file must remain standard-library only. It is copied out of the installed
tree and launched as a separate process before the main app exits.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
WORKER_PROTOCOL = 1
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
REQUIRED_FILES = (
    "启动大管家.cmd", "启动工作台.cmd", "配置本机.cmd", "local_config.py",
    "VERSION.json", "workbench/app.py", "workbench/updater.py",
    "workbench/update_worker.py", "workbench/uv.lock",
)
PROTECTED_PARTS = {
    ".runtime", ".venv", ".git", "__pycache__", "dist", "screenshots",
    "logs", "ocr_debug", "tests",
}


def normalize_version(value) -> str:
    match = SEMVER.match(str(value or "").strip())
    if not match:
        raise ValueError(f"版本格式无效：{value}")
    base = f"{int(match.group(1))}.{int(match.group(2))}.{int(match.group(3))}"
    return f"{base}-{match.group(4)}" if match.group(4) else base


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = ctypes.c_ulong()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def wait_for_parent(pid: int, timeout: float = 90.0) -> None:
    if pid <= 0:
        return
    deadline = time.time() + timeout
    while time.time() < deadline and process_alive(pid):
        time.sleep(0.25)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def retry_operation(callback, attempts: int = 40):
    delay = 0.05
    last = None
    for _ in range(attempts):
        try:
            return callback()
        except OSError as exc:
            last = exc
            time.sleep(delay)
            delay = min(0.5, delay * 1.6)
    raise last


def move(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    retry_operation(lambda: os.replace(src, dest))


def remove_file(path: Path) -> None:
    if path.is_file():
        retry_operation(lambda: path.unlink(missing_ok=True))


def protected(relative: str) -> bool:
    parts = Path(relative).parts
    if any(part in PROTECTED_PARTS for part in parts):
        return True
    name = parts[-1] if parts else ""
    return name == ".env" or name.startswith(".env.") or name == "task_config.json"


class Journal:
    def __init__(self, path: Path):
        self.path = path
        self.ops: list[dict] = []
        self.completed = False
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        data = read_json(self.path)
        self.ops = list(data.get("ops", []))
        self.completed = bool(data.get("completed"))

    def write(self) -> None:
        atomic_json(self.path, {"ops": self.ops, "completed": self.completed})

    def begin(self, op: dict) -> None:
        op["status"] = "begin"
        self.ops.append(op)
        self.write()

    def done(self, op: dict) -> None:
        op["status"] = "done"
        self.write()

    def finish(self) -> None:
        self.completed = True
        self.write()

    def rollback(self) -> None:
        for op in reversed(self.ops):
            if op.get("status") not in {"begin", "done"}:
                continue
            dest = Path(op["dest"])
            backup = Path(op["backup"])
            try:
                if dest.is_file():
                    dest.unlink()
                if backup.is_file():
                    move(backup, dest)
            except OSError as exc:
                print(f"[rollback] {dest}: {exc}", flush=True)


def verify_staging(staging: Path, version: str) -> dict:
    manifest_path = staging / "manifest.json"
    manifest = read_json(manifest_path)
    if not manifest:
        raise ValueError("staging 缺少 manifest.json")
    if normalize_version(manifest.get("version")) != version:
        raise ValueError("staging 版本不匹配")
    if int(manifest.get("worker_protocol", 1)) != WORKER_PROTOCOL:
        raise ValueError("更新器协议不兼容，请手动下载完整包")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("manifest 文件清单无效")
    for relative, meta in files.items():
        target = staging / relative
        if not target.is_file():
            raise ValueError(f"staging 缺少文件：{relative}")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != str(meta.get("sha256", "")).lower():
            raise ValueError(f"staging 文件校验失败：{relative}")
    for required in REQUIRED_FILES:
        if not (staging / required).is_file():
            raise ValueError(f"staging 缺少必需文件：{required}")
    return manifest


def find_uv(explicit: str) -> str | None:
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("uv")
    if found:
        return found
    candidates = [
        Path.home() / ".local" / "bin" / "uv.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "uv.exe",
        Path(os.environ.get("APPDATA", "")) / "Python" / "Scripts" / "uv.exe",
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


def run_uv(uv: str | None, root: Path, log) -> bool:
    if not uv:
        print("[uv] 未找到 uv，无法同步依赖", file=log, flush=True)
        return False
    command = [uv, "sync", "--project", str(root / "workbench"), "--no-dev", "--locked"]
    print("[uv] " + " ".join(command), file=log, flush=True)
    try:
        result = subprocess.run(command, cwd=str(root), capture_output=True,
                                text=True, encoding="utf-8", errors="replace",
                                timeout=300, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[uv] 执行失败：{exc}", file=log, flush=True)
        return False
    print(result.stdout or "", file=log, flush=True)
    if result.returncode != 0:
        print(result.stderr or "", file=log, flush=True)
        print(f"[uv] 退出码 {result.returncode}", file=log, flush=True)
        return False
    return True


def launch(launcher: Path, root: Path, token: str, log) -> None:
    environment = os.environ.copy()
    environment.update({
        "DIANTAO_UPDATE_TOKEN": token,
        "DIANTAO_NO_PAUSE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })
    command = ["cmd.exe", "/d", "/s", "/c", f'call "{launcher}"']
    print("[launch] " + " ".join(command), file=log, flush=True)
    subprocess.Popen(command, cwd=str(root), env=environment,
                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                     creationflags=NO_WINDOW)


def wait_for_health(root: Path, token: str, version: str, timeout: float, log) -> tuple[bool, dict]:
    marker = root / ".runtime" / "update" / "startup.json"
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        data = read_json(marker)
        last = data
        if data and data.get("token") == token:
            if data.get("ok") is False and data.get("phase") == "failed":
                print(f"[health] 启动失败：{data.get('error', '')}", file=log, flush=True)
                return False, data
            try:
                marker_version = normalize_version(data.get("version"))
            except ValueError:
                marker_version = ""
            if (data.get("ok") is True
                    and marker_version == version
                    and process_alive(int(data.get("pid") or 0))):
                port = data.get("port")
                if port:
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/api/health", timeout=2
                        ) as response:
                            health = json.loads(response.read().decode("utf-8"))
                        if normalize_version(health.get("version")) == version:
                            return True, data
                    except (OSError, ValueError):
                        pass
        time.sleep(1.0)
    return False, last


def kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, creationflags=NO_WINDOW)


def write_result(root: Path, **values) -> None:
    values.setdefault("ts", datetime.now(timezone.utc).isoformat())
    atomic_json(root / ".runtime" / "update" / "last_result.json", values)


def run(args) -> int:
    root = Path(args.root).resolve()
    staging = Path(args.staging).resolve()
    backup = Path(args.backup).resolve()
    launcher = Path(args.launcher).resolve()
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8", errors="replace")

    lock_path = root / ".runtime" / "update" / "worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            old_pid = int(lock_path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            old_pid = 0
        if old_pid and process_alive(old_pid):
            print("[worker] 已有更新器在运行", file=log, flush=True)
            return 1
        lock_path.unlink(missing_ok=True)
        lock = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(lock, str(os.getpid()).encode("ascii"))
    os.close(lock)
    import atexit
    atexit.register(lambda: lock_path.unlink(missing_ok=True))

    journal = Journal(root / ".runtime" / "update" / "journal.json")
    journal.load()
    if journal.ops and not journal.completed:
        print("[worker] 发现未完成 journal，先回滚", file=log, flush=True)
        journal.rollback()
        journal.finish()
        journal.ops = []
        journal.completed = False

    try:
        version = normalize_version(read_json(staging / "VERSION.json").get("version"))
    except ValueError:
        print("[worker] staging 版本无效", file=log, flush=True)
        return 1

    print(f"[worker] 等待主进程 {args.parent_pid} 退出", file=log, flush=True)
    wait_for_parent(args.parent_pid)
    try:
        manifest = verify_staging(staging, version)
    except Exception as exc:
        print(f"[worker] staging 校验失败：{exc}", file=log, flush=True)
        write_result(root, ok=False, version=version, error=str(exc))
        return 1

    uv = find_uv(args.uv)
    if not uv:
        error = "未找到 uv，无法同步依赖"
        print(f"[worker] {error}", file=log, flush=True)
        write_result(root, ok=False, version=version, error=error)
        return 1

    backup.mkdir(parents=True, exist_ok=True)
    new_files = set()
    try:
        for source in sorted(staging.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(staging).as_posix()
            if relative == "manifest.json" or protected(relative):
                continue
            new_files.add(relative)
            dest = root / relative
            backup_path = backup / relative
            op = {"op": "replace", "dest": str(dest), "backup": str(backup_path),
                  "had_old": dest.exists()}
            journal.begin(op)
            if dest.exists():
                move(dest, backup_path)
            move(source, dest)
            journal.done(op)

        old_manifest = read_json(root / ".runtime" / "workbench" / "installed_manifest.json")
        for relative in old_manifest.get("files", {}):
            if relative in new_files or protected(relative):
                continue
            dest = root / relative
            if not dest.is_file():
                continue
            op = {"op": "remove_old", "dest": str(dest),
                  "backup": str(backup / relative), "had_old": True}
            journal.begin(op)
            move(dest, backup / relative)
            journal.done(op)
    except Exception as exc:
        print(f"[worker] 文件替换失败：{exc}", file=log, flush=True)
        journal.rollback()
        write_result(root, ok=False, version=version, error=str(exc))
        return 1

    if not run_uv(uv, root, log):
        print("[worker] uv sync 失败，开始回滚", file=log, flush=True)
        journal.rollback()
        run_uv(uv, root, log)
        launch(launcher, root, "", log)
        write_result(root, ok=False, version=version, error="uv sync 失败，已回滚")
        return 1

    marker = root / ".runtime" / "update" / "startup.json"
    marker.unlink(missing_ok=True)
    launch(launcher, root, args.token, log)
    ok, data = wait_for_health(root, args.token, version, args.health_timeout, log)
    if not ok:
        print("[worker] 新版本未通过健康检查，开始回滚", file=log, flush=True)
        kill_pid(int(data.get("pid") or 0))
        journal.rollback()
        run_uv(uv, root, log)
        launch(launcher, root, "", log)
        write_result(root, ok=False, version=version,
                     error="新版本启动失败，已回滚", marker=data)
        return 1

    atomic_json(root / ".runtime" / "workbench" / "installed_manifest.json", manifest)
    journal.finish()
    write_result(root, ok=True, version=version)
    print("[worker] 更新完成", file=log, flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--staging", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--token", default="")
    parser.add_argument("--launcher", required=True)
    parser.add_argument("--uv", default="")
    parser.add_argument("--health-timeout", type=float, default=120)
    parser.add_argument("--log", required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[worker] 未处理异常：{exc}", file=sys.stderr)
        raise
