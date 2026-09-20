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


class MapBboxFromRotatedTest(unittest.TestCase):
    """`_map_point_from_rotated`/`_map_bbox_from_rotated`가 `np.rot90`의
    실제 회전과 맞는 역변환인지 확인한다. EasyOCR 없이 빠르게 도는 순수
    기하 테스트다 — `RotationRecoveryTest`(실제 OCR)가 확인하는 "회전 복구가
    실제로 작동하는가"와는 별개로, 여기서는 좌표 변환 공식 자체가 맞는지만
    본다."""

    def test_k_zero_is_identity(self):
        from backend.scanner.detectors import text_ocr

        bbox = (10.0, 20.0, 30.0, 40.0)
        self.assertEqual(text_ocr._map_bbox_from_rotated(bbox, 0, 100.0, 200.0), bbox)

    def test_inverse_matches_numpy_rot90_for_each_k(self):
        """공식을 손으로 베껴 대조하지 않고, `np.rot90` 자체에 점 하나를 찍어
        실제로 어디로 이동하는지 보고 그 결과를 되돌리는지 확인한다."""
        import numpy as np

        from backend.scanner.detectors import text_ocr

        h, w = 7, 11
        for k in (1, 2, 3):
            arr = np.zeros((h, w), dtype=int)
            x, y = 8, 2  # 원본에서 찍을 점 (x=열, y=행)
            arr[y, x] = 1
            rotated = np.rot90(arr, k=k)
            ry, rx = (int(v) for v in np.argwhere(rotated == 1)[0])
            mapped_x, mapped_y = text_ocr._map_point_from_rotated(
                float(rx), float(ry), k, float(w), float(h)
            )
            # np.rot90은 이산(정수 인덱스) 좌표라 연속 좌표 공식과 최대 1픽셀
            # 차이 날 수 있다 — bbox 용도로는 무의미한 오차다.
            self.assertLess(abs(mapped_x - x), 1.5)
            self.assertLess(abs(mapped_y - y), 1.5)


