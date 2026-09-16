from __future__ import annotations

import unittest

from backend.shared.schema import Finding, compute_risk_score, risk_level


def finding(risk_type: str, confidence: float = 1.0, index: int = 0) -> Finding:
    return Finding(
        id=f"f_{index:03d}",
        type=risk_type,
        text="value",
        start=index * 10,
        end=index * 10 + 5,
        confidence=confidence,
        source="rule",
        reason="test",
    )


class RiskScoreSaturationTest(unittest.TestCase):
    def test_below_high_threshold_is_unchanged(self) -> None:
        # person(10) x1건 confidence 1.0 -> raw total 10, well under the 60 knee.
        score = compute_risk_score([finding("person")])
        self.assertEqual(score, 10.0)

    def test_scores_above_100_raw_no_longer_collapse_to_the_same_value(self) -> None:
        # injection(50) + api_key(40) + rrn(40) = 130 raw, already over the old hard cap.
        mild = compute_risk_score(
            [finding("injection", index=0), finding("api_key", index=1), finding("rrn", index=2)]
        )
        # Adding more high-weight findings makes the raw total far larger (130 -> ~220+),
        # but under the old min(100, total) both would have shown exactly 100.0.
        severe = compute_risk_score(
            [
                finding("injection", index=0),
                finding("api_key", index=1),
                finding("rrn", index=2),
                finding("db_credential", index=3),
                finding("passport", index=4),
            ]
        )
        self.assertLess(mild, 100.0)
        self.assertLess(severe, 100.0)
        self.assertLess(mild, severe)

    def test_score_never_exceeds_100(self) -> None:
        findings = [finding("injection", index=i) for i in range(50)]
        score = compute_risk_score(findings)
        self.assertLessEqual(score, 100.0)

    def test_high_threshold_boundary_still_maps_to_high_level(self) -> None:
        # A raw total just over 130 should stay well within "high".
        score = compute_risk_score(
            [finding("injection", index=0), finding("api_key", index=1), finding("rrn", index=2)]
        )
        self.assertEqual(risk_level(score), "high")


if __name__ == "__main__":
    unittest.main()
