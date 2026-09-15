import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.scanner import scan


def _face(index: int) -> dict:
    return {
        "field": "id_photo",
        "value": "얼굴 사진",
        "start": 0,
        "end": 0,
        "confidence": 0.9,
        "bbox": (index * 20, 0, index * 20 + 10, 10),
        "page": 1,
    }


class ImageQualityGuardTest(unittest.TestCase):
    def test_collage_with_three_faces_is_not_treated_as_safe(self) -> None:
        with patch.object(scan.id_detector, "detect", return_value=[_face(i) for i in range(3)]):
            result = scan._scan_image(SimpleNamespace(path="collage.png", image_paths=[]))

        self.assertEqual(len(result.findings), 3)
        self.assertIsNotNone(result.error)
        self.assertIn("문서 한 장씩", result.error)

    def test_single_document_keeps_normal_image_flow(self) -> None:
        with patch.object(scan.id_detector, "detect", return_value=[_face(0)]):
            result = scan._scan_image(SimpleNamespace(path="id.png", image_paths=[]))

        self.assertEqual(len(result.findings), 1)
        self.assertIsNone(result.error)


if __name__ == "__main__":
    unittest.main()