@unittest.skipUnless(_easyocr_available(), "EasyOCR을 불러올 수 없는 환경")
@unittest.skipUnless(os.path.isfile(FONT_PATH), "테스트용 한글 폰트가 없다")
class RotationRecoveryTest(unittest.TestCase):
    """실측 재현(2026-09-18, 모바일로 노트북 화면을 세로로 세워 찍은 사진):
    문서가 90도 돌아간 채로 찍히면 EasyOCR이 거의 못 읽어 마스킹이 통째로
    빠졌다(이름 3곳 중 0곳, 주소·전화 전부 노출 — 낱글자 단위로는 확신도가
    높게 나올 수 있어도 실제 단어는 하나도 안 읽힌다). 기본 방향에서 읽히는
    게 거의 없을 때만 90/180/270도로 다시 읽어보고, 되돌린 bbox가 실제로
    마스킹이 그려질 이 파일(회전된 그 파일 자체) 위의 올바른 자리를
    가리키는지 확인한다."""

    @classmethod
    def setUpClass(cls) -> None:
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np

        cls.tmpdir = tempfile.mkdtemp(prefix="infoguard_ocr_rotation_test_")
        cls.image_path = os.path.join(cls.tmpdir, "sideways_photo.png")

        upright = Image.new("RGB", (900, 500), "white")
        draw = ImageDraw.Draw(upright)
        font = ImageFont.truetype(FONT_PATH, 36)
        draw.text((60, 80), "성명: 김하늘", font=font, fill="black")
        draw.text((60, 160), "생년월일: 1993.05.24", font=font, fill="black")
        draw.text((60, 240), "연락처: 010-2847-3915", font=font, fill="black")
        draw.text((60, 320), "주소: 서울특별시 강남구 테헤란로 152", font=font, fill="black")

        # 카메라를 가로로 들고 찍은 것처럼 이미지 전체를 90도 돌린다
        # (np.rot90 k=3) — `_ocr_lines`의 회전 복구가 시도하는 방향 중 하나다.
        rotated = np.rot90(np.array(upright), k=3)
        Image.fromarray(rotated).save(cls.image_path)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_rotation_recovery_is_triggered_and_recorded(self) -> None:
        from backend.scanner.detectors import text_ocr

        _lines, _flags, _weak_lines, rotation = text_ocr._ocr_lines(self.image_path)
        self.assertIsNotNone(rotation)
        k, _orig_w, _orig_h = rotation
        self.assertIn(k, (1, 2, 3))

    def test_sideways_photo_still_finds_the_phone_number(self) -> None:
        from backend.scanner.detectors import text_ocr

        findings = text_ocr.detect(self.image_path)
        by_field = {f["field"]: f for f in findings}
        self.assertIn("phone", by_field)

    def test_bbox_stays_within_the_actual_rotated_file_bounds(self) -> None:
        """뒤집기 전(바로 세운) 좌표계가 아니라, 실제로 마스킹이 그려질 이
        회전된 파일 자체의 좌표계를 가리켜야 한다."""
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

    def test_bbox_actually_overlaps_real_content_not_blank_background(self) -> None:
        """좌표 변환이 방향을 잘못 잡으면 bbox가 범위 안에는 있어도 엉뚱한
        빈 배경을 가리킬 수 있다 — 이 파일(회전된 그 파일) 자체에서 bbox
        영역을 잘라내 실제 글자(흰 배경 위 검은 획)가 있는지 픽셀 분산으로
        확인한다. 공식을 다시 베끼지 않는 독립적인 검증이다."""
        import numpy as np
        from PIL import Image

        from backend.scanner.detectors import text_ocr

        findings = text_ocr.detect(self.image_path)
        by_field = {f["field"]: f for f in findings}
        self.assertIn("phone", by_field)
        left, top, right, bottom = by_field["phone"]["bbox"]

        with Image.open(self.image_path) as img:
            arr = np.array(img.convert("L"))
        crop = arr[int(top) : int(bottom), int(left) : int(right)]
        self.assertGreater(crop.size, 0)
        self.assertGreater(crop.std(), 20.0)


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

        with patch.object(text_ocr, "_ocr_lines", return_value=(lines, oversized_flags, lines, None)), \
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

    def test_stops_before_the_next_tables_header_row(self) -> None:
        """실측 재현(2026-09-18, 실제 지원서 사진 80-----.jpg): "직장명" 표
        바로 밑에 표 사이 간격 없이 "자격증" 표("발급일자"/"자격증명"/"등급"
        헤더)가 곧장 붙어 있었다. 두 표의 줄 간격이 완전히 같아서(44px)
        세로 간격 검사로는 표 경계를 못 잡고, "발급일자"·"2020년 4월"이
        회사명 값으로 잘못 잡혔다. 좌표는 그 표를 그대로 실측한 값이다."""
        from backend.scanner.detectors import text_ocr

        header = [
            ("직장명", (388.0, 750.0, 458.0, 782.0)),
            ("기간", (658.0, 752.0, 706.0, 780.0)),
            ("주요업무", (938.0, 752.0, 1028.0, 782.0)),
        ]
        row_a = [
            ("A식품", (338.0, 796.0, 402.0, 826.0)),
            ("2021년 3월", (522.0, 796.0, 648.0, 826.0)),
            ("2022년 5월", (676.0, 796.0, 804.0, 828.0)),
            ("식품 포장 및 검수 작업", (860.0, 796.0, 1096.0, 828.0)),
        ]
        row_b = [
            ("B식품", (338.0, 840.0, 400.0, 870.0)),
            ("2022년 6월", (522.0, 840.0, 648.0, 870.0)),
            ("2023년 2월", (676.0, 840.0, 802.0, 870.0)),
            ("원재료 투입 및 혼합", (860.0, 840.0, 1066.0, 872.0)),
        ]
        row_c = [
            ("C식품", (338.0, 884.0, 402.0, 914.0)),
            ("2023년 3월", (522.0, 884.0, 648.0, 914.0)),
            ("2024년 1월", (676.0, 884.0, 804.0, 914.0)),
            ("위생 관리", (860.0, 884.0, 958.0, 916.0)),
        ]
        next_table_header = [
            ("발급일자", (378.0, 928.0, 470.0, 960.0)),
            ("자격증명", (636.0, 928.0, 728.0, 960.0)),
            ("등급", (960.0, 928.0, 1004.0, 960.0)),
        ]
        next_table_row = [
            ("2020년 4월", (338.0, 974.0, 464.0, 1004.0)),
            ("영어 회화 능력 우수", (522.0, 972.0, 728.0, 1004.0)),
            ("TOEIC 850점", (858.0, 974.0, 1000.0, 1004.0)),
        ]
        lines = [header, row_a, row_b, row_c, next_table_header, next_table_row]
        cells = text_ocr._find_table_column_cells(lines)
        values = {c["value"] for c in cells}
        self.assertEqual(values, {"A식품", "B식품", "C식품"})


