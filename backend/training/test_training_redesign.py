import unittest
from unittest.mock import patch

from backend.training.sanitizer import sanitize_training_text
from backend.training.prompts import build_attacker_prompt
from backend.training.scenarios import SCENARIOS
from backend.training.training_flow import (
    MAX_USER_TURNS,
    create_training_session,
    generate_attacker_message,
    process_user_reply,
)
from backend.training.training_service import (
    calculate_training_score,
    grade_training_score,
)


class TrainingRedesignTests(unittest.TestCase):
    def test_each_level_has_six_unique_scenarios(self):
        self.assertEqual(set(SCENARIOS), {1, 2, 3, 4, 5})
        ids = []
        for scenarios in SCENARIOS.values():
            self.assertEqual(len(scenarios), 6)
            ids.extend(scenario["id"] for scenario in scenarios)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 30)

    def test_training_sanitizer_replaces_only_explicit_formats(self):
        result = sanitize_training_text(
            "홍길동 인포가드 서울 010-1234-5678 test@example.com "
            "110-123-456789 4111-1111-1111-1111 990101-1234567"
        )
        self.assertEqual(
            result["sanitized_text"],
            "홍길동 인포가드 서울 [PHONE] [EMAIL] [ACCOUNT] [CARD] [RRN]",
        )
        self.assertEqual(
            result["shared_fields"],
            ["rrn", "card", "account", "phone", "email"],
        )

    def test_session_keeps_only_sanitized_user_text(self):
        session = create_training_session(1, SCENARIOS[1][0])
        session["history"].append(
            {"role": "assistant", "content": "연락처를 확인할게요."}
        )
        result = process_user_reply(
            session=session,
            user_reply="제 번호는 010-1234-5678입니다.",
        )
        self.assertEqual(result["shared_fields"], ["phone"])
        self.assertEqual(
            session["history"][-1]["content"],
            "제 번호는 [PHONE]입니다.",
        )
        self.assertNotIn("010-1234-5678", repr(session))

    def test_attacker_prompt_hides_internal_privacy_tokens_from_user(self):
        prompt = build_attacker_prompt(
            state="S2_INFO_REQUEST",
            level=1,
            scenario=SCENARIOS[1][0],
        )
        self.assertIn("대괄호 표시를 그대로 출력하지 말고", prompt)
        self.assertIn("휴대전화 번호", prompt)
        self.assertIn("카드 번호", prompt)

    def test_max_turn_finishes_without_calling_attacker(self):
        session = create_training_session(2, SCENARIOS[2][0])
        session["turn_no"] = MAX_USER_TURNS
        result = process_user_reply(session=session, user_reply="확인해 보겠습니다.")
        self.assertTrue(result["is_finished"])
        self.assertEqual(session["state"], "END")
        self.assertEqual(session["status"], "awaiting_report")

        with patch(
            "backend.training.training_flow.AttackerService",
            side_effect=AssertionError("Attacker must not be created"),
        ):
            with self.assertRaisesRegex(ValueError, "종료된 훈련"):
                generate_attacker_message(session)

    def test_backend_calculates_fixed_score_and_grade(self):
        safe = {
            "verified_identity": True,
            "used_official_channel": True,
            "shared_personal_info": False,
            "shared_auth_info": False,
            "accepted_money_request": False,
            "accepted_suspicious_link": False,
            "maintained_verification_under_pressure": True,
        }
        risky = {
            **safe,
            "verified_identity": False,
            "used_official_channel": False,
            "shared_personal_info": True,
            "shared_auth_info": True,
            "accepted_money_request": True,
            "accepted_suspicious_link": True,
            "maintained_verification_under_pressure": False,
        }
        self.assertEqual(calculate_training_score(safe), 100)
        self.assertEqual(grade_training_score(100), "안전")
        self.assertEqual(calculate_training_score(risky), 0)
        self.assertEqual(grade_training_score(0), "위험")

        cautious_refusal = {
            **safe,
            "verified_identity": False,
            "used_official_channel": False,
        }
        self.assertEqual(calculate_training_score(cautious_refusal), 95)
        self.assertEqual(grade_training_score(95), "안전")

        # 신원 확인/공식 채널 재확인/압박 유지 세 항목을 전부 못 했어도, 피해
        # 행동(개인정보·인증정보 공유, 송금·링크 수락)이 0건이면 최소 90점(안전)은
        # 보장되어야 한다 — 절차 미흡이 실질적 무피해보다 더 나쁘게 채점되면 안 된다.
        no_process_but_no_harm = {
            **safe,
            "verified_identity": False,
            "used_official_channel": False,
            "maintained_verification_under_pressure": False,
        }
        self.assertEqual(calculate_training_score(no_process_but_no_harm), 90)
        self.assertEqual(grade_training_score(90), "안전")


if __name__ == "__main__":
    unittest.main()
