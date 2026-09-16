from __future__ import annotations

import unittest

from backend.shared.schema import Finding, ScanBatch, ScanResult


def finding(risk_type: str, index: int = 0, confidence: float = 1.0) -> Finding:
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


def scan_result(findings: list[Finding]) -> ScanResult:
    return ScanResult(raw_text="text", findings=findings).finalize()


class ScanBatchSummaryTest(unittest.TestCase):
    def test_risk_level_counts_matches_per_file_levels(self) -> None:
        high = scan_result([finding("injection", 0), finding("api_key", 1), finding("rrn", 2)])
        low = scan_result([finding("person", 0)])
        empty = scan_result([])
        batch = ScanBatch(results=[high, low, empty])

        self.assertEqual(high.level, "high")
        self.assertEqual(low.level, "low")
        self.assertEqual(empty.level, "low")
        self.assertEqual(batch.risk_level_counts, {"high": 1, "medium": 0, "low": 2})

    def test_top_risk_types_sums_across_files_and_sorts_descending(self) -> None:
        file_a = scan_result([finding("person", i) for i in range(3)])
        file_b = scan_result([finding("person", i) for i in range(2)] + [finding("account", 5)])
        batch = ScanBatch(results=[file_a, file_b])

        top = batch.top_risk_types()
        self.assertEqual(top[0], {"type": "person", "label": "이름", "count": 5})
        self.assertEqual(top[1], {"type": "account", "label": "계좌번호", "count": 1})

    def test_top_risk_types_respects_limit(self) -> None:
        types = ["person", "phone", "email", "org", "address", "ip"]
        result = scan_result([finding(t, i) for i, t in enumerate(types)])
        batch = ScanBatch(results=[result])
        self.assertEqual(len(batch.top_risk_types(limit=3)), 3)

    def test_to_dict_includes_new_summary_fields(self) -> None:
        batch = ScanBatch(results=[scan_result([finding("person", 0)])])
        d = batch.to_dict()
        self.assertIn("risk_level_counts", d)
        self.assertIn("top_risk_types", d)
        self.assertEqual(d["risk_level_counts"], {"high": 0, "medium": 0, "low": 1})

    def test_empty_batch_has_zeroed_summary(self) -> None:
        batch = ScanBatch(results=[])
        d = batch.to_dict()
        self.assertEqual(d["risk_level_counts"], {"high": 0, "medium": 0, "low": 0})
        self.assertEqual(d["top_risk_types"], [])


if __name__ == "__main__":
    unittest.main()
