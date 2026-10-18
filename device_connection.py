"""设备连接时对 U2 服务的短暂传输中断做有限重试。"""
import time
from http.client import RemoteDisconnected

import uiautomator2 as u2


def connect_with_retry(serial):
    for attempt in range(3):
        try:
            return u2.connect(serial)
        except (RemoteDisconnected, ConnectionResetError, ConnectionAbortedError,
                BrokenPipeError, TimeoutError) as exc:
            if attempt == 2:
                raise
            delay = 2 * (attempt + 1)
            print(f"  ⚠️ 手机 U2 服务连接中断：{exc}；{delay}秒后重试 ({attempt + 1}/2)")
            time.sleep(delay)