class BboxForRangeSubWordInterpolationTest(unittest.TestCase):
    """실측 재현(2026-09-18, 실제 지원서 사진): EasyOCR이 "지원동기" 문단 첫
    줄 전체("저는 식품 공장에서... 홍길동입니다: A식품 B식품")를 검출 하나
    (bbox 하나)로 묶어서 돌려줬다. 그 안에서 "홍길동"·"A식품"만 찾았는데
    검출의 bbox 전체(문장 전체 폭)를 그대로 마스킹하면, 값과 무관한 문장
    전체가 덮인다 — 사용자가 스크린샷으로 직접 지적함("그것만 안 보이게
    해야지 통째로 삭제하면 안되지"). 단어 폭 안에서 글자 위치 비율만큼
    좁혀야 한다."""

    def test_match_in_the_middle_of_one_merged_word_is_narrowed(self):
        from backend.scanner.detectors import text_ocr

        # "저는유명한사람입니다" 10글자가 (0,0)~(200,20) 폭에 통째로 검출된
        # 경우를 흉내낸다. 한 글자당 20px씩 균일하다고 가정하면, 5번째 글자
        # ("한", 인덱스 4)부터 6번째("사"기 전, 인덱스 6 미포함)까지는 비례로는
        # x=80~120이지만, 글자 폭 불균일 오차를 흡수하려고 평균 글자 폭(20px)
        # 만큼 양옆으로 더 넓힌 x=60~140이 나와야 한다.
        word = text_ocr._Word(start=0, end=10, bbox=(0.0, 0.0, 200.0, 20.0))
        bbox = text_ocr._bbox_for_range([word], 4, 6)
        self.assertAlmostEqual(bbox[0], 60.0)
        self.assertAlmostEqual(bbox[2], 140.0)
        self.assertEqual((bbox[1], bbox[3]), (0.0, 20.0))

    def test_range_covering_the_whole_word_returns_the_original_bbox(self):
        """회귀 방지: 구간이 단어 전체를 덮는 보통의 경우(대다수 findings)는
        원래 단어 bbox 그대로 나와야 한다 — 근사 계산으로 기존 동작이 바뀌면
        안 된다."""
        from backend.scanner.detectors import text_ocr

        word = text_ocr._Word(start=5, end=15, bbox=(50.0, 10.0, 150.0, 40.0))
        bbox = text_ocr._bbox_for_range([word], 5, 15)
        self.assertEqual(bbox, (50.0, 10.0, 150.0, 40.0))

    def test_range_spanning_two_words_still_unions_both_narrowed_parts(self):
        from backend.scanner.detectors import text_ocr

        word_a = text_ocr._Word(start=0, end=10, bbox=(0.0, 0.0, 100.0, 20.0))
        word_b = text_ocr._Word(start=11, end=21, bbox=(110.0, 0.0, 210.0, 20.0))
        # 두 단어에 걸친 구간 — 첫 단어는 뒤쪽 절반만, 둘째 단어는 앞쪽 절반만.
        # 각 단어 안에서 평균 글자 폭(10px)만큼 안전 여유를 더하되 그 단어
        # 자신의 bbox 밖으로는 안 나간다: word_a는 [40, 100](오른쪽은 자기
        # 끝에서 막힘), word_b는 [110, 170]. 둘을 합친 전체 범위가 [40, 170]이다.
        bbox = text_ocr._bbox_for_range([word_a, word_b], 5, 16)
        self.assertAlmostEqual(bbox[0], 40.0)
        self.assertAlmostEqual(bbox[2], 170.0)


