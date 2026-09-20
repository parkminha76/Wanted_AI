"""locate.fill_coords가 finding마다 doc.spans 전체를 훑던 O(n²) 문제를 고친다.

실측(2026-09-20, 5만 셀·finding 3만 건짜리 XLSX): rects_for가 finding마다
doc.spans(5만 개)를 처음부터 끝까지 훑어(O(finding 수 × span 수)) 175.90초가
걸렸다. span은 문서를 순서대로 훑으며 만들어져 서로 겹치지 않는다는 성질을
이용해, 시작 위치로 한 번만 정렬하고(_span_index) 이진 탐색으로 겹치는
span만 찾도록 고쳤다.
"""

from __future__ import annotations

import time
import unittest
from dataclasses import dataclass, field

from backend.scanner.parser import locate
from backend.shared.schema import Finding


@dataclass
class _FakeSpan:
    start: int
    end: int
    text: str
    page: int = 0
    bbox: tuple = (0.0, 0.0, 10.0, 10.0)
    char_x: list | None = None


@dataclass
class _FakeDoc:
    spans: list
    page_map: list = field(default_factory=list)


def _finding(start: int, end: int) -> Finding:
    return Finding(
        id=f"f_{start}", type="phone", text="x" * (end - start), start=start, end=end,
        confidence=0.9, source="rule", reason="테스트",
    )


class FillCoordsCorrectnessTest(unittest.TestCase):
    def test_bbox_and_rects_are_filled_for_overlapping_span(self) -> None:
        doc = _FakeDoc(spans=[_FakeSpan(start=0, end=10, text="0123456789")])
        findings = [_finding(2, 5)]

        filled = locate.fill_coords(doc, findings)

        self.assertEqual(filled, 1)
        self.assertIsNotNone(findings[0].bbox)
        self.assertTrue(findings[0].evidence.get("rects"))

    def test_value_split_across_two_lines_gets_both_rects(self) -> None:
        """값 하나가 두 줄(span)에 걸치면 사각형이 둘 필요하다(locate.py 모듈
        docstring 참고) — 같은 줄이 아니므로 _merge가 하나로 합치지 않는다."""
        doc = _FakeDoc(
            spans=[
                _FakeSpan(start=0, end=9, text="010-1234-", bbox=(0.0, 0.0, 9.0, 10.0)),
                _FakeSpan(start=9, end=13, text="5678", bbox=(0.0, 12.0, 4.0, 22.0)),
            ]
        )
        findings = [_finding(0, 13)]

        locate.fill_coords(doc, findings)

        self.assertEqual(len(findings[0].evidence["rects"]), 2)

    def test_non_overlapping_span_is_ignored(self) -> None:
        doc = _FakeDoc(spans=[_FakeSpan(start=100, end=110, text="0123456789")])
        findings = [_finding(0, 5)]

        filled = locate.fill_coords(doc, findings)

        self.assertEqual(filled, 0)
        self.assertIsNone(findings[0].bbox)


class FillCoordsScalingTest(unittest.TestCase):
    def test_time_grows_roughly_linearly_not_quadratically(self) -> None:
        def make_doc_and_findings(n: int) -> tuple[_FakeDoc, list[Finding]]:
            spans = [_FakeSpan(start=i * 10, end=i * 10 + 8, text="x" * 8) for i in range(n)]
            findings = [_finding(i * 10, i * 10 + 8) for i in range(n)]
            return _FakeDoc(spans=spans), findings

        small_doc, small_findings = make_doc_and_findings(500)
        large_doc, large_findings = make_doc_and_findings(4000)  # 8x

        t0 = time.time()
        locate.fill_coords(small_doc, small_findings)
        small_time = time.time() - t0

        t0 = time.time()
        locate.fill_coords(large_doc, large_findings)
        large_time = time.time() - t0

        # 8배 입력에 제곱이면 64배 걸린다. 노이즈가 있는 소규모 벤치라 넉넉히 잡는다.
        self.assertLess(
            large_time,
            max(small_time * 20, 1.0),
            f"small={small_time:.3f}s large={large_time:.3f}s — 다시 제곱 시간대로 보임",
        )


if __name__ == "__main__":
    unittest.main()
