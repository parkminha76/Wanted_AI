"""text_ocr.py 실측 테스트 — 실제로 이미지를 그려서 EasyOCR를 돌린다.

목(mock)으로 OCR 결과를 흉내 내면 "OCR이 실제로 이 폰트·레이아웃에서 값을
읽어내는가"라는, 이 모듈이 존재하는 이유 자체를 검증하지 못한다. EasyOCR
모델을 못 불러오는 환경(CI 등)에서는 건너뛴다.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

FONT_PATH = os.path.join("ml", "data_generation", "assets", "fonts", "NanumGothic.otf")


def _easyocr_available() -> bool:
    try:
        import easyocr  # noqa: F401
    except Exception:      # noqa: BLE001 — 모델 로드 실패까지 포함해 전부 "불가"로 본다
        return False
    return True


@unittest.skipUnless(_easyocr_available(), "EasyOCR을 불러올 수 없는 환경")
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


@unittest.skipUnless(_easyocr_available(), "EasyOCR을 불러올 수 없는 환경")
@unittest.skipUnless(os.path.isfile(FONT_PATH), "테스트용 한글 폰트가 없다")
class TiltedImageOcrTest(unittest.TestCase):
    """실측 버그: 스캐너와 달리 카메라로 찍은 사진은 몇 도씩 기울어 있는 게 보통이다.
    예전 Tesseract 엔진(--psm 6)은 글자가 수평이라고 가정해서 8도만 기울어도
    계좌번호 줄 전체를 놓쳤고, 그래서 OCR 전에 각도를 되돌리는 보정이 따로
    있었다. EasyOCR의 검출기는 회전에 강해 그 보정 없이도 바로 읽는다 —
    이 테스트는 그 사실 자체를 고정한다."""

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


@unittest.skipUnless(_easyocr_available(), "EasyOCR을 불러올 수 없는 환경")
@unittest.skipUnless(os.path.isfile(FONT_PATH), "테스트용 한글 폰트가 없다")
class TableRowGapRecoveryTest(unittest.TestCase):
    """표 테두리 선이 있는 서식에서도 셀 안 글자(성명·생년월일 등)를 제대로
    읽고 person/birth_date 판정까지 이어지는지 확인한다. 예전 Tesseract
    엔진에서는 표 테두리 선 때문에 이 줄들이 통째로 안 읽히는 문제가 있었는데
    (`ocr_photo`로 오분류), EasyOCR은 이런 보정 없이도 바로 읽는다."""

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
        draw.text((320, 215), "2000. 05. 24", font=font, fill="black")
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


@unittest.skipUnless(_easyocr_available(), "EasyOCR을 불러올 수 없는 환경")
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

        draw.text((60, 115), "한빛전자", font=font, fill="black")
        draw.text((240, 115), "2020-2021", font=font, fill="black")
        draw.text((580, 115), "기획팀 인턴", font=font, fill="black")

        draw.text((60, 175), "대한소프트", font=font, fill="black")
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
            any("한빛전자" in v for v in org_values),
            f"회사명 열 값이 안 잡힘: {org_values}",
        )
        self.assertTrue(
            any("대한소프트" in v for v in org_values),
            f"회사명 열 값이 안 잡힘: {org_values}",
        )
        # 옆 열("기간"/"경력")의 글자가 회사명 값에 안 섞여야 한다.
        for value in org_values:
            self.assertNotIn("2020", value)
            self.assertNotIn("2022", value)
            self.assertNotIn("디자인", value)


@unittest.skipUnless(_easyocr_available(), "EasyOCR을 불러올 수 없는 환경")
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


class DropOversizedTest(unittest.TestCase):
    def test_glyphs_much_taller_than_median_body_text_are_flagged(self):
        """실측 버그: 제목("INVOICE", 본문의 3~4배 크기)이 NER에 회사명으로 오탐되어
        마스킹 상자가 머리말 절반을 뒤덮었다. 본문 높이 중앙값보다 훨씬 큰 줄이
        오버사이즈로 표시되는지 확인한다.

        줄은 버리지 않는다 — 이름을 큰 히어로 타이틀로 박아넣는 이력서
        디자인에서는 그러면 이름 자체가 raw_text에서 사라져 NER이 볼 기회조차
        없어졌다(실측). 대신 오버사이즈 표시만 돌려주고, `detect()`가 org
        판정에만 그 표시를 적용한다."""
        from backend.scanner.detectors import text_ocr

        rows = [
            [("받는 분", (0.0, 0.0, 60.0, 26.0))],
            [("김하늘", (0.0, 30.0, 74.0, 56.0))],
            [("INVOICE", (0.0, 60.0, 231.0, 150.0))],
        ]
        flags = text_ocr._oversized_row_flags(rows)
        self.assertEqual(flags, [False, False, True])

    def test_uniformly_sized_document_flags_nothing(self):
        from backend.scanner.detectors import text_ocr

        rows = [
            [("a", (0.0, 0.0, 10.0, 24.0))],
            [("b", (10.0, 0.0, 20.0, 26.0))],
            [("c", (20.0, 0.0, 30.0, 25.0))],
        ]
        self.assertEqual(text_ocr._oversized_row_flags(rows), [False, False, False])

    def test_oversized_line_org_finding_is_suppressed_but_person_is_not(self):
        """`detect()` 통합 테스트: 제목 크기 회사명(INVOICE류)은 여전히 걸러지지만,
        제목 크기로 인쇄된 사람 이름(이력서 히어로 타이틀)은 이제 잡힌다."""
        from unittest.mock import patch

        from backend.scanner import scan
        from backend.scanner.detectors import text_ocr
        from backend.shared.schema import Finding

        lines = [
            [("최민준", (10.0, 0.0, 200.0, 90.0))],  # 오버사이즈로 표시될 줄
            [("연락처", (10.0, 120.0, 80.0, 146.0)), ("010-1234-5678", (90.0, 120.0, 220.0, 146.0))],
        ]
        oversized_flags = [True, False]

        def fake_scan_text(text, meta=None):
            person_start = text.index("최민준")
            phone_start = text.index("010-1234-5678")
            return scan.ScanResult(
                raw_text=text,
                findings=[
                    Finding(
                        id="f_1",
                        type="person",
                        text="최민준",
                        start=person_start,
                        end=person_start + len("최민준"),
                        confidence=0.9,
                        reason="test",
                        source="ner",
                        evidence={},
                    ),
                    Finding(
                        id="f_2",
                        type="phone",
                        text="010-1234-5678",
                        start=phone_start,
                        end=phone_start + len("010-1234-5678"),
                        confidence=0.9,
                        reason="test",
                        source="rule",
                        evidence={},
                    ),
                ],
            )

        with patch.object(text_ocr, "_ocr_lines", return_value=(lines, oversized_flags)), \
             patch.object(scan, "scan_text", side_effect=fake_scan_text):
            findings = text_ocr.detect("fake.png")

        types = {f["field"] for f in findings}
        self.assertIn("person", types)
        self.assertIn("phone", types)


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

    def test_blank_cell_in_a_real_table_row_is_defensively_masked_without_a_value(self):
        """실측 버그(2026-09-17): "A식품"처럼 영문 한 글자와 한글이 공백 없이
        붙은 토큰을 Tesseract가 psm·배율·언어 조합을 다 바꿔도 못 읽었다.
        그래도 이 행이 첫 열·마지막 열 둘 다에 값이 있는 진짜 표 행이면,
        회사명 칸에 뭔가 있어야 한다는 것 자체는 표 구조로 알 수 있다.
        값은 모른 채로 자리만 방어적으로 가려야 한다(id_detector.py가 얼굴
        영역을 값 없이 좌표만으로 가리는 것과 같은 방식) — 조용히 건너뛰면
        안 된다."""
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
        self.assertEqual(len(cells), 1)
        cell = cells[0]
        self.assertEqual(cell["field"], "org")
        self.assertEqual(cell["value"], "회사명 미확인 값")
        self.assertLess(cell["confidence"], 0.98, "실제로 읽은 값보다는 신뢰도가 낮아야 한다")
        self.assertTrue(cell["evidence"]["unread"])

    def test_blank_cell_outside_the_table_produces_nothing(self):
        """대상 열도 비어 있고 첫 열·마지막 열 둘 다 안 걸치면(표를 벗어난 줄) —
        방어적으로 가릴 근거 자체가 없으므로 아무것도 안 잡아야 한다."""
        from backend.scanner.detectors import text_ocr

        unrelated_line = [("전혀", (400.0, 457.5, 420.0, 466.0)), ("관계없음", (424.0, 457.5, 460.0, 466.0))]
        lines = [self.HEADER, unrelated_line]
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

    def test_first_column_does_not_reach_across_into_a_separate_label_cell(self):
        """실측 버그(2026-09-17, 지원서 사진): "직장명" 열 왼쪽에 세로 선으로
        나뉜 별도 병합 셀(여러 행에 걸친 행 그룹 라벨 "아르바이트\n경력사항")이
        있었는데, 첫 열의 왼쪽 끝이 무조건 0(이미지 왼쪽 끝)이라 그 라벨
        글자가 회사명 값으로 잘못 잡혀 라벨 자체가 마스킹으로 가려졌다.
        좌표는 그 표를 그대로 실측한 값이다 — 이 표는 "직장명"이 첫 열이라
        열 자신의 폭만큼만 바깥으로 열어 두는 보정이 실제로 걸리는지 본다."""
        from backend.scanner.detectors import text_ocr

        header = [
            ("직장명", (392.5, 755.0, 451.5, 777.0)),
            ("기간", (663.0, 755.0, 702.5, 776.0)),
            ("주요", (941.5, 741.0, 1024.0, 786.0)),
            ("업무", (984.0, 755.0, 1024.0, 776.5)),
        ]
        # "아르바이트"는 실제로는 "직장명" 열이 아니라 그 왼쪽의 별도 병합
        # 셀(행 그룹 라벨)에 있는 글자다 — 이 표에서 OCR은 "A식품"(진짜
        # 첫 행 값)을 아예 못 읽었다.
        row_with_label_bleed_only = [
            ("아르바이트", (176.5, 803.0, 280.0, 824.0)),
            ("2021", (526.0, 800.0, 598.0, 821.0)),
            ("년", (584.5, 786.0, 602.5, 843.0)),
        ]
        cells = text_ocr._find_table_column_cells([header, row_with_label_bleed_only])
        self.assertEqual(cells, [])


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


class NormalizeDigitConfusableLettersTest(unittest.TestCase):
    """실측 재현(2026-09-18): 실제 이력서 사진에서 전화번호 "010-000-0000"의
    "0"이 EasyOCR로 "O"(영문자)로 읽혀 "010-000-0OOO"가 됐다. 전화번호
    정규식은 순수 숫자만 받으므로 이 값을 통째로 놓쳤다."""

    def test_letter_o_inside_digit_run_is_restored_to_zero(self):
        from backend.scanner.detectors import text_ocr

        self.assertEqual(
            text_ocr._normalize_digit_confusable_letters("전화 010-000-0OOO 문의"),
            "전화 010-000-0000 문의",
        )

    def test_length_is_unchanged_so_offsets_stay_valid(self):
        """한 글자를 한 글자로만 바꿔야 한다 — 길이가 바뀌면 이미 만들어 둔
        `_Word.start/end` 오프셋이 어긋난다."""
        from backend.scanner.detectors import text_ocr

        original = "전화 010-000-0OOO 문의"
        normalized = text_ocr._normalize_digit_confusable_letters(original)
        self.assertEqual(len(original), len(normalized))

    def test_letters_far_from_any_digit_are_untouched(self):
        """숫자가 하나도 안 섞인 "O"는 영문 단어의 일부일 수 있다 — 건드리면 안 된다."""
        from backend.scanner.detectors import text_ocr

        self.assertEqual(
            text_ocr._normalize_digit_confusable_letters("iOS 앱 개발, TOEIC 900점"),
            "iOS 앱 개발, TOEIC 900점",
        )


class RowIsSingleClusterTest(unittest.TestCase):
    """실측 재현(2026-09-18): 2단 이력서 레이아웃에서 왼쪽 "개인정보"와 오른쪽
    "학력사항"이 같은 세로 위치라 한 줄로 묶였다. 둘 다 개별적으로는 라벨처럼
    보여서(`_looks_like_label`), 그 줄이 통째로 다음 줄("고미리" 이름이 있는
    줄)에 공백으로 이어붙었다 — "개인정보 학력사항 고미리 2008 2011
    예지디자인고등학교"라는 뒤죽박죽 문맥이 되어 NER이 "고미리"를 이름으로
    못 알아봤다(같은 이름을 단독으로 넣으면 잡힘). 서로 멀리 떨어진 항목이
    줄 안에 있으면 라벨로 취급하지 않아야 한다."""

    def test_two_far_apart_section_headers_are_not_a_single_label(self):
        from backend.scanner.detectors import text_ocr

        line = [
            ("개인정보", (42.0, 416.0, 166.0, 464.0)),
            ("학력사항", (436.0, 402.0, 572.0, 450.0)),
        ]
        self.assertFalse(text_ocr._row_is_single_cluster(line))

    def test_words_of_one_real_phrase_stay_a_single_label(self):
        from backend.scanner.detectors import text_ocr

        line = [
            ("입금", (0.0, 0.0, 40.0, 26.0)),
            ("계좌", (44.0, 0.0, 84.0, 26.0)),
        ]
        self.assertTrue(text_ocr._row_is_single_cluster(line))

    def test_single_word_row_is_trivially_a_single_cluster(self):
        from backend.scanner.detectors import text_ocr

        self.assertTrue(text_ocr._row_is_single_cluster([("입금계좌", (0.0, 0.0, 80.0, 26.0))]))

    def test_words_from_lines_does_not_glue_across_unrelated_section_headers(self):
        """`_words_from_lines`까지 통합해서, 실제로 줄바꿈으로 끊기는지 확인한다."""
        from backend.scanner.detectors import text_ocr

        lines = [
            [
                ("개인정보", (42.0, 416.0, 166.0, 464.0)),
                ("학력사항", (436.0, 402.0, 572.0, 450.0)),
            ],
            [("고미리", (110.0, 488.0, 180.0, 520.0))],
        ]
        text, _words, _oversized = text_ocr._words_from_lines(lines)
        self.assertIn("\n", text)
        self.assertNotIn("학력사항 고미리", text)

    def test_words_from_lines_still_glues_a_real_label_to_its_value(self):
        """회귀 방지: 진짜 라벨-값 이어붙이기(`_looks_like_label`)는 계속 살아있어야 한다."""
        from backend.scanner.detectors import text_ocr

        lines = [
            [("입금", (0.0, 0.0, 40.0, 26.0)), ("계좌", (44.0, 0.0, 84.0, 26.0))],
            [("국민", (0.0, 30.0, 40.0, 56.0)), ("6127-02-384915", (44.0, 30.0, 200.0, 56.0))],
        ]
        text, _words, _oversized = text_ocr._words_from_lines(lines)
        self.assertEqual(text, "입금 계좌 국민 6127-02-384915")


if __name__ == "__main__":
    unittest.main()