class FindCareerListEntriesTest(unittest.TestCase):
    """실측 재현(2026-09-18, 실제 이력서 사진 고미리.png): "경력정보" 섹션은
    표가 아니라 목록이라 "회사명" 열 헤더가 없다. NER이 "디자인전략 매직
    디자인 인수"는 아예 못 잡고 "리우나 주거디자인 콘텐츠 마케팅"은 사람
    이름으로 잘못 잡아서, "연도 - 연도" 구조로 기하학적으로 잡는 함수를
    추가했다. 좌표는 그 문서를 그대로 실측한 값이다."""

    HEADER_ROW = [("경력정보", (436.0, 696.0, 570.0, 746.0))]
    # 2단 레이아웃이라 왼쪽 칸("서초시...")이 같은 줄에 같이 잡힌다.
    HEADER_ROW_WITH_LEFT_COLUMN_BLEED = [
        ("서초시 미리동 미리로", (109.0, 681.0, 329.0, 717.0)),
        ("128-9", (110.0, 714.0, 184.0, 744.0)),
        ("경력정보", (436.0, 696.0, 570.0, 746.0)),
    ]
    ENTRY_1 = [
        ("2006", (446.0, 768.0, 510.0, 798.0)),
        ("2011", (522.0, 770.0, 582.0, 796.0)),
        ("디자인전락 매직 디자인 인수", (639.0, 765.0, 943.0, 801.0)),
    ]
    # 왼쪽 칸("자격증" 섹션)의 글자가 같이 잡힌 행 — 열 필터가 걸러내야 한다.
    LEFT_COLUMN_ONLY_ROW = [
        ("자격증", (43.0, 813.0, 139.0, 857.0)),
        ("주요 업무 내용이 입력해주세요", (640.0, 804.0, 922.0, 834.0)),
    ]
    ENTRY_2_WITH_LEFT_BLEED = [
        ("2008.03", (52.0, 926.0, 141.0, 952.0)),
        ("전산운용기능사", (162.0, 924.0, 328.0, 956.0)),
        ("2006", (446.0, 938.0, 510.0, 966.0)),
        ("2009", (522.0, 938.0, 586.0, 966.0)),
        ("(주) MD 디자인예이전시 인터 근무", (638.0, 938.0, 990.0, 970.0)),
    ]
    # 연도만 있고 회사명 글자가 이 행엔 없는 경우(다른 행에 있거나 OCR이
    # 못 읽음) — 값 없이 끝나면 항목을 만들면 안 된다.
    YEARS_WITHOUT_A_VALUE_ROW = [
        ("2008.05", (52.0, 1016.0, 144.0, 1044.0)),
        ("GTQ 일러스트 1급", (162.0, 1014.0, 356.0, 1046.0)),
        ("2006", (446.0, 1024.0, 510.0, 1054.0)),
        ("2009", (522.0, 1024.0, 586.0, 1052.0)),
    ]
    NEXT_SECTION_ROW = [
        ("기술 숙권도", (45.0, 1129.0, 207.0, 1173.0)),
        ("수상경력", (434.0, 1142.0, 568.0, 1192.0)),
    ]

    def test_entries_after_year_range_are_caught_with_left_column_excluded(self) -> None:
        from backend.scanner.detectors import text_ocr

        lines = [
            self.HEADER_ROW_WITH_LEFT_COLUMN_BLEED,
            self.ENTRY_1,
            self.LEFT_COLUMN_ONLY_ROW,
            self.ENTRY_2_WITH_LEFT_BLEED,
            self.YEARS_WITHOUT_A_VALUE_ROW,
            self.NEXT_SECTION_ROW,
        ]
        results = text_ocr._find_career_list_entries(lines)
        values = {r["value"] for r in results}
        self.assertEqual(values, {"디자인전락 매직 디자인 인수", "(주) MD 디자인예이전시 인터 근무"})
        for r in results:
            self.assertEqual(r["field"], "org")
            # 왼쪽 칸 글자("자격증"·"전산운용기능사" 등)가 값에 안 섞여야 한다.
            self.assertNotIn("전산운용기능사", r["value"])
            self.assertNotIn("자격증", r["value"])

    def test_row_with_only_years_and_no_trailing_text_produces_nothing(self) -> None:
        from backend.scanner.detectors import text_ocr

        lines = [self.HEADER_ROW, self.YEARS_WITHOUT_A_VALUE_ROW]
        self.assertEqual(text_ocr._find_career_list_entries(lines), [])

    def test_no_header_produces_nothing(self) -> None:
        from backend.scanner.detectors import text_ocr

        self.assertEqual(text_ocr._find_career_list_entries([self.ENTRY_1]), [])

    def test_defers_to_the_real_table_detector_when_column_headers_are_present(self) -> None:
        """실측 재현(2026-09-18, 실제 이력서 사진 865f267df9c220bf.jpg): "경력사항"이
        진짜 표(회사명/경력/소속 열이 있는)의 제목으로 쓰인 문서도 있다. 그 표는
        `_find_table_column_cells`가 이미 정확히 처리하므로, 이 함수는 그 구간에
        진짜 열 헤더가 보이면 아무것도 잡지 않고 물러나야 한다 — 안 그러면
        여러 열의 글자를 한 값으로 뭉쳐 잡는다."""
        from backend.scanner.detectors import text_ocr

        career_title = [("경력사항", (25.0, 337.0, 71.0, 353.0))]
        real_table_header = [
            ("기간", (63.0, 367.0, 85.0, 381.0)),
            ("회사명", (140.5, 369.5, 165.5, 379.0)),
            ("경력", (252.5, 369.5, 268.5, 379.0)),
            ("소속", (357.5, 370.0, 374.0, 379.0)),
        ]
        data_row = [
            ("2022", (47.0, 427.0, 71.0, 439.0)),
            ("2023", (75.0, 427.0, 101.0, 439.0)),
            ("Liceria", (125.0, 427.0, 157.0, 439.0)),
            ("디자인팀", (347.0, 427.0, 385.0, 441.0)),
        ]
        lines = [career_title, real_table_header, data_row]
        self.assertEqual(text_ocr._find_career_list_entries(lines), [])

    def test_year_range_merged_into_a_single_cell_is_still_caught(self) -> None:
        """실측 재현(2026-09-18, 저해상도 이력서 사진 865f267df9c220bf.jpg): 같은
        표 안에서도 "연도 - 연도"가 줄마다 다르게 검출된다 — "2022"/"2023"처럼
        따로 잡히는 줄도 있고, "2024 * 2025"처럼(저해상도라 "-"가 "*"로
        오독된) 한 칸으로 통째로 잡히는 줄도 있다. 이 문서는 표 헤더
        ("회사명"/"경력"/"소속")도 저해상도 탓에 "기간" 한 칸만 읽혀서
        `_match_header_labels`가 표로 인식하지 못한다 — 그래도 회사명("Fauget"이
        "FauBct"로 오독)은 놓치면 안 된다."""
        from backend.scanner.detectors import text_ocr

        career_title = [("경력사항", (25.0, 337.0, 71.0, 353.0))]
        weak_header_row = [("기간", (63.0, 367.0, 85.0, 381.0))]
        merged_year_row = [
            ("2024 * 2025", (47.0, 397.0, 101.0, 411.0)),
            ("FauBct", (137.0, 397.0, 171.0, 411.0)),
            ("디자인터", (347.0, 397.0, 385.0, 411.0)),
        ]
        lines = [career_title, weak_header_row, merged_year_row]
        results = text_ocr._find_career_list_entries(lines)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["field"], "org")
        self.assertIn("FauBct", results[0]["value"])

    def test_year_range_merged_cell_with_only_one_trailing_word_produces_nothing(self) -> None:
        """실측 재현(같은 문서): 회사명·소속 칸이 통째로 OCR에서 빠지고 "경력"란
        (업무 설명, 예: "프로모신 디자인")만 한 칸 남는 줄도 있다. 남은 칸이
        하나뿐이면 그게 회사명인지 업무 설명인지 구별할 수 없으므로, 최소
        두 칸은 남아야 회사명으로 잡는다 — 안 그러면 업무 설명을 회사명으로
        잘못 가린다."""
        from backend.scanner.detectors import text_ocr

        career_title = [("경력사항", (25.0, 337.0, 71.0, 353.0))]
        weak_header_row = [("기간", (63.0, 367.0, 85.0, 381.0))]
        only_role_column_row = [
            ("2020 - 2021", (47.0, 455.0, 101.0, 469.0)),
            ("프로모신 디자인", (229.0, 455.0, 295.0, 469.0)),
        ]
        lines = [career_title, weak_header_row, only_role_column_row]
        self.assertEqual(text_ocr._find_career_list_entries(lines), [])

    def test_value_stops_at_a_column_sized_gap_instead_of_gluing_the_next_column(self) -> None:
        """실측 재현(같은 문서, 2026-09-18): 표 헤더를 못 읽어 이 함수로 떨어진
        줄에서, "회사명"란 값("FauBct") 뒤에 "경력"란을 건너뛰고 "소속"란
        ("디자인터")까지 한 값으로 뭉쳐 잡혔다 — 마스킹 박스가 "경력"란까지
        통째로 덮었다. "회사명"과 "소속" 사이 가로 간격(176px)이 줄 높이의
        몇 배나 되면 그 뒤는 다른 열로 보고 잘라야 한다."""
        from backend.scanner.detectors import text_ocr

        career_title = [("경력사항", (25.0, 337.0, 71.0, 353.0))]
        weak_header_row = [("기간", (63.0, 367.0, 85.0, 381.0))]
        merged_year_row = [
            ("2024 * 2025", (47.0, 397.0, 101.0, 411.0)),
            ("FauBct", (137.0, 397.0, 171.0, 411.0)),
            ("디자인터", (347.0, 397.0, 385.0, 411.0)),
        ]
        lines = [career_title, weak_header_row, merged_year_row]
        results = text_ocr._find_career_list_entries(lines)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["value"], "FauBct")
        self.assertEqual(results[0]["bbox"], (137.0, 397.0, 171.0, 411.0))

    def test_multi_word_org_name_detected_as_one_close_cluster_is_not_trimmed(self) -> None:
        """회귀 방지: 진짜 여러 단어짜리 회사명(실측: "디자인전략 매직 디자인
        인수")은 EasyOCR이 한 덩어리로 검출해서 칸 사이 간격이랄 게 없다 —
        새 간격 컷오프가 이런 정상 사례를 자르면 안 된다."""
        from backend.scanner.detectors import text_ocr

        lines = [
            self.HEADER_ROW,
            self.ENTRY_1,
        ]
        results = text_ocr._find_career_list_entries(lines)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["value"], "디자인전락 매직 디자인 인수")


