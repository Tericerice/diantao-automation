from tools.ocr_compat_contract import normalize_paddle_result


def test_normalizes_paddle_result_into_legacy_blocks() -> None:
    result = {
        "res": {
            "rec_texts": ["商品标题", "第二行"],
            "rec_scores": [0.98, 0.75],
            "rec_boxes": [[10, 20, 110, 60], [4, 80, 44, 100]],
        }
    }

    blocks = normalize_paddle_result(result)

    assert [(block.text, block.score) for block in blocks] == [
        ("商品标题", 0.98),
        ("第二行", 0.75),
    ]
    assert (blocks[0].center.x, blocks[0].center.y) == (60, 40)
    assert (blocks[1].center.x, blocks[1].center.y) == (24, 90)


def test_uses_polygons_when_rec_boxes_are_missing() -> None:
    result = {
        "res": {
            "rec_texts": ["旋转文字"],
            "rec_scores": [0.91],
            "dt_polys": [[[10, 10], [30, 8], [34, 28], [12, 30]]],
        }
    }

    blocks = normalize_paddle_result(result)

    assert len(blocks) == 1
    assert (blocks[0].center.x, blocks[0].center.y) == (22, 19)


def test_skips_malformed_rows_without_crashing() -> None:
    result = {
        "res": {
            "rec_texts": ["有效", 123, ""],
            "rec_scores": [0.8],
            "rec_boxes": [[0, 0, 20, 20], [1, 1]],
        }
    }

    blocks = normalize_paddle_result(result)

    assert len(blocks) == 1
    assert blocks[0].text == "有效"
