from __future__ import annotations

import unittest

from backend.shared.schema import Finding, ScanResult, build_action_guide


def finding(risk_type: str, start: int = 0) -> Finding:
    return Finding(
        id="f_001",
        type=risk_type,
        text="value",
        start=start,
        end=start + 5,
        confidence=1.0,
        source="rule",
        reason="test",
    )


class BuildActionGuideTest(unittest.TestCase):
    def test_no_findings_is_safe_to_share(self) -> None:
        guide = build_action_guide([])
        self.assertEqual(guide["actions"], [])
        self.assertIn("공유", guide["title"])

    def test_injection_produces_top_priority_action(self) -> None:
        guide = build_action_guide([finding("injection")])
        self.assertEqual(guide["actions"][0]["key"], "ai-command")
        self.assertEqual(guide["actions"][0]["tone"], "danger")
        self.assertIn("업로드", guide["actions"][0]["title"])

    def test_caps_actions_at_three_and_deprioritizes_organization(self) -> None:
        # 5개 그룹을 모두 채우면 organization(가장 낮은 우선순위)은 밀려나야 한다.
        findings = [
            finding("injection"),
            finding("api_key"),
            finding("rrn"),
            finding("account"),
            finding("person"),
            finding("biz_reg"),
        ]
        guide = build_action_guide(findings)
        self.assertEqual(len(guide["actions"]), 3)
        keys = {a["key"] for a in guide["actions"]}
        self.assertNotIn("organization", keys)

    def test_checklist_puts_ai_command_before_credential(self) -> None:
        guide = build_action_guide([finding("injection"), finding("api_key")])
        ai_index = next(i for i, item in enumerate(guide["checklist"]) if "AI 서비스" in item)
        credential_index = next(i for i, item in enumerate(guide["checklist"]) if "폐기" in item)
        self.assertLess(ai_index, credential_index)

    def test_scan_result_finalize_sets_action_guide(self) -> None:
        result = ScanResult(raw_text="value", findings=[finding("phone")]).finalize()
        self.assertIsNotNone(result.action_guide)
        self.assertEqual(result.action_guide["actions"][0]["key"], "contact")

    def test_error_result_has_no_action_guide(self) -> None:
        result = ScanResult(raw_text="", error="파일을 읽지 못했습니다").finalize()
        self.assertIsNone(result.action_guide)

    def test_action_guide_survives_to_dict(self) -> None:
        result = ScanResult(raw_text="value", findings=[finding("rrn")]).finalize()
        d = result.to_dict()
        self.assertEqual(d["action_guide"]["actions"][0]["key"], "identity")


if __name__ == "__main__":
    unittest.main()