class FindWeakTextPersonNamesTest(unittest.TestCase):
    """실측 재현(2026-09-18, 실제 지원서 사진): "지원동기" 문단 전체가 확신도
    0.21로 잡혀 본문 `text`(0.3 문턱)에서 빠졌다. 그 문단 속 이름 "홍길동"은
    표에서 확정된 값이 아니라서(성명 칸의 값은 다른 이름 "이예지") 표 교차
    대조로도 못 찾는다 — weak_text에 직접 NER을 돌리되 person 판정만 받아야
    한다."""

    def test_person_in_weak_text_is_found(self) -> None:
        from unittest.mock import patch

        from backend.scanner import scan
        from backend.scanner.detectors import text_ocr
        from backend.shared.schema import Finding

        weak_text = "저는 식품 공장에서 근무한 홍길동입니다."
        _t, weak_words, _o = text_ocr._words_from_lines(
            [[(weak_text, (0.0, 0.0, 500.0, 20.0))]]
        )
        person_start = weak_text.index("홍길동")

        def fake_scan_text(text, meta=None):
            return scan.ScanResult(
                raw_text=text,
                findings=[
                    Finding(
                        id="f_1",
                        type="person",
                        text="홍길동",
                        start=person_start,
                        end=person_start + len("홍길동"),
                        confidence=0.5,
                        reason="test",
                        source="ner",
                        evidence={},
                    )
                ],
            )

        with patch.object(scan, "scan_text", side_effect=fake_scan_text):
            found = text_ocr._find_weak_text_person_names(weak_text, weak_words, [])

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["field"], "person")
        self.assertEqual(found[0]["value"], "홍길동")

    def test_non_person_findings_are_ignored(self) -> None:
        """injection·org 같은 다른 타입은 확신도 낮은 텍스트에서 받으면 안 된다
        — OCR 잡음이 인젝션 분류기를 오탐시킨 전례가 있다(`_CROSS_REFERENCE_MIN_CONFIDENCE`
        주석 참고). person만 좁게 받아야 그 오탐 경로가 안 열린다."""
        from unittest.mock import patch

        from backend.scanner import scan
        from backend.scanner.detectors import text_ocr
        from backend.shared.schema import Finding

        weak_text = "ITQAAS AS 어쩌구"
        _t, weak_words, _o = text_ocr._words_from_lines(
            [[(weak_text, (0.0, 0.0, 500.0, 20.0))]]
        )

        def fake_scan_text(text, meta=None):
            return scan.ScanResult(
                raw_text=text,
                findings=[
                    Finding(
                        id="f_1",
                        type="injection",
                        text=weak_text,
                        start=0,
                        end=len(weak_text),
                        confidence=0.77,
                        reason="test",
                        source="classifier",
                        evidence={},
                    )
                ],
            )

        with patch.object(scan, "scan_text", side_effect=fake_scan_text):
            found = text_ocr._find_weak_text_person_names(weak_text, weak_words, [])
        self.assertEqual(found, [])

    def test_position_already_covered_by_an_existing_finding_is_skipped(self) -> None:
        from unittest.mock import patch

        from backend.scanner import scan
        from backend.scanner.detectors import text_ocr
        from backend.shared.schema import Finding

        weak_text = "홍길동"
        _t, weak_words, _o = text_ocr._words_from_lines(
            [[(weak_text, (0.0, 0.0, 100.0, 20.0))]]
        )

        def fake_scan_text(text, meta=None):
            return scan.ScanResult(
                raw_text=text,
                findings=[
                    Finding(
                        id="f_1",
                        type="person",
                        text="홍길동",
                        start=0,
                        end=3,
                        confidence=0.5,
                        reason="test",
                        source="ner",
                        evidence={},
                    )
                ],
            )

        with patch.object(scan, "scan_text", side_effect=fake_scan_text):
            found = text_ocr._find_weak_text_person_names(
                weak_text, weak_words, [(0.0, 0.0, 100.0, 20.0)]
            )
        self.assertEqual(found, [])


