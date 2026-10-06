"""按固定顺序启动九个点淘脚本，保留各子脚本现有执行逻辑。"""

import argparse
import signal
from pathlib import Path
from threading import Event

from task_runner import run_script


SCRIPT_DIR = Path(__file__).resolve().parent
# 使用现有任务选择器的超时预算；连通性导航单独预留 30 分钟。
TASKS = (
    ("连通性脚本.py", 1800),
    ("一键下滑.py", 2100),
    ("主播打卡粉丝礼.py", 2100),
    ("签到赢元宝.py", 2100),
    ("睡觉赚元宝.py", 3600),
    ("点淘鸭钻石任务.py", 2100),
    ("点淘鸭摇一摇.py", 2100),
    ("点淘购物赚钱.py", 2100),
    ("打工得体力.py", 3600),
)


def execute(stop=None):
    """串行执行一轮；失败/超时继续下一项，停止信号取消后续项。"""
    stop = stop if stop is not None else Event()
    missing = [filename for filename, _ in TASKS if not (SCRIPT_DIR / filename).is_file()]
    if missing:
        print(f"缺少脚本：{', '.join(missing)}", flush=True)
        return 1

    results = []
    for index, (filename, timeout) in enumerate(TASKS, 1):
        if stop.is_set():
            break
        print(f"\n[{index}/{len(TASKS)}] 启动 {filename}（超时 {timeout}s）", flush=True)
        try:
            success, elapsed, reason = run_script(
                SCRIPT_DIR / filename, cwd=SCRIPT_DIR, timeout=timeout,
                should_stop=stop.is_set,
                on_line=lambda line: print(line, flush=True),
            )
        except Exception as exc:
            success, elapsed, reason = False, 0, f"启动异常：{exc}"
        results.append((filename, success, reason))
        print(f"{filename}：{reason}（{elapsed:.1f}s）", flush=True)

    print("\n执行汇总：", flush=True)
    for filename, success, reason in results:
        print(f"  {'成功' if success else '失败'} | {filename} | {reason}", flush=True)
    if stop.is_set():
        print("已停止，后续脚本未启动。", flush=True)
        return 130
    return 0 if len(results) == len(TASKS) and all(r[1] for r in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="仅显示执行顺序，不操作设备")
    args = parser.parse_args()
    if args.list:
        for index, (filename, timeout) in enumerate(TASKS, 1):
            print(f"{index}. {filename}（{timeout}s）")
        return 0

    stop = Event()

    def request_stop(signum, frame):
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, request_stop)
    return execute(stop)


if __name__ == "__main__":
    raise SystemExit(main())
