"""rules.find_birth_dates 회귀 테스트.

실측 버그(2026-09-17): 이력서·지원서 사진 두 장 모두 생년월일이 마스킹 없이
그대로 남았다. 원인은 생년월일 탐지기 자체가 없었던 것 — schema.py의 birth_date는
이미지 신분증 CNN 전용이었고, 일반 문서(텍스트·OCR 공통 경로)에는 대응하는
탐지기가 하나도 없었다. rules.py에 단서어(생년월일) 기반 규칙을 추가해 메웠다.
"""

from __future__ import annotations

import unittest

from backend.scanner.detectors import rules


class FindBirthDatesTest(unittest.TestCase):
    def test_labeled_birth_date_is_found(self) -> None:
        matches = rules.find_birth_dates("생년월일 1996.05.24 전화번호 123-456-7890")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["field"], "birth_date")
        self.assertEqual(matches[0]["value"], "1996.05.24")

    def test_spaced_out_form_label_is_found(self) -> None:
        """실측 재현: 지원서 서식의 "생 년 월 일"처럼 라벨 글자 사이를 띄워 쓴 경우."""
        matches = rules.find_birth_dates("생 년 월 일 2000. 11. 12 (만 23세)")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], "2000. 11. 12")

    def test_korean_dotted_date_form_is_found(self) -> None:
        matches = rules.find_birth_dates("생년월일: 2000년 11월 12일")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], "2000년 11월 12일")

    def test_date_without_birth_cue_is_not_flagged(self) -> None:
        """실측 재현: 발급일자·수상일 같은 다른 날짜는 형식이 같아도 단서어가 없으면
        놓쳐야 한다 — 아니면 학력·자격증 표의 모든 날짜가 생년월일로 오탐된다."""
        self.assertEqual(rules.find_birth_dates("발급일자 2021.04.05."), [])
        self.assertEqual(rules.find_birth_dates("2025.12 공인 영어시험 900점"), [])

    def test_blood_type_after_date_is_found_without_a_label(self) -> None:
        """실측 재현(2026-09-18): 캔바류 이력서 템플릿은 "생년월일" 글자 대신 사람
        아이콘을 라벨로 쓴다. OCR은 아이콘을 못 읽으므로 앞쪽 단서어가 없는데, 이런
        템플릿은 거의 항상 날짜 뒤에 혈액형을 붙인다("1993.01.14 | B형") — 그 혈액형을
        뒤쪽 단서어로 받아야 한다."""
        matches = rules.find_birth_dates("최태오는요 1993.01.14 | B형")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], "1993.01.14")

    def test_blood_type_after_date_is_found_without_a_pipe(self) -> None:
        """실측 재현(2026-09-18): OCR 엔진을 EasyOCR로 바꾼 뒤 확인 — "|" 처럼
        가느다란 구분 기호는 EasyOCR이 글자로 아예 검출하지 못해 "1993.01.14 B형"
        처럼 구분자 없이 공백만 남는다. "|" 없이도 혈액형 단서로 잡아야 한다."""
        matches = rules.find_birth_dates("최태오는요 1993.01.14 B형")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], "1993.01.14")

    def test_date_with_unrelated_text_after_it_is_still_not_flagged(self) -> None:
        """"A"로 시작하는 아무 글자나 걸리면 안 된다 — "동"처럼 "형"이 아닌 글자로
        끝나면 여전히 안 걸려야 한다."""
        self.assertEqual(rules.find_birth_dates("발급일 2020.05.01 A동 101호"), [])

    def test_misread_blood_type_letter_is_still_found(self) -> None:
        """실측 재현(2026-09-18): 실제 이력서 사진에서 혈액형의 "B"가 OCR로
        "『"(따옴표 글리프)로 오인식돼 "1993.01.14 | 『 형"이 됐다. 글자 자체는
        틀려도 한두 글자 + "형"이라는 구조는 살아있으니 그걸로 잡아야 한다."""
        matches = rules.find_birth_dates("최태오는요 1993.01.14 | 『 형")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["value"], "1993.01.14")

    def test_word_ending_in_hyeong_three_syllables_after_date_is_not_flagged(self) -> None:
        """"형" 앞에 두 글자를 넘는 단어("직사각형" = 형 앞 세 글자)는 날짜 바로
        뒤에 붙어 있어도 걸리면 안 된다 — 길이 제한이 이런 무관한 단어를 걸러내는
        유일한 방어선이라 직접 인접시켜 확인한다."""
        self.assertEqual(rules.find_birth_dates("2020.01.01 직사각형 넓이 계산"), [])

    def test_impossible_calendar_date_is_rejected(self) -> None:
        self.assertEqual(rules.find_birth_dates("생년월일 1996.13.40"), [])

    def test_wired_into_find_all(self) -> None:
        findings = rules.find_all("생년월일 1996.05.24")
        self.assertTrue(any(f["field"] == "birth_date" for f in findings))


if __name__ == "__main__":
    unittest.main()
