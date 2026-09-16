import unittest
from types import SimpleNamespace

from backend.scanner.scan import _xlsx_ner_input
from backend.shared.schema import Finding


class XlsxNerInputTest(unittest.TestCase):
    def test_confirmed_and_non_korean_cells_are_blank_but_offsets_stay_fixed(self) -> None:
        text = "홍길동\t010-1234-5678\t검토 메모"
        spans = [
            SimpleNamespace(text="홍길동", start=0, end=3),
            SimpleNamespace(text="010-1234-5678", start=4, end=17),
            SimpleNamespace(text="검토 메모", start=18, end=23),
        ]
        findings = [
            Finding(
                id="",
                type="person",
                text="홍길동",
                start=0,
                end=3,
                confidence=0.98,
                source="rule",
                reason="구조화 열",
            )
        ]

        actual = _xlsx_ner_input(text, spans, findings)

        self.assertEqual(len(actual), len(text))
        self.assertEqual(actual[3], "\t")
        self.assertEqual(actual[17], "\t")
        self.assertEqual(actual[18:23], "검토 메모")
        self.assertTrue(actual[:3].isspace())
        self.assertTrue(actual[4:17].isspace())


if __name__ == "__main__":
    unittest.main()
