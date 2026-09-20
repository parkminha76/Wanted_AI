"""운전면허증의 면허 종별 글자가 주소로 잡혀 함께 가려지던 것을 막는다.

실측(2026-09-20, 합성 운전면허증 1040x720): 좌상단 "2종보통 2종소형 원동기" 줄이
address 0.080으로 잡혔다. 진짜 주소는 반대편에서 0.943으로 따로 잡혀 있었는데도
둘 다 검게 칠해져서 사본에서 면허 종별을 읽을 수 없었다.

address만 0.05까지 받는 규칙(_CLASS_CONFIDENCE_THRESHOLDS)은 주민등록증 주소가
여러 줄로 쪼개져 뒷줄이 낮게 나오는 것을 살리려는 것이다. 그 뒷줄은 첫 줄 바로
아래에 붙으므로 가로 범위가 겹친다 — 그 성질로 둘을 가른다.
"""

import unittest

from backend.scanner.detectors.id_detector import _drop_stray_low_confidence_addresses


def _addr(confidence: float, bbox: tuple) -> dict:
    return {
        "field": "address",
        "value": "주소 영역",
        "confidence": confidence,
        "bbox": bbox,
        "evidence": {"cnn_class": "address"},
    }


def _other(cnn_class: str, confidence: float = 0.9) -> dict:
    return {
        "field": "rrn",
        "value": cnn_class,
        "confidence": confidence,
        "bbox": (0.0, 0.0, 10.0, 10.0),
        "evidence": {"cnn_class": cnn_class},
    }


class StrayAddressTest(unittest.TestCase):
    def test_license_class_text_far_from_real_address_is_dropped(self) -> None:
        real = _addr(0.943, (402.0, 307.0, 750.0, 383.0))
        stray = _addr(0.080, (18.0, 132.0, 326.0, 157.0))  # 좌상단 "2종보통 원동기"
        kept = _drop_stray_low_confidence_addresses([real, stray, _other("license_number")])

        boxes = [item["bbox"] for item in kept if item["evidence"]["cnn_class"] == "address"]
        self.assertEqual(boxes, [real["bbox"]])

    def test_continuation_line_under_the_address_is_kept(self) -> None:
        """주소 블록과 가로로 겹치는 뒷줄은 이어지는 줄이라 남긴다."""
        first = _addr(0.943, (402.0, 307.0, 750.0, 383.0))
        second = _addr(0.121, (403.0, 351.0, 637.0, 383.0))
        kept = _drop_stray_low_confidence_addresses([first, second])

        self.assertEqual(len(kept), 2)

    def test_all_weak_addresses_are_all_kept(self) -> None:
        """주민등록증처럼 전부 낮게 잡히면 비교 기준이 없으니 예전처럼 전부 남긴다."""
        rows = [
            _addr(0.208, (100.0, 100.0, 400.0, 130.0)),
            _addr(0.062, (100.0, 130.0, 380.0, 160.0)),
            _addr(0.062, (100.0, 160.0, 300.0, 190.0)),
        ]
        self.assertEqual(len(_drop_stray_low_confidence_addresses(rows)), 3)

    def test_non_address_findings_are_untouched(self) -> None:
        items = [_addr(0.943, (10.0, 10.0, 20.0, 20.0)), _addr(0.08, (900.0, 900.0, 910.0, 910.0)),
                 _other("face"), _other("resident_number")]
        kept = _drop_stray_low_confidence_addresses(items)
        classes = [item["evidence"]["cnn_class"] for item in kept]
        self.assertIn("face", classes)
        self.assertIn("resident_number", classes)


if __name__ == "__main__":
    unittest.main()
