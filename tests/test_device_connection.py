"""连接重试测试不操作手机。"""
import ast
import unittest
from http.client import RemoteDisconnected
from pathlib import Path
from unittest.mock import patch, sentinel

import device_connection


class DeviceConnectionTest(unittest.TestCase):
    def connect(self, results):
        return patch.object(device_connection.u2, "connect", side_effect=results)

    def test_success_does_not_sleep_or_retry(self):
        with self.connect([sentinel.device]) as connect, patch.object(device_connection.time, "sleep") as sleep:
            self.assertIs(device_connection.connect_with_retry("phone-a"), sentinel.device)
        connect.assert_called_once_with("phone-a")
        sleep.assert_not_called()

    def test_transient_disconnect_retries_same_device(self):
        for error in (RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError):
            with self.subTest(error=error), self.connect([error("断开"), sentinel.device]) as connect, \
                    patch.object(device_connection.time, "sleep") as sleep:
                self.assertIs(device_connection.connect_with_retry("phone-a"), sentinel.device)
                self.assertEqual([c.args for c in connect.call_args_list], [("phone-a",), ("phone-a",)])
                sleep.assert_called_once_with(2)

    def test_persistent_failure_is_bounded_and_preserves_exception(self):
        error = RemoteDisconnected("持续中断")
        with self.connect([error] * 3) as connect, patch.object(device_connection.time, "sleep") as sleep:
            with self.assertRaises(RemoteDisconnected) as raised:
                device_connection.connect_with_retry("phone-a")
        self.assertIs(raised.exception, error)
        self.assertEqual(connect.call_count, 3)
        self.assertEqual([c.args for c in sleep.call_args_list], [(2,), (4,)])

    def test_non_transport_error_is_not_retried(self):
        with self.connect([ValueError("错误配置")]) as connect, patch.object(device_connection.time, "sleep") as sleep:
            with self.assertRaises(ValueError):
                device_connection.connect_with_retry("phone-a")
        self.assertEqual(connect.call_count, 1)
        sleep.assert_not_called()

    def test_both_entry_points_use_retry_before_starting_watcher(self):
        root = Path(__file__).parents[1]
        for filename in ("utils.py", "u2_scanner.py"):
            with self.subTest(filename=filename):
                tree = ast.parse((root / filename).read_text(encoding="utf-8-sig"))
                func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "connect_device")
                calls = [n for n in ast.walk(func) if isinstance(n, ast.Call)]
                self.assertTrue(any(isinstance(n.func, ast.Name) and n.func.id == "connect_with_retry" for n in calls))
                self.assertFalse(any(isinstance(n.func, ast.Attribute) and n.func.attr == "connect" for n in calls))


if __name__ == "__main__":
    unittest.main()
