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

    def test_impossible_calendar_date_is_rejected(self) -> None:
        self.assertEqual(rules.find_birth_dates("생년월일 1996.13.40"), [])

    def test_wired_into_find_all(self) -> None:
        findings = rules.find_all("생년월일 1996.05.24")
        self.assertTrue(any(f["field"] == "birth_date" for f in findings))


if __name__ == "__main__":
    unittest.main()
