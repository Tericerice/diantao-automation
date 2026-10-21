from unittest.mock import Mock

import utils


def test_ocr_click_uses_recognized_text_and_coordinates(monkeypatch):
    device = Mock()
    device.window_size.return_value = (1264, 2780)
    monkeypatch.setattr(utils, "get_ocr_text_blocks", Mock(return_value=[
        {"text": "去 完 成", "cx": 1100, "cy": 1490},
    ]))
    assert utils.has_ocr_text(device, "去完成", exact=True)
    assert utils.click_ocr_text(device, "去完成", exact=True, settle_seconds=0)
    device.click.assert_called_once_with(1100, 1490)


def test_missing_or_out_of_bounds_ocr_target_never_clicks(monkeypatch):
    device = Mock()
    device.window_size.return_value = (1264, 2780)
    blocks = Mock(return_value=[])
    monkeypatch.setattr(utils, "get_ocr_text_blocks", blocks)
    assert not utils.click_ocr_text(device, "去完成", settle_seconds=0, attempts=1)
    blocks.return_value = [{"text": "去完成", "cx": 2000, "cy": 1490}]
    assert not utils.click_ocr_text(device, "去完成", settle_seconds=0)
    device.click.assert_not_called()
