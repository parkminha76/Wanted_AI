"""ner._looks_like_person_name 회귀 테스트.

실측(2026-09-20, dummy_pii_test_txt.txt): "성 명"/"주 소"처럼 자간을 벌린 서식
라벨을 NER 모델이 확신도 0.9대로 사람 이름(person)으로 잘못 읽었다. 옛 코드는
"값에 한글이 아닌 문자가 섞여 있으면(공백 포함) 판단하지 않고 통과시킨다"는 규칙을
쓰고 있었는데, 이 규칙의 원래 의도는 외국어 이름(예: "John")을 건드리지 않으려는
것이었지만 한글 사이에 공백만 낀 값도 같이 통과시켜 버렸다. 한글이 하나라도 있으면
공백 없이 전부 한글이어야만 통과시키도록 고쳤다.
"""

from __future__ import annotations

import unittest

from backend.scanner.detectors import ner


class PersonNameShapeTest(unittest.TestCase):
    def test_spaced_label_is_not_a_name(self) -> None:
        self.assertFalse(ner._looks_like_person_name("성 명"))

    def test_spaced_address_label_is_not_a_name(self) -> None:
        self.assertFalse(ner._looks_like_person_name("주 소"))

    def test_real_korean_name_still_passes(self) -> None:
        self.assertTrue(ner._looks_like_person_name("홍길동"))

    def test_foreign_name_is_untouched_by_this_rule(self) -> None:
        """한글이 하나도 없으면 이 규칙으로 판단하지 않고 그대로 통과시킨다."""
        self.assertTrue(ner._looks_like_person_name("John"))

    def test_end_to_end_spaced_labels_are_not_detected_as_person(self) -> None:
        """실측 재현: 신청서 양식에서 "성 명"/"주 소" 라벨 자체는 이름으로 안 잡히고,
        진짜 이름·주소만 각자 맞는 유형으로 잡혀야 한다."""
        text = (
            "성 명: 서은서\n"
            "주 소: 경기도 수원시 영통구 더미길 127, 118동 1888호"
        )
        findings = ner.detect(text)
        values = {f["value"] for f in findings}
        self.assertNotIn("성 명", values)
        self.assertNotIn("주 소", values)
        self.assertIn("서은서", values)


if __name__ == "__main__":
    unittest.main()
