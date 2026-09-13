import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.scanner.detectors import models as detector_models
from ml.training.false_positive_classifier.false_positive_filter import (
    FalsePositiveFilter,
    get_checksum_feature,
)


MODEL_PATH = Path("ml/models/fp_filter_v1.pkl")
METRICS_PATH = Path("ml/eval/false_positive_eval/fp_filter_v1_metrics.json")


class FalsePositiveFilterTest(unittest.TestCase):
    def test_checksum_uses_candidate_span(self):
        text = "사업자등록번호 123-45-67891로 등록했습니다"
        value = "123-45-67891"
        start = text.index(value)
        self.assertEqual(
            get_checksum_feature(text, "biz_reg", start, start + len(value)), 1
        )

    def test_saved_model_loads_and_uses_context(self):
        self.assertTrue(MODEL_PATH.exists(), f"모델이 없습니다: {MODEL_PATH}")
        model = FalsePositiveFilter.load(str(MODEL_PATH))
        value = "123-45-67891"
        positive = f"사업자등록번호 {value}로 세금계산서를 발행합니다"
        negative = f"발주서 번호 {value} 기준으로 처리합니다"

        def probability(text: str) -> float:
            start = text.index(value)
            return model.predict_proba(text, "biz_reg", start, start + len(value))

        self.assertGreater(probability(positive), probability(negative))

    def test_operating_point_limits_false_negative_rate(self):
        model = FalsePositiveFilter.load(str(MODEL_PATH))
        metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        operating_point = metrics["selected"]["operating_point"]

        self.assertAlmostEqual(
            model.operating_threshold, operating_point["threshold"]
        )
        self.assertLessEqual(operating_point["false_negative_rate"], 0.05)

    def test_scanner_uses_model_operating_threshold(self):
        class StubModel:
            risk_types = ["phone"]
            operating_threshold = 0.3

            @staticmethod
            def predict_proba(text, risk_type, start, end):
                return 0.4

        with patch.object(
            detector_models, "_get_false_positive_model", return_value=StubModel()
        ):
            keep, probability = detector_models.filter_false_positive(
                "010-1234-5678", "연락처는 010-1234-5678입니다", "phone"
            )

        self.assertTrue(keep)
        self.assertEqual(probability, 0.4)


if __name__ == "__main__":
    unittest.main()
