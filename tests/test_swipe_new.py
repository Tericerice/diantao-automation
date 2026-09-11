import sys
import types
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import importlib.util


class SwipeNewContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 隔离加载 一键下滑_新.py，防止顶层产生设备依赖
        script_path = Path(__file__).parents[1] / "一键下滑_新.py"
        spec = importlib.util.spec_from_file_location("swipe_new_mod", script_path)
        assert spec is not None and spec.loader is not None
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_rounds_config_has_all_six_standard_tasks(self):
        # Given: the new script configuration
        config = self.module.ROUNDS_CONFIG

        # Then: exactly 6 rounds with standard names
        expected_names = [
            "打工赚元宝",
            "睡觉赚元宝",
            "签到赢元宝",
            "购物赚钱",
            "摇一摇",
            "走路赚元宝",
        ]
        actual_names = [r["name"] for r in config]
        self.assertEqual(actual_names, expected_names)

    def test_run_round_skips_swiping_when_navigation_fails(self):
        # Given: navigation fails (e.g. entry not found)
        mock_device = MagicMock()
        mock_nav = MagicMock(return_value=False)

        with patch.object(self.module, "_nav_to_yuanbao_center", return_value=True), \
             patch.object(self.module, "swipe_browse") as mock_swipe:

            # When: running the round
            result = self.module.run_round(
                device=mock_device,
                label="1",
                name="打工赚元宝",
                swipe_seconds=240,
                nav_func=mock_nav,
                sw=1080,
                sh=2400,
            )

            # Then: navigation failure blocks swiping and reports False
            self.assertFalse(result)
            mock_swipe.assert_not_called()

    def test_run_round_swipes_when_navigation_succeeds(self):
        # Given: navigation succeeds
        mock_device = MagicMock()
        mock_nav = MagicMock(return_value=True)

        with patch.object(self.module, "_nav_to_yuanbao_center", return_value=True), \
             patch.object(self.module, "swipe_browse") as mock_swipe:

            # When: running the round
            result = self.module.run_round(
                device=mock_device,
                label="1",
                name="打工赚元宝",
                swipe_seconds=240,
                nav_func=mock_nav,
                sw=1080,
                sh=2400,
            )

            # Then: navigation success executes swipe_browse and reports True
            self.assertTrue(result)
            mock_swipe.assert_called_once_with(mock_device, 240, 1080, 2400)


if __name__ == "__main__":
    unittest.main()
