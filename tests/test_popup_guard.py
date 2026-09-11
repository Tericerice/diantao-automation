import sys
import types
import unittest


sys.modules.setdefault("uiautomator2", types.ModuleType("uiautomator2"))

import u2_scanner


class _Selector:
    def __init__(self, center, exists):
        self._center = center
        self.exists = exists

    def center(self):
        return self._center


class _Device:
    def __init__(self):
        self.taps = []

    def window_size(self):
        return 1264, 2780

    def __call__(self, **kwargs):
        if kwargs.get("textContains") == "X":
            return _Selector((457, 2266), True)
        return _Selector((0, 0), False)

    def click(self, x, y):
        self.taps.append((x, y))


class PopupGuardTest(unittest.TestCase):
    def test_bottom_x_is_not_clicked_as_a_popup_close_control(self):
        # Given: a product-area X label below the popup safety region.
        device = _Device()
        original_scan_page = u2_scanner.scan_page
        u2_scanner.scan_page = lambda _device: []

        try:
            # When: live popup cleanup scans the current video page.
            u2_scanner.close_live_popups(device)

            # Then: the bottom product control is not tapped.
            self.assertEqual(device.taps, [])
        finally:
            u2_scanner.scan_page = original_scan_page


if __name__ == "__main__":
    unittest.main()
