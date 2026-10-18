"""Verify the shared OCR backend without starting a phone or vision agent."""
import ast
import io
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
import requests
from PIL import Image


def load_cloud_ocr():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "utils.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_cloud_ocr")
    namespace = {
        "_io": io, "Image": Image, "np": np, "cv2": cv2,
        "time": types.SimpleNamespace(time=Mock(return_value=0), sleep=Mock()),
        "OCR_SERVER_URL": "http://ocr.test.local/predict_ocr",
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "utils.py", "exec"), namespace)
    return namespace["_cloud_ocr"], namespace


class CloudOcrBackendTests(unittest.TestCase):
    def setUp(self):
        self.ocr, self.namespace = load_cloud_ocr()
        self.image = Image.new("RGBA", (1264, 2780))
        self.response = Mock()
        self.response.json.return_value = {
            "code": 200,
            "data": [
                {"text": " 元宝中心 ", "score": 0.98, "center": {"x": 1100, "y": 2500}},
                {"text": "误识别", "score": 0.2, "center": {"x": 10, "y": 20}},
                {"text": " ", "score": 0.99},
            ],
        }

    def test_uses_tencent_endpoint_and_original_image_coordinates(self):
        with patch.object(requests, "post", return_value=self.response) as post, patch("subprocess.run") as agent:
            blocks = self.ocr(self.image)
        self.assertEqual(blocks, [{"text": "元宝中心", "cx": 1100, "cy": 2500, "conf": 0.98}])
        agent.assert_not_called()
        args, kwargs = post.call_args
        self.assertEqual(args, (self.namespace["OCR_SERVER_URL"],))
        self.assertEqual(kwargs["timeout"], 45)
        self.assertEqual(kwargs["proxies"], {"http": "", "https": ""})
        image = Image.open(io.BytesIO(kwargs["files"]["image"][1]))
        self.assertEqual(image.size, self.image.size)
        self.assertEqual(image.mode, "RGB")

    def test_retries_request_failure_then_succeeds(self):
        with patch.object(requests, "post", side_effect=[requests.Timeout("timeout"), self.response]) as post:
            self.assertEqual(len(self.ocr(self.image, retries=1)), 1)
        self.assertEqual(post.call_count, 2)
        self.namespace["time"].sleep.assert_called_once_with(2.0)

    def test_service_error_returns_empty_without_agent_fallback(self):
        self.response.json.return_value = {"code": 500, "msg": "inference failed"}
        with patch.object(requests, "post", return_value=self.response) as post, patch("subprocess.run") as agent:
            self.assertEqual(self.ocr(self.image, retries=0), [])
        post.assert_called_once()
        agent.assert_not_called()

    def test_accepts_encoded_image_and_bgr_array(self):
        buf = io.BytesIO()
        self.image.save(buf, format="PNG")
        for image in (buf.getvalue(), np.zeros((20, 30, 3), dtype=np.uint8)):
            with self.subTest(type=type(image)), patch.object(requests, "post", return_value=self.response):
                self.assertEqual(len(self.ocr(image)), 1)


if __name__ == "__main__":
    unittest.main()