class FindCrossReferencedValuesTest(unittest.TestCase):
    """실측 재현(2026-09-18, 실제 지원서 사진): "직장명" 표에서 "A식품"/"B식품"이
    회사명으로 확정됐는데, 바로 아래 "지원동기" 자기소개서 문단에 똑같이 적힌
    "A식품, B식품"은 NER이 하나도 못 잡았다(같은 문장의 사람 이름 "홍길동"은
    잡히는 것과 대비 — NER 모델 자체가 이 모양의 회사명에 약하다). 표에서
    이미 확정된 값과 똑같은 문자열이 다른 자리에도 나오면 같이 잡아야 한다."""

    def test_value_confirmed_by_table_is_found_again_in_free_text(self):
        """`_bbox_for_range`가 검출 하나(문장 전체)의 일부만 비례로 좁혀 돌려주므로
        (실측 재현: 2026-09-18, 아래 `BboxForRangeSubWordInterpolationTest` 참고),
        여기서 나오는 bbox는 문장 전체 폭이 아니라 "A식품" 위치 근처로 좁아야 한다."""
        from backend.scanner.detectors import text_ocr

        text = "저는 식품 공장에서 근무한 홍길동입니다. A식품에서 일했습니다."
        sentence_bbox = (0.0, 0.0, 500.0, 20.0)
        _t, words, _o = text_ocr._words_from_lines([[(text, sentence_bbox)]])
        table_cells = [
            {"field": "org", "value": "A식품", "bbox": (600.0, 600.0, 650.0, 620.0)}
        ]
        found = text_ocr._find_cross_referenced_values(text, words, table_cells)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["field"], "org")
        self.assertEqual(found[0]["value"], "A식품")
        left, top, right, bottom = found[0]["bbox"]
        self.assertEqual((top, bottom), (0.0, 20.0))
        self.assertLess(right - left, sentence_bbox[2] - sentence_bbox[0])
        self.assertGreater(left, 0.0)
        self.assertLess(right, 500.0)

    def test_the_table_cells_own_position_is_not_duplicated(self):
        """표 셀 자기 자신의 자리(=table_cells가 이미 갖고 있는 bbox)는
        다시 잡으면 안 된다 — 안 그러면 같은 값이 같은 자리에서 두 번 잡힌다."""
        from backend.scanner.detectors import text_ocr

        text = "A식품"
        _t, words, _o = text_ocr._words_from_lines([[(text, (10.0, 10.0, 60.0, 30.0))]])
        table_cells = [{"field": "org", "value": "A식품", "bbox": (10.0, 10.0, 60.0, 30.0)}]
        found = text_ocr._find_cross_referenced_values(text, words, table_cells)
        self.assertEqual(found, [])

    def test_unread_placeholder_cells_are_not_searched_for(self):
        """`_collect_column_rows`가 값을 못 읽어 방어적으로 채운 자리
        ("{라벨} 미확인 값")는 실제 값이 아니므로 그 문구를 문서에서 찾지
        않는다."""
        from backend.scanner.detectors import text_ocr

        text = "직장명 미확인 값이라는 말이 우연히 나온 문장입니다."
        _t, words, _o = text_ocr._words_from_lines([[(text, (0.0, 0.0, 500.0, 20.0))]])
        table_cells = [
            {
                "field": "org",
                "value": "직장명 미확인 값",
                "bbox": (600.0, 600.0, 650.0, 620.0),
                "evidence": {"unread": True},
            }
        ]
        found = text_ocr._find_cross_referenced_values(text, words, table_cells)
        self.assertEqual(found, [])

    def test_confusable_leading_letter_is_matched_when_exact_form_is_ocr_misread(self):
        """실측 재현(2026-09-18, 아르바이트 지원서): 표에서 "C식품"으로 확정된
        값이 자유 서술문에서는 "C"가 "("로 오독되어("(식품 공장에서...")
        정확한 문자열이 그 자리에 존재하지 않았다. 표 셀 자기 위치 외에는
        정확히 일치하는 자리가 하나도 없을 때만, 영문 한 글자를 흔한 오독
        기호(괄호·숫자)로 바꾼 형태도 찾아야 한다."""
        from backend.scanner.detectors import text_ocr

        text = "C식품 근무하며 (식품 공장에서 근무하다 생산 라인 관리"
        _t, words, _o = text_ocr._words_from_lines([[(text, (0.0, 0.0, 500.0, 20.0))]])
        table_cells = [{"field": "org", "value": "C식품", "bbox": (0.0, 0.0, 60.0, 20.0)}]
        found = text_ocr._find_cross_referenced_values(text, words, table_cells)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["value"], "C식품")
        left, _top, _right, _bottom = found[0]["bbox"]
        self.assertGreater(left, 60.0)

    def test_multiple_values_do_not_cross_contaminate_via_confusable_fallback(self):
        """A식품처럼 정확히 일치하는 값이 있는 경우와 C식품처럼 오독으로만 찾을
        수 있는 값이 같은 문서에 섞여 있을 때, C식품의 느슨한 폴백 패턴이
        A식품 자리까지 다시 잡아 중복/오표기하면 안 된다."""
        from backend.scanner.detectors import text_ocr

        text = "지원동기: A식품 (식품 공장에서 근무했습니다"
        _t, words, _o = text_ocr._words_from_lines([[(text, (0.0, 0.0, 500.0, 20.0))]])
        table_cells = [
            {"field": "org", "value": "A식품", "bbox": (600.0, 600.0, 650.0, 620.0)},
            {"field": "org", "value": "C식품", "bbox": (700.0, 600.0, 750.0, 620.0)},
        ]
        found = text_ocr._find_cross_referenced_values(text, words, table_cells)
        self.assertEqual(len(found), 2)
        values = sorted(f["value"] for f in found)
        self.assertEqual(values, ["A식품", "C식품"])


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

    def test_overlapping_table_cells_do_not_evict_each_other(self):
        """실측 재현(2026-09-18, 아르바이트 지원서): 자유 서술문에 이어붙은
        "A식품 B식품"처럼 인접한 두 값의 교차참조 sub-word bbox가 서로 살짝
        겹칠 수 있는데, 예전 코드는 table_cells를 하나씩 append하며 겹침을
        검사해서 뒤에 처리된 셀이 먼저 넣은 셀을 지워버렸다(B식품이 A식품을
        밀어냄). table_cells끼리는 서로 지우면 안 된다 — 둘 다 표에서 확정된
        진짜 값이다."""
        from backend.scanner.detectors import text_ocr

        table_cells = [
            {"field": "org", "value": "A식품", "bbox": (968.0, 1099.0, 1054.0, 1135.0)},
            {"field": "org", "value": "B식품", "bbox": (1037.0, 1099.0, 1105.0, 1135.0)},
        ]
        merged = text_ocr._merge_table_cells([], table_cells)
        self.assertEqual(len(merged), 2)
        self.assertIn(table_cells[0], merged)
        self.assertIn(table_cells[1], merged)


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


