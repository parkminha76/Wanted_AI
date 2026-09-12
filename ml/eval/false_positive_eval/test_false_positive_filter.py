import unittest
from pathlib import Path

from ml.training.false_positive_classifier.false_positive_filter import (
    FalsePositiveFilter,
    get_checksum_feature,
)


MODEL_PATH = Path("ml/models/fp_filter_v1.pkl")


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


if __name__ == "__main__":
    unittest.main()
