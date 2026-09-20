"""누출 검사가 XML 마크업의 글자까지 세지 않는지 본다.

`0` 한 글자가 숨은 텍스트로 탐지되면, 마크업의 `r="A10"`·`s="0"` 때문에 제대로
가려진 사본이 "샌다"로 판정돼 통째로 버려졌다(02_최종점검_정산내역.xlsx 실측).
"""

import os
import tempfile
import unittest
import zipfile

from backend.scanner.masking import mask


def _book(cell_text: str) -> str:
    """sheet XML 한 장짜리 xlsx. 마크업 쪽에 `0`이 일부러 여러 개 들어 있다."""
    path = os.path.join(tempfile.mkdtemp(prefix="leak_test_"), "book.xlsx")
    sheet = (
        '<worksheet><sheetData><row r="10" s="0" ht="20">'
        f'<c r="A10" s="0" t="inlineStr"><is><t>{cell_text}</t></is></c>'
        "</row></sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


class LeakMarkupTest(unittest.TestCase):
    def test_markup_digits_do_not_count_as_leak(self):
        plan = [(0, 1, "[숨은명령]")]
        self.assertFalse(mask._leaks(_book("[숨은명령]"), "0", plan))

    def test_value_left_in_cell_text_still_leaks(self):
        plan = [(0, 1, "[숨은명령]")]
        self.assertTrue(mask._leaks(_book("0"), "0", plan))


if __name__ == "__main__":
    unittest.main()
