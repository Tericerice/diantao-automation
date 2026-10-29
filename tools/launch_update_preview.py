"""Start the isolated update-preview window with the workbench Python runtime."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / "workbench" / ".venv"
PYTHONW = Path(sys.base_prefix) / "pythonw.exe"

if not PYTHONW.is_file():
    raise SystemExit(f"pythonw.exe not found: {PYTHONW}")

environment = os.environ.copy()
environment["PYTHONPATH"] = os.pathsep.join(
    [str(VENV / "Lib" / "site-packages"), str(ROOT)]
)
environment.setdefault("PYTHONIOENCODING", "utf-8")
environment.setdefault("PYTHONUTF8", "1")

runtime = ROOT / ".runtime" / "workbench_update_preview"
runtime.mkdir(parents=True, exist_ok=True)
log = runtime / "launcher.log"
child_log = runtime / "preview-child.log"
try:
    with child_log.open("ab") as output:
        process = subprocess.Popen(
            [str(PYTHONW), "-m", "workbench_update_preview.app"],
            cwd=str(ROOT),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
except Exception as error:
    log.write_text(f"failed: {error}\npythonw={PYTHONW}\n", encoding="utf-8")
    raise
log.write_text(f"started pid={process.pid}\npythonw={PYTHONW}\n", encoding="utf-8")
