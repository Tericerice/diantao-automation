"""养优惠的任务配对、执行顺序和进度复核，不连接手机。"""
import importlib
import unittest
from unittest.mock import Mock, patch

m = importlib.import_module("养优惠")


def block(text, x=400, y=1000):
    return {"text": text, "cx": x, "cy": y}


def task(name, done=0, total=20):
    return m.parse_tasks([block(f"{name}({done}/{total})"), block("去完成", 1080, 1042)], 1264)[0]


class YangYouhuiTests(unittest.TestCase):
    def test_real_rows_pair_button_below_title_and_separate_progress(self):
        rows = [block("看精彩内容30秒", y=1000), block("(1/20)", 700, 1005),
                block("去完成", 1080, 1042), block("+0.1元", y=1080),
                block("搜索宝贝后浏览45秒(0/4)", y=1240), block("去完成", 1080, 1282)]
        parsed = m.parse_tasks(rows, 1264)
        self.assertEqual([(t["name"], t["done"], t["total"], t["cy"]) for t in parsed],
                         [("看精彩内容30秒", 1, 20, 1042), ("搜索宝贝后浏览45秒", 0, 4, 1282)])

    def test_completed_purchase_and_unpaired_rows_are_not_executed(self):
        rows = [block("看直播60秒(20/20)"), block("去完成", 1080, 1042),
                block("下单购买30秒(0/4)", y=1240), block("去完成", 1080, 1282),
                block("浏览30秒后下单(0/4)", y=1700), block("去完成", 1080, 1742),
                block("看精彩内容30秒(0/20)", y=1500)]
        self.assertEqual(m.parse_tasks(rows, 1264), [])

    def test_search_runs_after_all_normal_repetitions(self):
        video = task("看视频30秒", total=2)
        search = task("搜索宝贝后浏览45秒", total=1)
        state = {video["key"]: video, search["key"]: search}
        order = []

        def collect(device, target=None):
            return dict(state[target]) if target else [dict(t) for t in state.values()]

        def execute(device, selected):
            order.append(selected["kind"])
            stored = state[selected["key"]]
            stored["done"] += 1
            if stored["done"] == stored["total"]:
                del state[selected["key"]]

        with patch.object(m, "collect_tasks", side_effect=collect), \
             patch.object(m, "execute_media", side_effect=execute), \
             patch.object(m, "execute_search", side_effect=execute), \
             patch.object(m, "return_to_tasks", return_value=True), patch.object(m.time, "sleep"):
            self.assertTrue(m.run_tasks(Mock()))
        self.assertEqual(order, ["video", "video", "search"])

    def test_no_progress_stops_retry_and_reports_failure(self):
        video = task("看视频30秒")
        with patch.object(m, "collect_tasks", side_effect=lambda d, target=None: video if target else [video]), \
             patch.object(m, "execute_media") as execute, \
             patch.object(m, "return_to_tasks", return_value=True), patch.object(m.time, "sleep"):
            self.assertFalse(m.run_tasks(Mock()))
            execute.assert_called_once()

    def test_limit_does_not_report_pending_tasks_as_complete(self):
        with patch.object(m, "collect_tasks", return_value=[task("看视频30秒")]), \
             patch.object(m, "report_round_finished") as finished:
            self.assertFalse(m.run_tasks(Mock(), max_tasks=0))
            finished.assert_not_called()

    def test_unknown_page_is_not_treated_as_empty_task_list(self):
        with patch.object(m, "open_tasks", return_value=True), \
             patch.object(m, "scroll_tasks"), patch.object(m, "read_page", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "空扫描"):
                m.collect_tasks(Mock())

    def test_modal_heading_without_tasks_is_not_completion(self):
        device = Mock()
        device.window_size.return_value = (1264, 2780)
        with patch.object(m, "open_tasks", return_value=True), patch.object(m, "scroll_tasks"), \
             patch.object(m, "read_page", return_value=[block("做任务 养更大")]):
            with self.assertRaisesRegex(RuntimeError, "空扫描"):
                m.collect_tasks(device)

    def test_home_progress_can_be_split_across_controls(self):
        blocks = [block("滑动浏览", 300), block("30", 500), block("秒", 550),
                  block("+0.1元", 700), block("(2/20)", 900)]
        self.assertEqual(m.home_browse_progress(blocks, 1264), (30, 2, 20))

    def test_page_uses_screen_ocr_instead_of_hidden_webview_coordinates(self):
        import types
        device = Mock()
        visible = [block("做任务 养更大"), block("看视频30秒(0/20)")]
        ocr = Mock(return_value=visible)
        with patch.dict("sys.modules", {"utils": types.SimpleNamespace(get_ocr_text_blocks=ocr)}):
            self.assertEqual(m.read_page(device), visible)
        device.dump_hierarchy.assert_not_called()

    def test_home_browse_requires_progress_increase(self):
        import types
        device = Mock()
        device.window_size.return_value = (1264, 2780)
        page = [block("滑动浏览30秒 +0.1元 (0/20)")]
        browse = Mock()
        with patch.dict("sys.modules", {"u2_scanner": types.SimpleNamespace(execute_browse_task=browse)}), \
             patch.object(m, "read_page", return_value=page):
            self.assertFalse(m.run_home_browse(device))
        browse.assert_called_once()

    def test_search_uses_focused_system_input_and_suggestion_before_browsing(self):
        import types
        browse = Mock()
        device = Mock()
        device.window_size.return_value = (1264, 2780)
        device.app_current.return_value = {"package": m.DT_APP}
        pages = [[block("USB", 200, 390), block("领红包", 1100, 390),
                  block("usb延长线", 200, 550)], [block("滑动浏览45", 1140, 1200)]]
        with patch.dict("sys.modules", {"u2_scanner": types.SimpleNamespace(execute_browse_task=browse)}), \
             patch.object(m, "click_text", return_value=True), patch.object(m, "read_page", side_effect=pages), \
             patch.object(m.time, "sleep"):
            m.execute_search(device, task("搜索宝贝后浏览45秒", total=4))
        device.shell.assert_called_once_with(["input", "text", "USB"])
        device.click.assert_called_once_with(200, 550)
        browse.assert_called_once_with(device, min_duration=45, max_wait=105)

    def test_search_suggestions_without_countdown_are_not_browsed(self):
        import types
        browse = Mock()
        device = Mock()
        device.window_size.return_value = (1264, 2780)
        device.app_current.return_value = {"package": m.DT_APP}
        page = [block("USB", 200, 390), block("领红包", 1100, 390), block("usb延长线", 200, 550)]
        with patch.dict("sys.modules", {"u2_scanner": types.SimpleNamespace(execute_browse_task=browse)}), \
             patch.object(m, "click_text", return_value=True), patch.object(m, "read_page", return_value=page), \
             patch.object(m.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "搜索结果页"):
                m.execute_search(device, task("搜索宝贝后浏览45秒", total=4))
        browse.assert_not_called()

    def test_content_that_lands_in_live_uses_live_and_one_back(self):
        import types
        handlers = types.SimpleNamespace(execute_browse_task=Mock(), execute_live_task=Mock(),
                                         execute_video_task=Mock(), detect_entered_media_type=Mock())
        device = Mock()
        device.app_current.return_value = {"package": m.DT_APP, "activity": ".TaoLiveVideoActivity"}
        with patch.dict("sys.modules", {"u2_scanner": handlers}), patch.object(m.time, "sleep"):
            m.execute_media(device, task("看精美内容30秒"))
        handlers.execute_live_task.assert_called_once()
        handlers.execute_video_task.assert_not_called()
        device.press.assert_called_once_with("back")

    def test_video_return_is_owned_by_shared_executor(self):
        import types
        handlers = types.SimpleNamespace(execute_browse_task=Mock(), execute_live_task=Mock(),
                                         execute_video_task=Mock(), detect_entered_media_type=Mock())
        device = Mock()
        device.app_current.return_value = {"package": m.DT_APP, "activity": "com.taobao.video.VideoListActivity"}
        with patch.dict("sys.modules", {"u2_scanner": handlers}), patch.object(m.time, "sleep"):
            m.execute_media(device, task("看视频30秒"))
        handlers.execute_video_task.assert_called_once()
        device.press.assert_not_called()


if __name__ == "__main__":
    unittest.main()
