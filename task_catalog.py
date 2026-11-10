"""允许进入批量调度的业务脚本；工具、校准脚本不参与自动发现。"""
from task_exclusions import is_blocked_task_file

TASK_FILES = frozenset({
    "618花花乐.py", "diantao_1024_auto.py", "一键下滑.py", "一键下滑_新.py",
    "主播打卡粉丝礼.py", "元宝中心小任务.py", "合成百元大红包.py",
    "打工加速.py", "打工得体力.py", "淘金币任务.py", "点淘购物赚钱.py",
    "点淘鸭摇一摇.py", "点淘鸭钻石任务.py", "摇一摇.py",
    "睡觉赚元宝.py", "签到赢元宝.py", "走路赚元宝.py", "赚钱卡.py", "养优惠.py",
    "../coin11-tb-main/2026淘宝618活动.py",
})


def is_task_file(filename: str) -> bool:
    # 用户 2026-11-10 指示：睡觉赚元宝加入黑名单，绕过 checked 的发现路径也拒绝调度。
    return (filename.replace("\\", "/") in TASK_FILES
            and not is_blocked_task_file(filename))
