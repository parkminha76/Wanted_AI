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


class SkipChunksWithoutHangulTest(unittest.TestCase):
    """실측(2026-09-20, 4,442,184자·2만 5천 줄짜리 로그 파일): request_id·
    client_ip·phone·email이 반복되는 줄마다 NER 입력이 하나씩 생겨(한글이
    하나도 없는데도) 배치 추론이 3천 번 넘게 돌아 173초가 걸렸다. 한글이
    하나도 없는 조각은 애초에 모델에 보내지 않는다."""

    def test_log_lines_without_hangul_never_reach_the_pipeline(self) -> None:
        pipe = _FakePipeline()
        text = "\n".join(
            f"2026-09-20T00:00:00Z INFO request_id={i:08x} phone=010-{i:04d}-0000"
            for i in range(20)
        )

        with patch.object(ner, "_get_pipeline", return_value=pipe):
            findings = ner.detect(text)

        self.assertEqual(pipe.calls, [])
        self.assertEqual(findings, [])

    def test_a_line_with_any_hangul_still_reaches_the_pipeline(self) -> None:
        pipe = _FakePipeline()
        text = "2026-09-20T00:00:00Z INFO 담당자=홍길동 request_id=00000001"

        with patch.object(ner, "_get_pipeline", return_value=pipe):
            ner.detect(text)

        self.assertEqual(len(pipe.calls), 1)


if __name__ == "__main__":
    unittest.main()
