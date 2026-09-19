"""scan.py가 오탐 제거 분류기에 넘기는 문맥(`_sentence_around`)과, 값 바로 뒤의
명시적 부정문(`_has_explicit_negative_cue`)을 확인한다.

실측(2026-09-19, 실제 샘플 문서 3종을 배포 API와 원본 대조): 두 가지가 확인됐다.

1. 숨은명령.docx — "정산 계좌\\n1401-839-183201"처럼 라벨과 값이 줄바꿈으로만
   나뉘어 있으면, 문장 분리가 줄바꿈마다 끊어서 값 혼자만 "문장"이 된다. 그 빈
   문맥으로 분류기를 부르면 진짜 계좌번호도 오탐(확신도 0.41)으로 걸러진다 —
   라벨을 붙여 주면 0.99로 뒤집힌다.
2. 개발문서.md — "쿠폰번호 4111-1111-1111-1111은 결제 카드번호가 아니다"처럼
   값 뒤에 명시적 부정문이 있는데도, 분류기가 그 부정을 못 읽고 카드번호로
   오판했다(확신도 0.72). "장비 접수번호 123-45-67891은 사업자등록번호가
   아니다"도 마찬가지로 오판했다(확신도 0.79).
"""

from __future__ import annotations

import unittest

from backend.scanner import scan
from backend.shared.schema import Finding


def _finding(risk_type: str, text: str, start: int) -> Finding:
    return Finding(
        id="f_001",
        type=risk_type,
        text=text,
        start=start,
        end=start + len(text),
        confidence=0.3,
        source="rule",
        reason="test",
        evidence={"checksum": "not_available"},
    )


class SentenceAroundTest(unittest.TestCase):
    def test_value_only_line_falls_back_to_the_label_on_the_previous_line(self) -> None:
        """실측 재현: 라벨과 값이 줄바꿈으로만 나뉜 경우, 값 혼자만 "문장"으로
        끊기지 않고 앞 줄의 라벨까지 문맥에 포함돼야 한다."""
        text = "분당구 백현동 532-12\n정산 계좌\n1401-839-183201\n사업자등록번호\n907-96-38082"
        value = "1401-839-183201"
        start = text.find(value)
        context, context_start = scan._sentence_around(text, start, start + len(value))
        self.assertIn("정산 계좌", context)
        self.assertIn(value, context)

    def test_label_and_value_on_the_same_sentence_are_unaffected(self) -> None:
        """회귀 방지: 원래도 한 문장 안에 라벨과 값이 같이 있는 경우(줄바꿈 없음)는
        그대로 그 문장을 써야 한다."""
        text = "계좌번호는 110-2222-3333-44 입니다. 다음 문단입니다."
        value = "110-2222-3333-44"
        start = text.find(value)
        context, _ = scan._sentence_around(text, start, start + len(value))
        self.assertIn("계좌번호는", context)
        self.assertIn("입니다", context)


class ExplicitNegativeCueTest(unittest.TestCase):
    def test_coupon_number_disclaimer_is_recognized(self) -> None:
        text = "- 쿠폰번호 `4111-1111-1111-1111`은 결제 카드번호가 아니다."
        value = "4111-1111-1111-1111"
        start = text.find(value)
        f = _finding("card", value, start)
        self.assertTrue(scan._has_explicit_negative_cue(f, text))

    def test_receipt_number_disclaimer_is_recognized(self) -> None:
        text = "- 장비 접수번호 `123-45-67891`은 사업자등록번호가 아니다."
        value = "123-45-67891"
        start = text.find(value)
        f = _finding("biz_reg", value, start)
        self.assertTrue(scan._has_explicit_negative_cue(f, text))

    def test_value_with_no_trailing_negation_is_not_flagged(self) -> None:
        text = "법인카드 3991-2016-6713-7045로 결제했습니다."
        value = "3991-2016-6713-7045"
        start = text.find(value)
        f = _finding("card", value, start)
        self.assertFalse(scan._has_explicit_negative_cue(f, text))

    def test_filters_the_value_out_end_to_end(self) -> None:
        text = "- 쿠폰번호 `4111-1111-1111-1111`은 결제 카드번호가 아니다."
        value = "4111-1111-1111-1111"
        start = text.find(value)
        f = _finding("card", value, start)
        kept, filtered_out = scan._apply_classifier_filters([f], text)
        self.assertEqual(kept, [])
        self.assertEqual(filtered_out, [f])


if __name__ == "__main__":
    unittest.main()
