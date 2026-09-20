"""실측(2026-09-20, 4,442,184자·2만 5천 줄짜리 로그 파일 — phone·email 6천 건):
_apply_classifier_filters가 분류기가 학습하지 않은 타입(phone·email 등)에도
_sentence_around를 불렀다. _sentence_around는 부를 때마다 원문 전체를 처음부터
다시 문장으로 쪼개며 찾는 값 자리까지 훑는 함수라, 값이 6천 개면 원문 전체를
6천 번 훑는 셈이 됐다(실측 139초). 학습 안 한 타입은 문맥이 버려질 걸 알고
있으므로, _sentence_around를 아예 안 불러야 한다.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.scanner import scan
from backend.shared.schema import Finding


def _finding(field: str, text: str, start: int, end: int) -> Finding:
    return Finding(
        id=f"f_{start}", type=field, text=text, start=start, end=end,
        confidence=0.9, source="rule", reason="테스트",
    )


class SkipSentenceAroundForUntrainedTypesTest(unittest.TestCase):
    def test_phone_and_email_never_call_sentence_around(self) -> None:
        raw_text = "\n".join(
            f"010-{1000+i:04d}-{2000+i:04d} user{i}@example.com" for i in range(50)
        )
        findings = []
        cursor = 0
        for i in range(50):
            phone = f"010-{1000+i:04d}-{2000+i:04d}"
            email = f"user{i}@example.com"
            phone_start = raw_text.index(phone, cursor)
            findings.append(_finding("phone", phone, phone_start, phone_start + len(phone)))
            email_start = raw_text.index(email, phone_start)
            findings.append(_finding("email", email, email_start, email_start + len(email)))
            cursor = email_start + len(email)

        with patch.object(scan, "_sentence_around") as mock_sentence_around, \
             patch.object(scan.models, "false_positive_model_ready", return_value=False):
            kept, filtered_out = scan._apply_classifier_filters(findings, raw_text)

        mock_sentence_around.assert_not_called()
        self.assertEqual(len(kept), 100)
        self.assertEqual(filtered_out, [])

    def test_trained_types_still_get_context(self) -> None:
        """학습된 타입(account 등)은 지금처럼 그대로 문맥을 받아야 한다(회귀 방지)."""
        raw_text = "계좌번호 123-456-789012입니다."
        finding = _finding("account", "123-456-789012", 5, 19)

        with patch.object(scan, "_sentence_around", wraps=scan._sentence_around) as spy, \
             patch.object(scan.models, "false_positive_model_ready", return_value=True), \
             patch.object(scan.models, "filter_false_positive", return_value=(True, 1.0)):
            scan._apply_classifier_filters([finding], raw_text)

        spy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
