"""이름보다 위쪽에서 낮은 확신도로 잡힌 주소 후보를 버린다.

실측(2026-09-20, 실제 운전면허증 사진): "2종보통 2종소형 원동기"·"특수(대형견인,
소형견인, 구난)" 같은 면허 종별 줄이 각각 0.122·0.183 확신도의 address로 잡혀
마스킹됐다. 이 사진은 진짜 주소 자체가 강한 확신도로 안 잡혀서(기준점이 없어서)
`_drop_stray_low_confidence_addresses`(강한 주소가 있을 때만 동작)가 못 걸렀다.

한국 신분증·면허증 서식에서 주소는 항상 이름보다 아래에 인쇄된다 — 이름이
잡혔을 때만, 그보다 위쪽의 낮은 확신도 주소 후보를 버린다.
"""

import unittest

from backend.scanner.detectors.id_detector import (
    CONFIDENCE_THRESHOLD,
    _drop_low_confidence_addresses_above_name,
)


def _addr(confidence: float, bbox: tuple) -> dict:
    return {
        "field": "address",
        "value": "주소 영역",
        "confidence": confidence,
        "bbox": bbox,
        "evidence": {"cnn_class": "address"},
    }


def _name(bbox: tuple, confidence: float = 0.78) -> dict:
    return {
        "field": "person",
        "value": "이름 영역",
        "confidence": confidence,
        "bbox": bbox,
        "evidence": {"cnn_class": "name"},
    }


class DropAddressAboveNameTest(unittest.TestCase):
    def test_real_photo_stray_addresses_above_name_are_dropped(self) -> None:
        """실측 재현: 2026-09-20 운전면허증 사진의 실제 bbox·확신도 값 그대로."""
        name = _name((296.47, 137.94, 382.46, 158.68))
        stray_vehicle_class = _addr(0.080, (18.0, 88.74, 444.72, 105.32))
        stray_license_header = _addr(0.122, (293.70, 94.44, 665.77, 127.69))
        below_name_candidate = _addr(0.087, (289.81, 221.08, 755.0, 276.81))

        kept = _drop_low_confidence_addresses_above_name(
            [name, stray_vehicle_class, stray_license_header, below_name_candidate]
        )

        addresses = [item for item in kept if item["evidence"]["cnn_class"] == "address"]
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0]["bbox"], below_name_candidate["bbox"])

    def test_strong_confidence_address_above_name_is_kept(self) -> None:
        """확신도가 충분히 높으면(문턱 이상) 이름보다 위에 있어도 손대지 않는다
        — 이 규칙은 "낮은 확신도" 후보만을 위한 안전장치다."""
        name = _name((300.0, 200.0, 380.0, 220.0))
        strong_above = _addr(CONFIDENCE_THRESHOLD, (10.0, 10.0, 400.0, 30.0))
        kept = _drop_low_confidence_addresses_above_name([name, strong_above])
        self.assertEqual(len(kept), 2)

    def test_no_name_found_leaves_findings_untouched(self) -> None:
        """이름 자체가 안 잡힌 문서(예: 이름 없이 주소만 있는 서류)에는 손대지 않는다."""
        stray = _addr(0.08, (18.0, 88.74, 444.72, 105.32))
        kept = _drop_low_confidence_addresses_above_name([stray])
        self.assertEqual(kept, [stray])

    def test_address_below_name_is_kept_regardless_of_confidence(self) -> None:
        name = _name((300.0, 137.0, 380.0, 158.0))
        below = _addr(0.08, (100.0, 200.0, 400.0, 230.0))
        kept = _drop_low_confidence_addresses_above_name([name, below])
        self.assertEqual(kept, [name, below])


if __name__ == "__main__":
    unittest.main()
