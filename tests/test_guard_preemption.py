"""真实进程树抢占测试，仅写测试日志，不调用 ADB 或手机。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from phone_control import CONTROL_ENV, PhoneLock, guardian_turn
from task_host import NO_WINDOW, run_host, stop_tree


ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError("等待模拟任务状态超时")


def events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    monkeypatch.setenv(CONTROL_ENV, str(tmp_path / "control"))
    monkeypatch.setenv("PYTHONPATH", str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setenv("SCENARIO", str(tmp_path))
    common = """
import json,os,time
from pathlib import Path
base=Path(os.environ['SCENARIO'])
def log(name):
    with (base/'events.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps([name,time.time(),os.getpid()])+chr(10))
"""
    (tmp_path / "grandchild.py").write_text(common + """
while True:
    log('grandchild')
    time.sleep(.03)
""", encoding="utf-8")
    (tmp_path / "swipe.py").write_text(common + """
import subprocess,sys
from task_checkpoint import run_step
def run(name):
    log(name+' begin')
    if name=='睡觉' and not (base/'guard_done').exists():
        p=subprocess.Popen([sys.executable,str(base/'grandchild.py')])
        (base/'grandchild.pid').write_text(str(p.pid))
        (base/'sleep_ready').touch()
        while True: time.sleep(.05)
    log(name+' end')
for name in ['打工','睡觉','赚钱']:
    run_step(name,name,run,name)
""", encoding="utf-8")
    (tmp_path / "sign.py").write_text(common + "log('签到')\n", encoding="utf-8")
    (tmp_path / "flow.py").write_text(common + """
import sys
from task_runner import run_script
for script in ['sign.py','swipe.py']:
    ok,_,reason=run_script(base/script,cwd=base,timeout=None,
                          should_stop=lambda:False,on_line=lambda s:print(s,flush=True))
    if not ok: raise RuntimeError(reason)
log('后续任务')
""", encoding="utf-8")
    (tmp_path / "guardian.py").write_text(common + """
from phone_control import guardian_turn
with guardian_turn():
    log('guard begin')
    (base/'guard_ready').touch()
    time.sleep(.5)
    (base/'guard_done').touch()
    log('guard end')
    if os.environ.get('FAIL_GUARD')=='1': raise RuntimeError('模拟守护失败')
""", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("fail_guard", [False, True])
def test_real_nested_sequence_resumes_current_sleep_without_replaying_sign_or_work(scenario, fail_guard):
    output = (scenario / "host.log").open("w", encoding="utf-8")
    host = subprocess.Popen(
        [sys.executable, str(ROOT / "task_host.py"), "--",
         sys.executable, "-u", str(scenario / "flow.py")],
        stdout=output, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
        start_new_session=sys.platform != "win32",
    )
    priority = None
    try:
        wait_for(lambda: (scenario / "sleep_ready").exists())
        env = dict(os.environ)
        if fail_guard:
            env["FAIL_GUARD"] = "1"
        priority = subprocess.Popen(
            [sys.executable, str(scenario / "guardian.py")],
            env=env, stdout=output, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
            start_new_session=sys.platform != "win32",
        )
        assert priority.wait(timeout=10) == (1 if fail_guard else 0)
        assert host.wait(timeout=10) == 0
    finally:
        stop_tree(host)
        if priority:
            stop_tree(priority)
        output.close()
    rows = events(scenario / "events.jsonl")
    major = [row[0] for row in rows if row[0] != "grandchild"]
    assert major == [
        "签到", "打工 begin", "打工 end", "睡觉 begin",
        "guard begin", "guard end", "睡觉 begin", "睡觉 end",
        "赚钱 begin", "赚钱 end", "后续任务",
    ], (major, (scenario / "host.log").read_text(encoding="utf-8"))
    start = next(row[1] for row in rows if row[0] == "guard begin")
    end = next(row[1] for row in rows if row[0] == "guard end")
    assert not [row for row in rows if row[0] == "grandchild" and row[1] >= start]
    assert start < end
    assert "[让路] 保存当前大任务：睡觉" in (scenario / "host.log").read_text(encoding="utf-8")


def test_stop_while_guardian_is_running_never_restarts_sequence(scenario):
    stop = threading.Event()
    result = []
    runner = threading.Thread(
        target=lambda: result.append(run_host(
            [sys.executable, "-u", str(scenario / "flow.py")], should_stop=stop.is_set,
        )),
    )
    priority = None
    with (scenario / "guardian.log").open("w", encoding="utf-8") as output:
        runner.start()
        try:
            wait_for(lambda: (scenario / "sleep_ready").exists())
            priority = subprocess.Popen(
                [sys.executable, str(scenario / "guardian.py")],
                stdout=output, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                start_new_session=sys.platform != "win32",
            )
            wait_for(lambda: (scenario / "guard_ready").exists())
            stop.set()
            runner.join(timeout=5)
            assert not runner.is_alive()
            assert result == [130]
            assert priority.wait(timeout=10) == 0
        finally:
            stop.set()
            runner.join(timeout=5)
            if priority:
                stop_tree(priority)
    names = [row[0] for row in events(scenario / "events.jsonl")]
    assert names.count("睡觉 begin") == 1
    assert "赚钱 begin" not in names


def test_guard_releases_lease_even_if_task_raises(tmp_path):
    with pytest.raises(RuntimeError):
        with guardian_turn(tmp_path):
            raise RuntimeError("unknown screen")
    assert not list((tmp_path / "requests").glob("*.json"))
    lock = PhoneLock(tmp_path)
    assert lock.acquire()
    lock.release()
