"""mask.py의 이미지 마스킹 박스 여백·둥근 모서리(`_padded_image_box`) 순수 테스트.

`Finding` 전체를 만들 필요 없이 `finding.type`만 읽으므로, 최소 속성만 가진
가짜 객체로 충분하다.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.scanner.masking import mask


def _finding(field: str):
    return SimpleNamespace(type=field)


class PaddedImageBoxTest(unittest.TestCase):
    """실측 버그(2026-09-18, 모바일로 노트북 화면을 세로로 세워 찍은 사진):
    회전 복구(`text_ocr.py`)가 되돌린 이름 bbox는 가로 53px·세로 148px처럼
    세로가 훨씬 길다(글자가 세로로 서 있다). 옛 코드는 "세로 축 = 항상 넉넉히"로
    고정해서 148*0.30≈44px가 세로(=읽는 방향)에 붙어, "최태오" 바로 뒤에 이어진
    "의 발자취"까지 뭉텅 가렸다. 어느 축이 짧은 변(줄 두께)인지 상자 자신의
    가로세로 비율로 판단해야 한다."""

    def test_wide_box_pads_generously_on_the_short_vertical_axis(self) -> None:
        """가로로 눕는 보통 문서(가로 > 세로)는 원래 동작과 같아야 한다:
        세로(짧은 변)에 넉넉히, 가로(긴 변=읽는 방향)에 최소한만."""
        box = (100.0, 100.0, 300.0, 140.0)  # width=200, height=40
        (left, top, right, bottom), _radius = mask._padded_image_box(
            _finding("person"), box, width=1000, height=1000
        )
        x_pad = 100.0 - left
        y_pad = 100.0 - top
        self.assertAlmostEqual(x_pad, round(200 * 0.02))       # 긴 변(가로) 기준 최소 여백
        self.assertAlmostEqual(y_pad, round(40 * 0.30))         # 짧은 변(세로) 기준 넉넉한 여백
        self.assertGreater(y_pad, x_pad)

    def test_tall_box_pads_generously_on_the_short_horizontal_axis(self) -> None:
        """실측 재현: 회전 복구된 사진처럼 세로가 훨씬 긴 상자는 반대로 —
        가로(짧은 변)에 넉넉히, 세로(긴 변=읽는 방향)에 최소한만 줘야 옆
        단어를 안 먹는다."""
        box = (1113.0, 1246.0, 1166.0, 1394.0)  # width=53, height=148 (실측 값)
        (left, top, right, bottom), _radius = mask._padded_image_box(
            _finding("person"), box, width=2000, height=1500
        )
        x_pad = 1113.0 - left
        y_pad = 1246.0 - top
        self.assertAlmostEqual(x_pad, round(53 * 0.30))          # 짧은 변(가로) 기준 넉넉한 여백
        self.assertAlmostEqual(y_pad, round(148 * 0.02))          # 긴 변(세로) 기준 최소 여백
        self.assertGreater(x_pad, y_pad)
        # 예전 코드(세로 축 고정 44px)라면 148 + 44*2 = 236이 됐을 세로 길이가,
        # 이제는 148 + 3*2 = 154 정도로 옆 글자를 침범하지 않는다.
        self.assertLess(bottom - top, 160)

    def test_address_still_gets_a_larger_cross_axis_fraction_than_other_fields(self) -> None:
        """주소는 다른 필드보다 짧은 변 쪽 비율이 더 크다(0.55 vs 0.30) — 필드별
        차등은 그대로 유지되는지 확인한다."""
        box = (100.0, 100.0, 400.0, 140.0)  # width=300, height=40 (가로로 눕는 보통 문서)
        (left, top, right, bottom), _radius = mask._padded_image_box(
            _finding("address"), box, width=1000, height=1000
        )
        y_pad = 100.0 - top
        self.assertAlmostEqual(y_pad, round(40 * 0.55))

    def test_id_photo_keeps_the_fixed_minimal_padding(self) -> None:
        """얼굴 사진은 문서 내용을 과도하게 덮지 않도록 고정 2px만 준다 —
        가로세로 비율과 무관하다."""
        box = (10.0, 10.0, 30.0, 200.0)  # 세로로 아주 긴 상자라도
        (left, top, right, bottom), _radius = mask._padded_image_box(
            _finding("id_photo"), box, width=1000, height=1000
        )
        self.assertEqual((left, top, right, bottom), (8.0, 8.0, 32.0, 202.0))

    def test_padded_box_never_exceeds_image_bounds(self) -> None:
        box = (0.0, 0.0, 5.0, 500.0)  # 이미지 경계에 바짝 붙은 좁고 긴 상자
        (left, top, right, bottom), _radius = mask._padded_image_box(
            _finding("person"), box, width=100, height=500
        )
        self.assertGreaterEqual(left, 0.0)
        self.assertGreaterEqual(top, 0.0)
        self.assertLessEqual(right, 100.0)
        self.assertLessEqual(bottom, 500.0)


class BoxRadiusSafetyTest(unittest.TestCase):
    """둥근 모서리 반지름은 그 상자의 여백(x_pad, y_pad)보다 항상 작아야 한다 —
    안 그러면 모서리가 패딩을 넘어 실제 탐지 내용(얼굴·글자) 안쪽까지 파고들어,
    "예쁘게 만들려다 덜 가리는" 사고가 난다."""

    def test_id_photo_radius_stays_within_its_tight_2px_padding(self) -> None:
        """얼굴은 여백이 2px뿐이다 — 반지름이 10px 고정이면 얼굴 가장자리가
        그대로 드러난다. 여백보다 작아야(1px 이하) 안전하다."""
        box = (10.0, 10.0, 200.0, 200.0)
        _box, radius = mask._padded_image_box(
            _finding("id_photo"), box, width=1000, height=1000
        )
        self.assertLessEqual(radius, 1)

    def test_text_field_radius_never_exceeds_its_own_padding(self) -> None:
        """여러 모양의 텍스트 상자에서, 반지름이 실제로 적용된 여백(패딩된
        상자와 원래 상자의 차이)보다 항상 작은지 직접 확인한다."""
        cases = [
            ("person", (0.0, 0.0, 200.0, 40.0)),   # 가로로 눕는 보통 글자
            ("person", (0.0, 0.0, 53.0, 148.0)),   # 세로로 선 글자(회전 복구)
            ("address", (0.0, 0.0, 300.0, 30.0)),  # 주소(짧은 변 비율이 더 큼)
            ("org", (0.0, 0.0, 20.0, 20.0)),       # 아주 작은 정사각형 상자
        ]
        for field, box in cases:
            with self.subTest(field=field, box=box):
                (left, top, right, bottom), radius = mask._padded_image_box(
                    _finding(field), box, width=2000, height=2000
                )
                x_pad = box[0] - left
                y_pad = box[1] - top
                self.assertLessEqual(radius, x_pad)
                self.assertLessEqual(radius, y_pad)

    def test_radius_is_never_negative(self) -> None:
        # 여백이 0이 되는 극단적으로 작은 상자에서도 반지름이 음수로 내려가면
        # 안 된다(Pillow가 음수 반지름을 거부한다).
        box = (0.0, 0.0, 1.0, 1.0)
        _box, radius = mask._padded_image_box(
            _finding("id_photo"), box, width=1000, height=1000
        )
        self.assertGreaterEqual(radius, 0)


if __name__ == "__main__":
    unittest.main()
