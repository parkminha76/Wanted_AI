"""주소 박스가 글자 끝까지 못 미쳐 주소가 새던 것을 막는다.

실측(2026-09-20, 합성 운전면허증 1040x720): 주소는 x=900 근처까지 인쇄돼 있는데
박스가 x=750에서 끊겨 사본에서 "통일로 97"이 그대로 읽혔다. 같은 카드의 다른 글자
필드(면허번호 끝선 913)를 기준으로 늘려 덮는다.
"""

import unittest

from backend.scanner.detectors.id_detector import _widen_address_to_text_extent


def _item(cnn_class: str, bbox: tuple, confidence: float = 0.9) -> dict:
    return {
        "field": cnn_class,
        "value": cnn_class,
        "confidence": confidence,
        "bbox": bbox,
        "evidence": {"cnn_class": cnn_class},
    }


def _address_of(findings: list[dict]) -> tuple:
    return next(f["bbox"] for f in findings if f["evidence"]["cnn_class"] == "address")


class AddressExtentTest(unittest.TestCase):
    def test_horizontal_card_extends_right_to_widest_text_field(self) -> None:
        out = _widen_address_to_text_extent([
            _item("license_number", (397.0, 129.0, 913.0, 175.0)),
            _item("resident_number", (401.0, 246.0, 731.0, 286.0)),
            _item("address", (402.0, 307.0, 750.0, 383.0)),
        ])
        self.assertEqual(_address_of(out), (402.0, 307.0, 913.0, 383.0))

    def test_reference_shorter_than_address_changes_nothing(self) -> None:
        out = _widen_address_to_text_extent([
            _item("resident_number", (400.0, 200.0, 500.0, 230.0)),
            _item("address", (400.0, 300.0, 800.0, 380.0)),
        ])
        self.assertEqual(_address_of(out), (400.0, 300.0, 800.0, 380.0))

    def test_rotated_card_extends_downward_not_sideways(self) -> None:
        """세로로 누운 신분증은 글자가 아래로 흐르므로 아래쪽 끝을 늘린다."""
        out = _widen_address_to_text_extent([
            _item("resident_number", (207.0, 79.0, 227.0, 340.0)),
            # 세로로 긴 박스. 높이 171이라 상한(+171)에 걸리지 않고 기준선까지 닿는다.
            _item("address", (154.0, 79.0, 168.0, 250.0)),
        ])
        self.assertEqual(_address_of(out), (154.0, 79.0, 168.0, 340.0))

    def test_runaway_extension_is_capped_at_own_length(self) -> None:
        """기준이 엉뚱하게 멀면 원래 길이만큼까지만 늘려 카드 절반을 칠하지 않는다."""
        out = _widen_address_to_text_extent([
            _item("license_number", (0.0, 0.0, 5000.0, 10.0)),
            _item("address", (100.0, 300.0, 200.0, 340.0)),  # 폭 100
        ])
        self.assertEqual(_address_of(out), (100.0, 300.0, 300.0, 340.0))  # 100 + 100

    def test_no_reference_field_changes_nothing(self) -> None:
        out = _widen_address_to_text_extent([
            _item("face", (0.0, 0.0, 10.0, 10.0)),
            _item("address", (400.0, 300.0, 500.0, 340.0)),
        ])
        self.assertEqual(_address_of(out), (400.0, 300.0, 500.0, 340.0))


if __name__ == "__main__":
    unittest.main()
