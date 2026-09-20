"""스캔본 PDF의 렌더링 쪽수 상한(_PDF_SCANNED_MAX_PAGES)을 확인한다.

실측(2026-09-20, 장변 1400px로 캡한 해상도): 신분증 CNN + OCR을 합쳐 페이지당
약 21초(콜드스타트 제외). 10쪽을 실측하니 211.20초로 비동기 처리의 180초
목표를 넘겼다. 180 / 21 ≈ 8.5쪽이라 8쪽에서 자른다 — 넘는 쪽은 렌더링 자체를
건너뛰어(OCR/CNN 비용도 같이 아낀다) 처리 시간을 붙잡아 둔다.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from PIL import Image


class ScannedPdfPageCapTest(unittest.TestCase):
    def _make_scanned_pdf(self, path: str, n_pages: int) -> None:
        import pymupdf

        doc = pymupdf.open()
        img_path = path + ".src.png"
        Image.new("RGB", (595, 842), "white").save(img_path)
        for _ in range(n_pages):
            page = doc.new_page(width=595, height=842)
            page.insert_image(page.rect, filename=img_path)
        doc.save(path)
        doc.close()

    def test_pages_within_the_cap_are_all_rendered(self) -> None:
        from backend.scanner.parser import parse
        from backend.scanner.parser.parse import _PDF_SCANNED_MAX_PAGES

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "short.pdf")
            self._make_scanned_pdf(src, _PDF_SCANNED_MAX_PAGES)
            doc = parse.load(src)
            self.assertEqual(len(doc.image_paths), _PDF_SCANNED_MAX_PAGES)
            self.assertEqual(doc.skipped_page_count, 0)

    def test_pages_beyond_the_cap_are_not_rendered(self) -> None:
        from backend.scanner.parser import parse
        from backend.scanner.parser.parse import _PDF_SCANNED_MAX_PAGES

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "long.pdf")
            self._make_scanned_pdf(src, _PDF_SCANNED_MAX_PAGES + 5)
            doc = parse.load(src)
            self.assertEqual(len(doc.image_paths), _PDF_SCANNED_MAX_PAGES)
            self.assertEqual(doc.skipped_page_count, 5)

    def test_scan_result_reports_the_skipped_pages_without_hiding_findings(self) -> None:
        """검사 안 한 쪽이 있으면 조용히 "안전"으로 보이면 안 된다 — 안내가 붙어야
        하고, 검사한 쪽의 findings는 그대로 살아 있어야 한다."""
        from unittest.mock import patch

        from backend.scanner import scan
        from backend.scanner.parser import parse
        from backend.scanner.parser.parse import _PDF_SCANNED_MAX_PAGES

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "long.pdf")
            self._make_scanned_pdf(src, _PDF_SCANNED_MAX_PAGES + 2)
            doc = parse.load(src)
            self.assertEqual(doc.skipped_page_count, 2)

            fake_finding = [{"field": "phone", "value": "010-1234-5678", "start": 0, "end": 13, "confidence": 0.9}]
            with patch.object(scan, "id_detector", None), \
                 patch.object(scan, "text_ocr") as fake_ocr:
                fake_ocr.detect.return_value = fake_finding
                result = scan._scan_image(doc)

            self.assertIn(f"{_PDF_SCANNED_MAX_PAGES}쪽까지만 분석", result.notice)
            self.assertIsNone(result.error)  # 검사 자체는 정상 — action_guide를 지우지 않는다
            self.assertTrue(result.findings)


if __name__ == "__main__":
    unittest.main()