class RecoverNumberedListGapsTest(unittest.TestCase):
    """실측 재현(2026-09-20): 참석자명단.png "7. 김경자 (넥스트브릿지)"가
    EasyOCR 확신도 0.255로 `_EASYOCR_MIN_CONFIDENCE`(0.3) 바로 아래에서
    걸러져 raw_text에서 통째로 빠졌다. 문턱 자체를 낮추면 배경 잡음이
    인젝션 분류기를 오탐시킨 전례가 있어(`_EASYOCR_MIN_CONFIDENCE` 주석
    참고) 대신 "번호 목록에서 번호 하나가 빔"이라는 구조만 보고 좁게
    구제한다."""

    @staticmethod
    def _row(text: str, y: float) -> list:
        return [(text, (10.0, y, 200.0, y + 30.0))]

    def test_missing_middle_item_is_recovered_from_weak_rows(self):
        from backend.scanner.detectors import text_ocr

        rows = [
            self._row("1. 김영수 (블루웨이브 솔루션)", 100),
            self._row("2. 김지영 (넥스트브릿지)", 150),
            self._row("4. 황광수 (대한소프트)", 250),
        ]
        weak_rows = [
            self._row("3. 김경자 (한빛전자)", 200),
        ]
        recovered = text_ocr._recover_numbered_list_gaps(rows, weak_rows)
        texts = [row[0][0] for row in recovered]
        self.assertEqual(
            texts,
            [
                "1. 김영수 (블루웨이브 솔루션)",
                "2. 김지영 (넥스트브릿지)",
                "3. 김경자 (한빛전자)",
                "4. 황광수 (대한소프트)",
            ],
        )

    def test_fewer_than_three_numbered_rows_is_not_treated_as_a_list(self):
        """번호가 하나·둘만 보이면 우연일 수 있다 — 목록이라고 단정하지 않는다."""
        from backend.scanner.detectors import text_ocr

        rows = [self._row("1. 김영수 (블루웨이브 솔루션)", 100)]
        weak_rows = [self._row("2. 잡음", 150)]
        recovered = text_ocr._recover_numbered_list_gaps(rows, weak_rows)
        self.assertEqual(recovered, rows)

    def test_weak_row_with_wrong_number_is_not_pulled_in(self):
        """빠진 자리(3번)가 아닌 다른 번호로 시작하는 weak_row는 채우지 않는다."""
        from backend.scanner.detectors import text_ocr

        rows = [
            self._row("1. 김영수 (블루웨이브 솔루션)", 100),
            self._row("2. 김지영 (넥스트브릿지)", 150),
            self._row("4. 황광수 (대한소프트)", 250),
        ]
        weak_rows = [self._row("5. 잡음 (엉뚱한 회사)", 300)]
        recovered = text_ocr._recover_numbered_list_gaps(rows, weak_rows)
        self.assertEqual(recovered, rows)

    def test_no_gap_returns_rows_unchanged(self):
        from backend.scanner.detectors import text_ocr

        rows = [
            self._row("1. 김영수 (블루웨이브 솔루션)", 100),
            self._row("2. 김지영 (넥스트브릿지)", 150),
            self._row("3. 황광수 (대한소프트)", 200),
        ]
        recovered = text_ocr._recover_numbered_list_gaps(rows, [])
        self.assertEqual(recovered, rows)


if __name__ == "__main__":
    unittest.main()
