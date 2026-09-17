"""text_ocr.py 실측 테스트 — 실제로 이미지를 그려서 Tesseract를 돌린다.

목(mock)으로 OCR 결과를 흉내 내면 "OCR이 실제로 이 폰트·레이아웃에서 값을
읽어내는가"라는, 이 모듈이 존재하는 이유 자체를 검증하지 못한다. Tesseract가
설치돼 있지 않은 환경(CI 등)에서는 건너뛴다.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

FONT_PATH = os.path.join("ml", "data_generation", "assets", "fonts", "NanumGothic.otf")

_TESSERACT_CANDIDATES = (r"C:\Program Files\Tesseract-OCR\tesseract.exe",)


def _tesseract_available() -> bool:
    if shutil.which("tesseract"):
        return True
    return any(os.path.isfile(candidate) for candidate in _TESSERACT_CANDIDATES)


@unittest.skipUnless(_tesseract_available(), "Tesseract-OCR이 설치되지 않은 환경")
@unittest.skipUnless(os.path.isfile(FONT_PATH), "테스트용 한글 폰트가 없다")
class TextOcrDetectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PIL import Image, ImageDraw, ImageFont

        cls.tmpdir = tempfile.mkdtemp(prefix="infoguard_ocr_test_")
        cls.image_path = os.path.join(cls.tmpdir, "invoice_like.png")

        # 실제 인보이스 캡처에서 겪은 실패(라벨 줄과 값 줄이 분리돼 계좌번호가
        # 오탐 제거 분류기에 걸러짐)를 그대로 재현하는 레이아웃으로 그린다.
        image = Image.new("RGB", (900, 400), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(FONT_PATH, 28)
        draw.text((40, 40), "받는 분", font=font, fill="black")
        draw.text((40, 90), "김하늘", font=font, fill="black")
        draw.text((40, 140), "010-2847-3915", font=font, fill="black")
        draw.text((40, 220), "입금 계좌", font=font, fill="black")
        draw.text((40, 270), "국민 6127-02-384915", font=font, fill="black")
        image.save(cls.image_path)

        from backend.scanner.detectors import text_ocr

        cls.findings = text_ocr.detect(cls.image_path)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _finding(self, field: str):
        matches = [f for f in self.findings if f["field"] == field]
        self.assertEqual(len(matches), 1, f"{field} 탐지 개수가 1건이 아니다: {matches}")
        return matches[0]

    def test_phone_number_is_found_with_offset_convention_and_bbox(self):
        finding = self._finding("phone")
        # id_detector.py와 같은 관례: 이미지에는 문자 오프셋이 없으니 0으로 둔다.
        self.assertEqual((finding["start"], finding["end"]), (0, 0))
        left, top, right, bottom = finding["bbox"]
        self.assertLess(left, right)
        self.assertLess(top, bottom)
        # 값이 실제로 그려진 자리(세로 140~168px) 근처를 가리켜야 한다.
        self.assertTrue(120 <= top <= 180)

    def test_account_number_survives_false_positive_filter_despite_label_on_previous_line(self):
        """실측 버그: 라벨 줄("입금 계좌")과 값 줄("국민 ...")이 분리되면 오탐 제거
        분류기가 진짜 계좌번호를 주문번호로 착각해 걸러냈다. 두 줄을 이어 붙이는
        보정(_looks_like_label)이 살아있는지 이 테스트로 고정한다."""
        finding = self._finding("account")
        self.assertIn("6127-02-384915", finding["value"])

    def test_findings_carry_true_detector_source_not_a_placeholder(self):
        sources = {f["field"]: f["source"] for f in self.findings}
        self.assertIn(sources["phone"], ("rule", "classifier"))
        self.assertIn(sources["account"], ("rule", "classifier"))


@unittest.skipUnless(_tesseract_available(), "Tesseract-OCR이 설치되지 않은 환경")
@unittest.skipUnless(os.path.isfile(FONT_PATH), "테스트용 한글 폰트가 없다")
class TiltedImageOcrTest(unittest.TestCase):
    """실측 버그: 스캐너와 달리 카메라로 찍은 사진은 몇 도씩 기울어 있는 게 보통인데,
    --psm 6은 글자가 수평이라고 가정해서 8도만 기울어도 계좌번호 줄 전체를 놓쳤다
    (자세한 내용은 text_ocr.py의 _MIN/_MAX_DESKEW_ANGLE 주석 참고)."""

    @classmethod
    def setUpClass(cls) -> None:
        from PIL import Image, ImageDraw, ImageFont

        cls.tmpdir = tempfile.mkdtemp(prefix="infoguard_ocr_tilt_test_")
        cls.image_path = os.path.join(cls.tmpdir, "invoice_tilted.png")

        image = Image.new("RGB", (900, 400), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(FONT_PATH, 28)
        draw.text((40, 40), "받는 분: 김하늘", font=font, fill="black")
        draw.text((40, 100), "연락처: 010-2847-3915", font=font, fill="black")
        draw.text((40, 220), "입금 계좌", font=font, fill="black")
        draw.text((40, 270), "국민 6127-02-384915", font=font, fill="black")
        tilted = image.rotate(-8, expand=True, fillcolor="white")
        tilted.save(cls.image_path)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_tilted_photo_still_finds_phone_and_account(self) -> None:
        from backend.scanner.detectors import text_ocr

        findings = text_ocr.detect(self.image_path)
        by_field = {f["field"]: f for f in findings}

        self.assertIn("phone", by_field)
        self.assertIn("account", by_field)
        self.assertIn("6127-02-384915", by_field["account"]["value"])

    def test_bbox_stays_within_original_tilted_image_bounds(self) -> None:
        """되돌린 좌표계가 아니라 원본(기울어진) 이미지 좌표계를 가리켜야 마스킹이
        실제 글자 위에 그려진다."""
        from PIL import Image

        from backend.scanner.detectors import text_ocr

        with Image.open(self.image_path) as img:
            width, height = img.size

        findings = text_ocr.detect(self.image_path)
        self.assertTrue(findings)
        for finding in findings:
            left, top, right, bottom = finding["bbox"]
            self.assertTrue(0 <= left < right <= width)
            self.assertTrue(0 <= top < bottom <= height)


@unittest.skipUnless(_tesseract_available(), "Tesseract-OCR이 설치되지 않은 환경")
@unittest.skipUnless(os.path.isfile(FONT_PATH), "테스트용 한글 폰트가 없다")
class TableRowGapRecoveryTest(unittest.TestCase):
    """실측 버그(2026-09-17): 아르바이트 지원서 사진에서 표 테두리 선 때문에
    Tesseract가 "성 명 이예지", "생 년 월 일 ..." 줄을 --psm 3/4/6/11/12
    전부에서 통째로 못 읽었다(hOCR로 보면 그 영역을 `ocr_photo`로 오분류).
    표 테두리 선을 그린 합성 이미지로 같은 실패를 재현해, 이미 읽힌 줄
    사이의 빈 구간만 다시 잘라 OCR하는 보정(`_recover_gap_lines`)이 살아있는지
    이 테스트로 고정한다."""

    @classmethod
    def setUpClass(cls) -> None:
        from PIL import Image, ImageDraw, ImageFont

        cls.tmpdir = tempfile.mkdtemp(prefix="infoguard_ocr_table_test_")
        cls.image_path = os.path.join(cls.tmpdir, "application_form.png")

        image = Image.new("RGB", (900, 360), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(FONT_PATH, 28)
        draw.text((40, 20), "아르바이트 지원서", font=font, fill="black")

        draw.rectangle([40, 80, 880, 320], outline="black", width=2)
        draw.line([(40, 200), (700, 200)], fill="black", width=2)
        draw.line([(40, 260), (700, 260)], fill="black", width=2)
        draw.line([(300, 80), (300, 320)], fill="black", width=2)
        draw.line([(700, 80), (700, 320)], fill="black", width=2)

        draw.text((60, 95), "성    명", font=font, fill="black")
        draw.text((320, 95), "이예지", font=font, fill="black")
        draw.text((60, 215), "생 년 월 일", font=font, fill="black")
        draw.text((320, 215), "2000. 11. 12", font=font, fill="black")
        draw.text((60, 275), "연락처", font=font, fill="black")
        draw.text((320, 275), "010-1234-5678", font=font, fill="black")
        image.save(cls.image_path)

        from backend.scanner.detectors import text_ocr

        cls.text, cls.words = text_ocr._ocr_words(cls.image_path)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_table_row_swallowed_by_tesseract_is_recovered(self) -> None:
        compact = self.text.replace(" ", "").replace("\n", "")
        self.assertIn("성명", compact)
        self.assertIn("이예지", compact)
        self.assertIn("생년월일", compact)

    def test_recovered_row_is_wired_into_person_and_birth_date_rules(self) -> None:
        from backend.scanner.detectors import rules

        findings = rules.find_all(self.text)
        self.assertTrue(
            any(f["field"] == "person" and f["value"] == "이예지" for f in findings)
        )
        self.assertTrue(any(f["field"] == "birth_date" for f in findings))


class MergeAdjacentSyllablesTest(unittest.TestCase):
    """실제 인보이스에서 실측한 좌표를 그대로 써서 순수 함수를 결정론적으로 검증한다.

    end-to-end(이미지 → OCR → NER)로는 이 규칙을 안정적으로 재현할 수 없다 —
    Tesseract가 언제 한 단어를 음절 단위로 쪼개는지는 폰트·해상도에 따라 달라져서
    합성 테스트 이미지로는 실제 실패 그대로 재현되지 않았다. 대신 실제로 실패를
    일으켰던 좌표값으로 함수 자체를 고정한다.
    """

    def test_touching_single_syllables_merge_into_one_word(self):
        from backend.scanner.detectors import text_ocr

        # 2026-09-17 실측: 서명란 "정수연"이 이 좌표로 세 단어로 쪼개져 나왔다.
        line = [
            ("정", (192.0, 2142.0, 213.0, 2168.0)),
            ("수", (223.5, 2142.0, 241.0, 2168.0)),
            ("연", (246.5, 2142.0, 265.0, 2168.0)),
        ]
        merged = text_ocr._merge_adjacent_syllables(line)
        self.assertEqual([text for text, _ in merged], ["정수연"])

    def test_far_apart_single_syllables_stay_separate(self):
        from backend.scanner.detectors import text_ocr

        # 같은 줄 번호로 묶였지만 실제로는 다른 열(라벨과 서명)에 있던 두 "정수연".
        line = [
            ("정", (192.0, 2142.0, 213.0, 2168.0)),
            ("수", (223.5, 2142.0, 241.0, 2168.0)),
            ("연", (246.5, 2142.0, 265.0, 2168.0)),
            ("정", (1326.0, 2145.0, 1399.0, 2171.0)),
            ("수", (1358.0, 2142.5, 1376.5, 2178.5)),
            ("연", (1381.0, 2142.5, 1400.5, 2176.5)),
        ]
        merged = text_ocr._merge_adjacent_syllables(line)
        self.assertEqual([text for text, _ in merged], ["정수연", "정수연"])

    def test_multi_char_tokens_are_never_merged(self):
        """"번호" + "01234"처럼 라벨과 값이 붙어 있어도, 한 글자짜리 한글이 아니면 안 합친다."""
        from backend.scanner.detectors import text_ocr

        line = [("번호", (269.0, 672.5, 304.5, 707.0)), ("01234", (302.0, 681.0, 386.0, 701.0))]
        merged = text_ocr._merge_adjacent_syllables(line)
        self.assertEqual([text for text, _ in merged], ["번호", "01234"])


class DropOversizedTest(unittest.TestCase):
    def test_glyphs_much_taller_than_median_body_text_are_dropped(self):
        """실측 버그: 제목("INVOICE", 본문의 3~4배 크기)이 NER에 회사명으로 오탐되어
        마스킹 상자가 머리말 절반을 뒤덮었다. 본문 높이 중앙값보다 훨씬 큰 글자는
        판정 대상에서 아예 빠지는지 확인한다."""
        from backend.scanner.detectors import text_ocr

        entries = [
            ((1, 1, 1), "받는", (0.0, 0.0, 40.0, 26.0), 26.0),
            ((1, 1, 1), "분", (40.0, 0.0, 60.0, 25.0), 25.0),
            ((1, 1, 2), "김하늘", (0.0, 30.0, 74.0, 56.0), 26.0),
            ((1, 1, 3), "INVOICE", (0.0, 60.0, 231.0, 150.0), 90.0),
        ]
        kept = text_ocr._drop_oversized(entries)
        self.assertEqual([text for _, text, _, _ in kept], ["받는", "분", "김하늘"])

    def test_uniformly_sized_document_keeps_every_word(self):
        from backend.scanner.detectors import text_ocr

        entries = [
            ((1, 1, 1), "a", (0.0, 0.0, 10.0, 24.0), 24.0),
            ((1, 1, 1), "b", (10.0, 0.0, 20.0, 26.0), 26.0),
            ((1, 1, 1), "c", (20.0, 0.0, 30.0, 25.0), 25.0),
        ]
        kept = text_ocr._drop_oversized(entries)
        self.assertEqual(len(kept), 3)

    def test_digits_on_a_normal_line_are_not_dropped_as_a_title(self):
        """실측 버그(2026-09-17, 실제 이력서 사진): Tesseract가 매기는 글자 bbox
        높이가 한글 음절과 숫자 글리프에서 다르게 나온다 — 같은 줄인데 "생년월일"은
        9px, 바로 옆 "1996.05.24"는 17px로 잡혔다. 토큰 하나하나를 문서 전체
        중앙값과 비교하면 이 숫자가 "제목"으로 오인되어 생년월일이 통째로
        사라진다. 줄 단위 대표 높이로 비교하면 이 편차가 묻혀야 한다."""
        from backend.scanner.detectors import text_ocr

        entries = [
            ((1, 1, 1), "생명", (0.0, 0.0, 20.0, 9.0), 9.0),
            ((1, 1, 2), "생년월일", (0.0, 20.0, 40.0, 29.0), 9.0),
            ((1, 1, 2), "1996.05.24", (45.0, 20.0, 100.0, 37.0), 17.0),
            ((1, 1, 2), "전", (105.0, 20.0, 115.0, 29.0), 9.0),
            ((1, 1, 2), "화", (115.0, 20.0, 125.0, 37.0), 17.0),
        ]
        kept = text_ocr._drop_oversized(entries)
        self.assertEqual([text for _, text, _, _ in kept], [text for _, text, _, _ in entries])


if __name__ == "__main__":
    unittest.main()
