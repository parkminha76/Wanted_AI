"""이미지 파일은 신분증 3종만 검사한다(2026-09-20 결정).

스캔본 PDF는 같은 _scan_image를 타지만 file_type이 "pdf"라 이 제한을 받지 않는다 —
문서를 스캔해 올린 경로까지 막으면 핵심 사용 경로가 끊긴다. 그 경계를 여기서 잠근다.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.scanner import scan


def _cnn(field: str, value: str) -> dict:
    return {
        "field": field,
        "value": value,
        "start": 0,
        "end": 0,
        "confidence": 0.9,
        "bbox": (0, 0, 10, 10),
        "page": 1,
    }


class ImageIdCardOnlyTest(unittest.TestCase):
    def test_id_card_image_is_scanned(self) -> None:
        """주민등록번호 영역이 잡히면 신분증이다 — 그대로 검사한다."""
        page = [_cnn("id_photo", "얼굴 사진"), _cnn("rrn", "주민등록번호 영역")]
        with patch.object(scan.id_detector, "detect", return_value=page):
            result = scan._scan_image(
                SimpleNamespace(path="id.png", image_paths=[], file_type="image")
            )

        self.assertIsNone(result.error)
        self.assertFalse(result.unsupported)
        self.assertEqual(len(result.findings), 2)

    def test_ordinary_photo_is_rejected(self) -> None:
        """얼굴만 잡힌 사진은 신분증으로 보지 않는다 — 일반 사진에도 얼굴은 있다."""
        with patch.object(scan.id_detector, "detect", return_value=[_cnn("id_photo", "얼굴 사진")]):
            result = scan._scan_image(
                SimpleNamespace(path="selfie.png", image_paths=[], file_type="image")
            )

        self.assertIsNotNone(result.error)
        self.assertIn("지원하지 않는 이미지", result.error)
        self.assertEqual(result.findings, [])
        # 이 표시가 있어야 화면이 결과로 넘어가지 않고 업로드 화면에 안내를 띄운다.
        self.assertTrue(result.unsupported)
        self.assertTrue(result.to_dict()["unsupported"])

    def test_scanned_pdf_is_not_restricted(self) -> None:
        """스캔본 PDF는 신분증이 아니어도 막지 않는다."""
        with patch.object(scan.id_detector, "detect", return_value=[]):
            result = scan._scan_image(
                SimpleNamespace(path="scan.pdf", image_paths=["p1.png"], file_type="pdf")
            )

        self.assertFalse(result.unsupported)
        self.assertNotIn("지원하지 않는 이미지", result.error or "")

    def test_signature_alone_is_rejected(self) -> None:
        """서명·도장만 잡힌 사진도 신분증 근거로 치지 않는다."""
        with patch.object(scan.id_detector, "detect", return_value=[_cnn("signature", "서명")]):
            result = scan._scan_image(
                SimpleNamespace(path="sign.jpg", image_paths=[], file_type="image")
            )

        self.assertIsNotNone(result.error)
        self.assertIn("지원하지 않는 이미지", result.error)
        self.assertTrue(result.unsupported)


if __name__ == "__main__":
    unittest.main()
