"""사용자가 올린 사진이 해상도 상한(스캔본 PDF와 같은 장변 1,400px)을 넘으면
축소본으로 검사하고, 탐지된 픽셀 좌표(bbox)는 원본 해상도 기준으로 되돌리는지
확인한다.

실측(2026-09-20): 스캔본 PDF 페이지는 렌더링할 때부터 1,400px 안에서 굽는데,
사용자가 직접 올리는 사진은 원본 해상도 그대로 CNN/OCR에 들어가 25MP 사진이면
약 380초까지 걸릴 수 있었다(21초/1.4MP 환산). 같은 상한을 적용한다.

마스킹(mask.build_file)은 화질 손실 없이 **원본 파일**을 그대로 칠하므로, 축소본
좌표를 그대로 쓰면 엉뚱한(더 작고 왼쪽 위로 치우친) 자리를 지운다 — 그래서
scan.py가 doc.image_downscale_ratio로 bbox를 되돌리는지가 핵심이다.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from backend.scanner import scan


def _cnn_finding(bbox: tuple) -> dict:
    return {
        "field": "rrn", "value": "900101-1234567", "start": 0, "end": 0,
        "confidence": 0.9, "bbox": bbox, "page": 1,
    }


class ImageDownscaleParseTest(unittest.TestCase):
    def test_oversized_image_is_downscaled_and_ratio_recorded(self) -> None:
        from backend.scanner.parser import parse
        from backend.scanner.parser.parse import _PDF_SCANNED_RENDER_MAX_DIMENSION

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "huge.png")
            Image.new("RGB", (4000, 3000), "white").save(src)

            doc = parse.load(src)

            self.assertEqual(len(doc.image_paths), 1)
            self.assertGreater(doc.image_downscale_ratio, 1.0)
            with Image.open(doc.image_paths[0]) as resized:
                self.assertLessEqual(max(resized.size), _PDF_SCANNED_RENDER_MAX_DIMENSION + 1)

    def test_normal_sized_image_is_not_downscaled(self) -> None:
        from backend.scanner.parser import parse

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "normal.png")
            Image.new("RGB", (800, 600), "white").save(src)

            doc = parse.load(src)

            self.assertEqual(doc.image_paths, [])
            self.assertEqual(doc.image_downscale_ratio, 1.0)


class ImageDownscaleCoordinateRescaleTest(unittest.TestCase):
    def test_bbox_is_scaled_back_to_original_resolution(self) -> None:
        # 축소본에서 (10,10,20,20)을 찾았고, 원본이 축소본의 2배 해상도였다면
        # 원본 기준으로는 (20,20,40,40)이어야 마스킹이 제 자리를 지운다.
        doc = SimpleNamespace(path="huge.png", image_paths=["resized.png"], image_downscale_ratio=2.0)
        with patch.object(scan.id_detector, "detect", return_value=[_cnn_finding((10, 10, 20, 20))]):
            result = scan._scan_image(doc)

        self.assertEqual(result.findings[0].bbox, (20.0, 20.0, 40.0, 40.0))
        self.assertIn("1,400px", result.notice)

    def test_no_rescale_and_no_notice_when_ratio_is_default(self) -> None:
        doc = SimpleNamespace(path="normal.png", image_paths=[], image_downscale_ratio=1.0)
        with patch.object(scan.id_detector, "detect", return_value=[_cnn_finding((10, 10, 20, 20))]):
            result = scan._scan_image(doc)

        self.assertEqual(result.findings[0].bbox, (10, 10, 20, 20))
        self.assertIsNone(result.notice)


if __name__ == "__main__":
    unittest.main()
