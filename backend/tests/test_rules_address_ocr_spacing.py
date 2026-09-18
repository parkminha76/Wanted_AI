"""rules.find_addresses가 OCR이 흔히 끼워 넣는 숫자-단위 사이 공백을 견디는지
확인하는 회귀 테스트.

실측 버그(2026-09-17, 실제 지원서 사진): Tesseract가 "101동 101호"를 "101 동
101 호"로, 숫자와 동·층·호 사이에 공백을 끼워 읽었다. 기존 정규식은 공백 없는
형태만 받아서 주소가 도로명·번지까지만 잡히고 동·호수(사람을 특정하는 부분)가
사본에 그대로 남았다.
"""

from __future__ import annotations

import unittest

from backend.scanner.detectors import rules


class FindAddressesOcrSpacingTest(unittest.TestCase):
    def test_dong_and_ho_with_ocr_inserted_space_are_included(self) -> None:
        """실측 재현: "우림필유 101 동 101 호"(OCR이 공백을 끼워 읽은 형태)."""
        text = "안산시 단원구 고잔로 55 우림필유 101 동 101 호"
        matches = rules.find_addresses(text)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], text)

    def test_dong_and_ho_without_space_still_work(self) -> None:
        """공백 없는 원래 형식도 그대로 받아야 한다(회귀 방지)."""
        text = "안산시 단원구 고잔로 55 우림필유 101동 101호"
        matches = rules.find_addresses(text)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], text)

    def test_address_split_across_ocr_line_break_with_spaced_unit(self) -> None:
        """실측 재현: 주소가 줄바꿈으로 갈라지고 둘째 줄에도 공백 낀 단위가 있는 경우."""
        text = "현 주 소\n안산시 단원구 고잔로 55 우림필유 101 동 101 호"
        matches = rules.find_addresses(text)
        self.assertEqual(len(matches), 1)
        self.assertIn("101 동 101 호", matches[0]["value"])

    def test_special_city_suffix_with_ocr_inserted_space_is_included(self) -> None:
        """실측 재현(2026-09-18, 이력서 사진): 위치 핀 아이콘 옆의 "서울특별시"가
        OCR에서 "서"가 통째로 사라지고 "울특 별시"로 읽혔다. "특별시" 음절 사이의
        공백을 견뎌야 적어도 "울특별시"까지는 한 덩어리 주소로 잡힌다 — 공백을 못
        견디면 "~시"로 끝나는 "별시"부터만 매칭돼 "울특"이 그대로 남는다."""
        text = "울특 별시 구로구 구로디지털로 11"
        matches = rules.find_addresses(text)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], text)

    def test_metro_city_suffix_without_ocr_space_still_works(self) -> None:
        """공백 없는 원래 형식도 그대로 받아야 한다(회귀 방지)."""
        text = "서울특별시 강남구 테헤란로 152"
        matches = rules.find_addresses(text)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], text)


if __name__ == "__main__":
    unittest.main()
