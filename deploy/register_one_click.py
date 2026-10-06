"""将点淘一键入口注册到指定自动化大管家目录的 Python 脚本分类。"""

import argparse
import json
from pathlib import Path


TARGET_ID = "diantao-one-click"
SCRIPT_DIR = Path(__file__).resolve().parents[1]


def register(butler_dir):
    # 插入独立条目，保留现有配置文本和所有其他条目；重复注册不会新增按钮。
    registry = butler_dir / "tools" / "managed_process" / "registry.yaml"
    source = registry.read_text(encoding="utf-8")
    if f"  - id: {TARGET_ID}\n" not in source:
        command_path = json.dumps((SCRIPT_DIR / "一键顺序执行.py").as_posix(), ensure_ascii=False)
        working_dir = json.dumps(SCRIPT_DIR.as_posix(), ensure_ascii=False)
        entry = (
            f"  - id: {TARGET_ID}\n"
            '    name: "点淘一键顺序执行"\n'
            "    category: script\n"
            "    lifecycle: managed_job\n"
            f'    command: ["${{PYTHON}}", {command_path}]\n'
            f"    working_directory: {working_dir}\n"
            '    description: "连通性 → 下滑 → 主播 → 签到 → 睡觉 → 钻石 → 摇一摇 → 购物 → 打工"\n'
            "    risk: device_automation\n"
            "    enabled: true\n"
            "    requires_human_approval: false\n\n"
        )
        marker = "  - id: diantao-anchor\n"
        if marker not in source:
            raise ValueError("未找到大管家点淘脚本分类的注册位置")
        registry.write_text(source.replace(marker, entry + marker, 1), encoding="utf-8")
    print(f"已注册点淘一键顺序执行：{registry}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("butler_dir", type=Path, help="自动化大管家目录")
    register(parser.parse_args().butler_dir)
