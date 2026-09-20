"""rules.find_person_names_after_label 회귀 테스트.

실측 버그(2026-09-17): 이력서·지원서 사진 둘 다 상단 표의 "성명" 값("이수인",
"이예지")이 마스킹 없이 그대로 남았다. 같은 이름이 "지원자 : 이예지 (인)" 같은
자연스러운 문장에서는 NER이 0.8대로 정확히 잡는데, "성 명 이수인 성별 여"처럼
표 라벨과 값이 붙어 있는 한 줄에서는 "이수인"을 "이수"로 잘라 확신도 0.4에
그쳤다(오탐 제거 분류기 단계에서 걸러짐). "성명"이라는 라벨 자체가 이름값이
바로 뒤에 있다는 강한 근거이므로 emp_no와 같은 방식(라벨 옆에 있으면 잡는다)으로
보강했다.
"""

from __future__ import annotations

import unittest

from backend.scanner.detectors import rules


class FindPersonNamesAfterLabelTest(unittest.TestCase):
    def test_table_row_label_is_found(self) -> None:
        """실측 재현: NER이 "이수"로 잘라먹던 표 라벨 형태."""
        matches = rules.find_person_names_after_label("성 명 이수인 성별 여")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["field"], "person")
        self.assertEqual(matches[0]["value"], "이수인")

    def test_colon_form_is_found(self) -> None:
        matches = rules.find_person_names_after_label("성명: 홍길동")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], "홍길동")

    def test_gender_label_is_not_confused_with_name_label(self) -> None:
        self.assertEqual(rules.find_person_names_after_label("성별 남"), [])

    def test_label_glued_to_following_word_is_not_captured(self) -> None:
        """실측 재현: "성명란은"처럼 라벨에 다음 음절이 바로 붙으면 그 음절을
        이름으로 잘못 캡처했다("란은"이 이름으로 잡힘). 공백/구분자가 있어야 한다."""
        self.assertEqual(rules.find_person_names_after_label("신청서 성명란은 자필로 작성"), [])

    def test_tab_separated_header_row_is_not_captured(self) -> None:
        """실측 재현(2026-09-20): XLSX 헤더 행("구분\t성명\t연락처\t이메일")에서
        "성명"은 열 제목일 뿐인데, 탭 하나 건너 다음 열 제목("연락처")을 이름 값으로
        잘못 캡처했다. XLSX 원문은 같은 행의 셀을 탭으로 이어 붙이므로(parse.py),
        탭으로 이어진 다음 칸은 값이 아니라 다른 헤더 라벨일 수 있다."""
        self.assertEqual(
            rules.find_person_names_after_label("구분\t성명\t연락처\t이메일"), []
        )

    def test_wired_into_find_all(self) -> None:
        findings = rules.find_all("성 명 이수인 성별 여")
        self.assertTrue(any(f["field"] == "person" and f["value"] == "이수인" for f in findings))


if __name__ == "__main__":
    unittest.main()
