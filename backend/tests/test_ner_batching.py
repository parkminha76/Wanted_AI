import unittest
from unittest.mock import patch

from backend.scanner.detectors import ner


class _FakePipeline:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, texts, batch_size=None):
        self.calls.append((texts, batch_size))
        return [
            [{"entity_group": "PS", "start": 0, "end": 3, "score": 0.99}],
            [{"entity_group": "OG", "start": 0, "end": 10, "score": 0.95}],
        ]


class NerBatchingTest(unittest.TestCase):
    def test_chunks_are_sent_as_one_batch_and_offsets_are_preserved(self) -> None:
        pipe = _FakePipeline()
        text = "홍길동\t블루웨이브 솔루션"

        with patch.object(ner, "_get_pipeline", return_value=pipe):
            findings = ner.detect(text)

        self.assertEqual(len(pipe.calls), 1)
        self.assertEqual(pipe.calls[0], (["홍길동", "블루웨이브 솔루션"], ner._BATCH_SIZE))
        self.assertTrue(
            any(
                item["field"] == "person"
                and item["value"] == "홍길동"
                and (item["start"], item["end"]) == (0, 3)
                for item in findings
            )
        )
        self.assertTrue(
            any(
                item["field"] == "org"
                and item["value"] == "블루웨이브 솔루션"
                and (item["start"], item["end"]) == (4, 14)
                for item in findings
            )
        )


if __name__ == "__main__":
    unittest.main()
