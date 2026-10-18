import unittest

from utils import click_device_point, click_u2_control


class ClickDispatchTest(unittest.TestCase):
    def test_click_device_point_emits_device_tap(self):
        # Given: a device recorder and the task button coordinates.
        device = _FakeDevice()

        # When: the coordinate click helper is used.
        clicked = click_device_point(device, 456, 789, "视频任务按钮")

        # Then: one device-level tap is dispatched at the requested point.
        self.assertTrue(clicked)
        self.assertEqual(device.taps, [(456, 789)])

    def test_click_u2_control_dispatches_center_as_device_tap(self):
        # Given: a UI selector with a known center and a device recorder.
        device = _FakeDevice()
        control = _FakeControl(center=(321, 654))

        # When: the shared click helper is used.
        clicked = click_u2_control(device, control, "测试控件")

        # Then: the helper emits one device-level tap at the selector center.
        self.assertTrue(clicked)
        self.assertEqual(device.taps, [(321, 654)])


class _FakeDevice:
    def __init__(self):
        self.taps = []

    def click(self, x, y):
        self.taps.append((x, y))


class _FakeControl:
    def __init__(self, center):
        self._center = center

    def center(self):
        return self._center


if __name__ == "__main__":
    unittest.main()
