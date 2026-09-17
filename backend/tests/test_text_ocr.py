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


@unittest.skipUnless(_tesseract_available(), "Tesseract-OCR이 설치되지 않은 환경")
@unittest.skipUnless(os.path.isfile(FONT_PATH), "테스트용 한글 폰트가 없다")
class TableColumnDetectIntegrationTest(unittest.TestCase):
    """`_find_table_column_cells`가 `detect()` 전체 파이프라인과 실제로 맞물리는지
    합성 이미지로 확인한다(실제 Tesseract 필요). 실측 버그 재현: NER이 표에서
    "회사명" 값 옆 칸 글자를 끝에 붙이거나(경계 오염) 아예 놓치는 경우가 있는데,
    "회사명" 헤더가 있으면 그 열 전체를 확정적으로 잡아야 한다."""

    @classmethod
    def setUpClass(cls) -> None:
        from PIL import Image, ImageDraw, ImageFont

        cls.tmpdir = tempfile.mkdtemp(prefix="infoguard_ocr_table_column_test_")
        cls.image_path = os.path.join(cls.tmpdir, "career_table.png")

        image = Image.new("RGB", (900, 260), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(FONT_PATH, 26)

        draw.rectangle([40, 40, 860, 220], outline="black", width=2)
        draw.line([(40, 100), (860, 100)], fill="black", width=2)
        draw.line([(40, 160), (860, 160)], fill="black", width=2)
        draw.line([(220, 40), (220, 220)], fill="black", width=2)
        draw.line([(560, 40), (560, 220)], fill="black", width=2)

        draw.text((60, 55), "회사명", font=font, fill="black")
        draw.text((240, 55), "기간", font=font, fill="black")
        draw.text((580, 55), "경력", font=font, fill="black")

        draw.text((60, 115), "글로벡스전자", font=font, fill="black")
        draw.text((240, 115), "2020-2021", font=font, fill="black")
        draw.text((580, 115), "기획팀 인턴", font=font, fill="black")

        draw.text((60, 175), "테크노메가", font=font, fill="black")
        draw.text((240, 175), "2022-2023", font=font, fill="black")
        draw.text((580, 175), "UI 디자인", font=font, fill="black")
        image.save(cls.image_path)

        from backend.scanner.detectors import text_ocr

        cls.findings = text_ocr.detect(cls.image_path)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_company_column_values_are_caught_cleanly(self) -> None:
        # OCR이 음절 사이에 공백을 끼워 읽는 경우가 있어(예: "테크노 메가")
        # 공백을 뺀 형태로 비교한다 — 이 테스트가 확인하려는 건 옆 열 글자가
        # 안 섞이는지지, OCR 음절 분리 자체가 아니다.
        org_values = {f["value"].replace(" ", "") for f in self.findings if f["field"] == "org"}
        self.assertTrue(
            any("글로벡스" in v for v in org_values),
            f"회사명 열 값이 안 잡힘: {org_values}",
        )
        self.assertTrue(
            any("테크노메가" in v for v in org_values),
            f"회사명 열 값이 안 잡힘: {org_values}",
        )
        # 옆 열("기간"/"경력")의 글자가 회사명 값에 안 섞여야 한다.
        for value in org_values:
            self.assertNotIn("2020", value)
            self.assertNotIn("2022", value)
            self.assertNotIn("디자인", value)


@unittest.skipUnless(_tesseract_available(), "Tesseract-OCR이 설치되지 않은 환경")
@unittest.skipUnless(os.path.isfile(FONT_PATH), "테스트용 한글 폰트가 없다")
class TableColumnSchoolExclusionIntegrationTest(unittest.TestCase):
    """"학교명" 헤더가 있는 표는 구조화 탐지의 영향을 받지 않아야 한다(학교명
    제외 결정의 end-to-end 고정)."""

    @classmethod
    def setUpClass(cls) -> None:
        from PIL import Image, ImageDraw, ImageFont

        cls.tmpdir = tempfile.mkdtemp(prefix="infoguard_ocr_table_school_test_")
        cls.image_path = os.path.join(cls.tmpdir, "education_table.png")

        image = Image.new("RGB", (900, 200), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(FONT_PATH, 26)

        draw.rectangle([40, 40, 860, 160], outline="black", width=2)
        draw.line([(40, 100), (860, 100)], fill="black", width=2)
        draw.line([(220, 40), (220, 160)], fill="black", width=2)
        draw.line([(560, 40), (560, 160)], fill="black", width=2)

        draw.text((60, 55), "학교명", font=font, fill="black")
        draw.text((240, 55), "기간", font=font, fill="black")
        draw.text((580, 55), "전공", font=font, fill="black")

        draw.text((60, 115), "신안산대학교", font=font, fill="black")
        draw.text((240, 115), "2019-2021", font=font, fill="black")
        draw.text((580, 115), "시각디자인", font=font, fill="black")
        image.save(cls.image_path)

        from backend.scanner.detectors import text_ocr

        cls.findings = text_ocr.detect(cls.image_path)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_no_structured_org_finding_from_school_column(self) -> None:
        structured = [
            f
            for f in self.findings
            if f.get("evidence", {}).get("structured_header")
        ]
        self.assertEqual(structured, [])


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


class TableColumnCellsTest(unittest.TestCase):
    """`_find_table_column_cells`(표 헤더 열 인식) 순수 함수 테스트 — Tesseract 불필요.

    좌표는 실제 이력서 사진(865f267df9c220bf.jpg)의 "경력사항" 표를 OCR해서
    실측한 값을 그대로 썼다("기간 회사명 경력 소속" 헤더 행과 그 아래 두 행).
    """

    HEADER = [
        ("기간", (65.0, 369.5, 81.5, 378.5)),
        ("회사명", (140.5, 369.5, 165.5, 379.0)),
        ("경력", (252.5, 369.5, 268.5, 379.0)),
        ("소속", (357.5, 370.0, 374.0, 379.0)),
    ]
    ROW_FAUGET = [
        ("2024-2025", (48.5, 399.0, 98.0, 407.0)),
        ("Fauget", (139.0, 394.5, 168.0, 411.5)),
        ("웹사이트", (218.5, 399.0, 250.5, 407.5)),
        ("구축", (255.5, 399.0, 271.5, 407.5)),
        ("및", (275.0, 399.0, 282.5, 407.5)),
        ("운영", (286.0, 399.0, 302.0, 408.0)),
        ("디자", (349.0, 398.5, 366.5, 407.5)),
        ("인팀", (375.0, 395.5, 383.5, 412.5)),
    ]
    # 실측 버그 재현: NER이 옆 칸("경력" 열)의 OCR 오독 글자("UI"->"비")를
    # 회사명 개체 끝에 붙여 "Liceria & Co. 비"로 잡았다.
    ROW_LICERIA = [
        ("2022", (49.0, 428.5, 68.5, 436.0)),
        ("-", (72.0, 431.5, 74.5, 433.0)),
        ("2023", (78.0, 428.5, 98.0, 436.0)),
        ("Liceria", (126.5, 428.5, 154.5, 436.5)),
        ("&", (157.5, 428.5, 163.5, 436.0)),
        ("Co.", (166.5, 428.5, 180.0, 436.5)),
        ("비", (242.0, 429.0, 250.5, 436.5)),
        ("디자인", (254.0, 428.0, 278.5, 437.0)),
        ("디자인팀", (349.0, 425.0, 383.5, 442.0)),
    ]

    def test_column_values_are_found_without_bleeding_into_neighbor(self):
        """헤더 4단어 → 중점 계산으로 올바른 열 경계. 옆 열("비")이 회사명
        셀로 안 새고, NER이 아예 놓쳤던 "Fauget"도 같이 잡히는지 확인한다."""
        from backend.scanner.detectors import text_ocr

        lines = [self.HEADER, self.ROW_FAUGET, self.ROW_LICERIA]
        cells = text_ocr._find_table_column_cells(lines)
        values = {c["value"] for c in cells}
        self.assertIn("Fauget", values)
        self.assertIn("Liceria & Co.", values)
        self.assertNotIn("Liceria & Co. 비", values)
        for cell in cells:
            self.assertEqual(cell["field"], "org")
            self.assertEqual(cell["source"], "rule")
            self.assertTrue(cell["evidence"]["structured_header"])

    def test_single_header_word_with_no_neighbor_finds_nothing(self):
        """실측 버그: 표 테두리 선 때문에 Tesseract가 "회사명" 하나만 다른
        헤더들과 분리된 줄로 뽑아내면, 이웃 헤더 없이 경계를 계산해 왼쪽 끝 0
        ~ 오른쪽 끝 무한대인 "열 하나"가 되어 그 아래 모든 행의 글자를
        통째로 삼켜버렸다. 헤더 셀이 2개 미만이면 아무것도 안 잡아야 한다."""
        from backend.scanner.detectors import text_ocr

        lone_header = [("회사명", (140.5, 369.5, 165.5, 379.0))]
        lines = [lone_header, self.ROW_LICERIA]
        cells = text_ocr._find_table_column_cells(lines)
        self.assertEqual(cells, [])

    def test_header_word_split_across_two_tokens_is_still_matched(self):
        """실측 재현: Tesseract가 "회사명"을 "회사"(2글자)+"명"(1글자)로 쪼개면
        `_merge_adjacent_syllables`(한 글자짜리 음절끼리만 다시 붙임)로는
        안 고쳐진다. 단어 하나가 라벨과 똑같은지 보지 않고 줄을 이어붙인
        문자열에서 찾아야 한다."""
        from backend.scanner.detectors import text_ocr

        split_header = [
            ("기간", (65.0, 369.5, 81.5, 378.5)),
            ("회사", (140.5, 369.5, 155.5, 379.0)),
            ("명", (156.0, 369.5, 165.5, 379.0)),
            ("경력", (252.5, 369.5, 268.5, 379.0)),
        ]
        lines = [split_header, self.ROW_LICERIA]
        cells = text_ocr._find_table_column_cells(lines)
        self.assertTrue(any(c["value"] == "Liceria & Co." for c in cells))

    def test_blank_cell_is_skipped_not_an_empty_string_finding(self):
        from backend.scanner.detectors import text_ocr

        row_without_company_name = [
            ("2020", (49.0, 457.5, 68.5, 466.0)),
            ("-", (72.0, 460.5, 74.5, 462.0)),
            ("2021", (78.0, 457.5, 98.0, 466.0)),
            ("프로모션", (218.5, 457.5, 250.5, 466.0)),
            ("디자인", (254.0, 457.5, 278.5, 466.0)),
            ("프리랜서", (349.0, 457.5, 383.5, 466.0)),
        ]
        lines = [self.HEADER, row_without_company_name]
        cells = text_ocr._find_table_column_cells(lines)
        self.assertEqual(cells, [])

    def test_school_header_produces_nothing(self):
        """학교명은 마스킹 대상이 아니다(ner.py의 학교명 제외 결정과 일관) —
        `_COLUMN_FIELD_LABELS`에 "학교명"을 일부러 안 넣었는지 고정한다."""
        from backend.scanner.detectors import text_ocr

        school_header = [
            ("학교명", (65.0, 369.5, 100.0, 378.5)),
            ("기간", (200.0, 369.5, 230.0, 378.5)),
            ("전공", (350.0, 369.5, 380.0, 378.5)),
        ]
        school_row = [
            ("신안산대학교", (65.0, 399.0, 150.0, 407.0)),
            ("2019.03-2021.02", (200.0, 399.0, 280.0, 407.0)),
            ("시각디자인", (350.0, 399.0, 400.0, 407.0)),
        ]
        cells = text_ocr._find_table_column_cells([school_header, school_row])
        self.assertEqual(cells, [])

    def test_row_cap_is_respected(self):
        from backend.scanner.detectors import text_ocr

        rows = []
        for i in range(30):
            y0 = 400.0 + i * 30.0
            rows.append(
                [
                    ("2020", (49.0, y0, 68.5, y0 + 8.0)),
                    (f"Company{i}", (139.0, y0, 180.0, y0 + 8.0)),
                    ("업무", (255.5, y0, 271.5, y0 + 8.0)),
                    ("소속팀", (349.0, y0, 383.5, y0 + 8.0)),
                ]
            )
        cells = text_ocr._find_table_column_cells([self.HEADER, *rows])
        self.assertLessEqual(len(cells), text_ocr._MAX_TABLE_ROWS)

    def test_terminates_on_large_vertical_gap(self):
        from backend.scanner.detectors import text_ocr

        # 두 번째 행이 첫 행과 세로 간격이 훨씬 크다 — 표를 벗어난 것으로 본다.
        far_row = [
            ("2020", (49.0, 900.0, 68.5, 908.0)),
            ("SomeCo", (139.0, 900.0, 180.0, 908.0)),
            ("업무", (255.5, 900.0, 271.5, 908.0)),
            ("소속팀", (349.0, 900.0, 383.5, 908.0)),
        ]
        lines = [self.HEADER, self.ROW_FAUGET, far_row]
        cells = text_ocr._find_table_column_cells(lines)
        values = {c["value"] for c in cells}
        self.assertIn("Fauget", values)
        self.assertNotIn("SomeCo", values)

    def test_terminates_on_unrelated_line_touching_neither_end_column(self):
        """실측 버그: 표 다음에 나온 좌우 두 섹션 제목("자격증" / "수상 및
        기타 능력")이 한 줄로 합쳐져 표와 같은 왼쪽 여백에서 시작해 가로
        범위 대부분과 겹쳐서 표 다음 줄로 잘못 포함됐다. 대상 열이 비어
        있고, 첫 열·마지막 열 둘 다에 걸치지 않으면 멈춰야 한다."""
        from backend.scanner.detectors import text_ocr

        section_titles = [
            ("자격증", (26.5, 516.0, 58.0, 527.5)),
            ("수상", (218.0, 516.0, 239.5, 527.5)),
            ("및", (243.5, 516.0, 253.0, 527.5)),
            ("기타", (257.0, 516.0, 278.0, 527.5)),
            ("능력", (281.5, 516.0, 302.0, 527.5)),
        ]
        lines = [self.HEADER, self.ROW_FAUGET, self.ROW_LICERIA, section_titles]
        cells = text_ocr._find_table_column_cells(lines)
        values = {c["value"] for c in cells}
        self.assertEqual(values, {"Fauget", "Liceria & Co."})


class MergeTableCellsTest(unittest.TestCase):
    def test_overlapping_finding_is_replaced(self):
        from backend.scanner.detectors import text_ocr

        findings = [{"field": "org", "value": "Liceria & Co. 비", "bbox": (126.5, 428.5, 250.5, 436.5)}]
        table_cells = [{"field": "org", "value": "Liceria & Co.", "bbox": (126.5, 428.5, 180.0, 436.5)}]
        merged = text_ocr._merge_table_cells(findings, table_cells)
        self.assertEqual(merged, table_cells)

    def test_non_overlapping_cell_is_appended(self):
        from backend.scanner.detectors import text_ocr

        findings = [{"field": "person", "value": "이수민", "bbox": (0.0, 0.0, 10.0, 10.0)}]
        table_cells = [{"field": "org", "value": "Fauget", "bbox": (139.0, 394.5, 168.0, 411.5)}]
        merged = text_ocr._merge_table_cells(findings, table_cells)
        self.assertEqual(len(merged), 2)
        self.assertIn(findings[0], merged)
        self.assertIn(table_cells[0], merged)

    def test_cell_overlapping_multiple_findings_removes_all(self):
        from backend.scanner.detectors import text_ocr

        findings = [
            {"field": "org", "value": "garbage1", "bbox": (0.0, 0.0, 50.0, 10.0)},
            {"field": "phone", "value": "garbage2", "bbox": (40.0, 0.0, 90.0, 10.0)},
        ]
        table_cells = [{"field": "org", "value": "Real Co.", "bbox": (0.0, 0.0, 90.0, 10.0)}]
        merged = text_ocr._merge_table_cells(findings, table_cells)
        self.assertEqual(merged, table_cells)


if __name__ == "__main__":
    unittest.main()
