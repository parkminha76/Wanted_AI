import unittest

from backend.scanner.detectors import id_detector


def _finding(class_name: str, box=(0, 0, 10, 10)) -> dict:
    return {
        "field": id_detector._CLASS_TO_RISK_TYPE[class_name],
        "bbox": box,
        "evidence": {"cnn_class": class_name},
    }


class IdDetectorPostprocessTest(unittest.TestCase):
    def test_only_address_uses_lower_threshold(self) -> None:
        self.assertEqual(id_detector._class_threshold("address"), 0.05)
        self.assertEqual(id_detector._class_threshold("resident_number"), 0.25)

    def test_passport_removes_impossible_fields_and_upper_page_name(self) -> None:
        findings = [
            _finding("mrz", (0, 700, 500, 740)),
            _finding("face", (10, 150, 150, 380)),
            _finding("face", (30, 500, 170, 690)),
            _finding("name", (490, 130, 530, 160)),
            _finding("name", (200, 520, 260, 540)),
            _finding("address", (200, 220, 470, 250)),
            _finding("resident_number", (200, 200, 470, 230)),
            _finding("license_number", (200, 100, 470, 120)),
        ]

        actual = id_detector._filter_passport_incompatible(findings)
        classes = [item["evidence"]["cnn_class"] for item in actual]

        self.assertEqual(classes.count("name"), 1)
        self.assertNotIn("address", classes)
        self.assertNotIn("resident_number", classes)
        self.assertNotIn("license_number", classes)

    def test_driver_license_adds_missing_secondary_face(self) -> None:
        findings = [
            {**_finding("face"), "confidence": 0.95},
            {**_finding("license_number"), "confidence": 0.90},
            {**_finding("resident_number"), "confidence": 0.85},
            {**_finding("address"), "confidence": 0.80},
        ]

        actual = id_detector._add_license_secondary_face(findings, 600, 400)

        self.assertEqual(len(actual), len(findings) + 1)
        added = actual[-1]
        self.assertEqual(added["field"], "id_photo")
        self.assertEqual(tuple(round(value, 1) for value in added["bbox"]),
                         (486.0, 172.0, 588.0, 316.0))
        self.assertEqual(
            added["evidence"]["layout_rule"], "kr_driver_license_secondary_face"
        )


if __name__ == "__main__":
    unittest.main()
