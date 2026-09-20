"""스캔본 PDF를 그림으로 구울 때, 원본 페이지가 커도 렌더링 결과가 무한정
커지지 않는지 확인한다.

실측(2026-09-20): 원본 페이지가 1600x2000인 스캔본 PDF를 고정 배율(1.5배)로
구우면 2400x3000(720만 픽셀)까지 커져, OCR이 한 페이지에 112초까지 걸렸다.
페이지가 크면 배율을 줄여 긴 변이 상한(1200px)을 넘지 않게 고쳤다 — A4처럼
흔한 크기는 이 상한에 안 걸려 기존 1.5배 그대로 나와야 한다.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from PIL import Image


class ScannedPdfRenderCapTest(unittest.TestCase):
    def _make_scanned_pdf(self, path: str, width: float, height: float) -> None:
        import pymupdf

        doc = pymupdf.open()
        img_path = path + ".src.png"
        Image.new("RGB", (int(width), int(height)), "white").save(img_path)
        page = doc.new_page(width=width, height=height)
        page.insert_image(page.rect, filename=img_path)
        doc.save(path)
        doc.close()

    def test_a4_sized_page_keeps_the_default_zoom(self) -> None:
        from backend.scanner.parser import parse

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a4.pdf")
            self._make_scanned_pdf(src, 595, 842)  # A4, pt
            doc = parse.load(src)
            self.assertEqual(doc.kind, "image")
            with Image.open(doc.image_paths[0]) as rendered:
                width, height = rendered.size
            # 1.5배 그대로: 595*1.5=892.5, 842*1.5=1263 (반올림 오차 허용)
            self.assertAlmostEqual(width, round(595 * 1.5), delta=2)
            self.assertAlmostEqual(height, round(842 * 1.5), delta=2)

    def test_oversized_page_is_capped_and_stays_under_the_limit(self) -> None:
        from backend.scanner.parser import parse
        from backend.scanner.parser.parse import _PDF_SCANNED_RENDER_MAX_DIMENSION

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "huge.pdf")
            self._make_scanned_pdf(src, 1600, 2000)
            doc = parse.load(src)
            self.assertEqual(doc.kind, "image")
            with Image.open(doc.image_paths[0]) as rendered:
                width, height = rendered.size
            self.assertLessEqual(max(width, height), _PDF_SCANNED_RENDER_MAX_DIMENSION + 1)
            # 그래도 YOLO가 필요로 하는 640px는 넉넉히 넘어야 한다.
            self.assertGreaterEqual(max(width, height), 640)

    def test_multi_page_document_caps_each_page_independently(self) -> None:
        """한 페이지가 크다고 다른(작은) 페이지까지 같이 줄어들면 안 된다."""
        import pymupdf
        from backend.scanner.parser import parse

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "mixed.pdf")
            doc_writer = pymupdf.open()
            for width, height in [(595, 842), (1600, 2000)]:
                img_path = os.path.join(tmp, f"{width}x{height}.png")
                Image.new("RGB", (int(width), int(height)), "white").save(img_path)
                page = doc_writer.new_page(width=width, height=height)
                page.insert_image(page.rect, filename=img_path)
            doc_writer.save(src)
            doc_writer.close()

            doc = parse.load(src)
            self.assertEqual(len(doc.image_paths), 2)
            with Image.open(doc.image_paths[0]) as small_page:
                small_size = small_page.size
            with Image.open(doc.image_paths[1]) as big_page:
                big_size = big_page.size

            # 작은 페이지(A4)는 그대로 1.5배.
            self.assertAlmostEqual(small_size[0], round(595 * 1.5), delta=2)
            # 큰 페이지는 상한 안으로 줄어들어야 한다.
            from backend.scanner.parser.parse import _PDF_SCANNED_RENDER_MAX_DIMENSION
            self.assertLessEqual(max(big_size), _PDF_SCANNED_RENDER_MAX_DIMENSION + 1)


if __name__ == "__main__":
    unittest.main()
