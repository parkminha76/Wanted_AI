"""id_detector.detect()를 실제 YOLO 가중치로 돌려서 확인하는 회귀 평가.

test_id_detector_postprocess.py는 합성 dict로 후처리 함수(_require_anchor_evidence
등)만 검증한다. 그런데 실제로 터진 두 버그 — 인보이스 결제약관 문단이 address
0.519로 잡힌 것, 지원서 증명사진이 "face" 앵커로 인정되어 지원동기 문단이 같이
가려진 것 — 는 둘 다 후처리 로직이 아니라 모델이 실제 이미지에서 뭘 찍어내는지에서
나왔다. 합성 dict 테스트는 애초에 모델이 어떤 confidence로 뭘 찍을지를 가정으로
깔고 들어가므로 이런 종류의 회귀를 잡지 못한다.

이 파일은 실제 가중치(ml/models/infoguard_cnn_v1.pt, 저장소에 커밋되어 있음)로
두 가지를 확인한다:
  1. 진짜 신분증 샘플(data/test/test_img)은 문서 유형에 맞는 앵커 클래스를
     계속 찾아내는가 — 앵커 목록을 좁히면서 정탐까지 같이 줄이지 않았는지.
  2. 신분증이 아닌 문서(순수 텍스트, 증명사진+자기소개서)는 findings가 비는가.

모델 가중치가 없는 환경(예: 경량 CI)에서는 클래스 전체를 건너뛴다.
"""

from __future__ import annotations

import glob
import os
import tempfile
import unittest

from backend.scanner.detectors import id_detector

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SAMPLE_DIR = os.path.join(_REPO_ROOT, "data", "test", "test_img")
_FONT_PATH = os.path.join(_REPO_ROOT, "frontend", "public", "fonts", "NotoSansKR-Regular.ttf")
_FACE_SAMPLE = os.path.join(_REPO_ROOT, "data", "raw", "faces", "female_01.png")

# data/test/test_img의 파일명 규칙(aug_<문서유형>_<번호>.png)에서 문서유형을 뽑아,
# 그 문서라면 반드시 나와야 하는 앵커 클래스 중 하나로 매핑한다.
_EXPECTED_ANCHORS_BY_DOC_TYPE = {
    "driver": {"license_number", "resident_number"},
    "idcard": {"resident_number"},
    "passport": {"passport_number", "mrz"},
}


def _positive_samples() -> list[tuple[str, set[str]]]:
    samples = []
    for path in sorted(glob.glob(os.path.join(_SAMPLE_DIR, "*.png"))):
        name = os.path.basename(path)
        if "_result" in name:
            continue
        parts = name.split("_")
        if len(parts) < 2:
            continue
        expected = _EXPECTED_ANCHORS_BY_DOC_TYPE.get(parts[1])
        if expected:
            samples.append((path, expected))
    return samples


@unittest.skipUnless(
    os.path.exists(id_detector.MODEL_PATH), "ml/models/infoguard_cnn_v1.pt 가중치가 없어 건너뜀"
)
class IdDetectorRealInferenceEvalTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_paths: list[str] = []

    def tearDown(self) -> None:
        for path in self._tmp_paths:
            try:
                os.remove(path)
            except OSError:
                pass

    def _save_tmp(self, image) -> str:
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        image.save(path)
        self._tmp_paths.append(path)
        return path

    def test_positive_samples_keep_expected_anchor(self) -> None:
        samples = _positive_samples()
        self.assertTrue(samples, "data/test/test_img에서 샘플을 못 찾음")
        for path, expected_anchors in samples:
            with self.subTest(path=os.path.basename(path)):
                findings = id_detector.detect(path)
                classes = {f["evidence"]["cnn_class"] for f in findings}
                self.assertTrue(
                    classes & expected_anchors,
                    f"앵커 클래스 {expected_anchors} 중 하나도 안 잡힘 (검출: {classes})",
                )

    def test_plain_text_document_yields_no_findings(self) -> None:
        """실측 재현: 인보이스처럼 얼굴·신분증 번호 없이 문단만 있는 이미지는
        address가 낮은 문턱을 넘어 잡히더라도 앵커가 없어 전부 버려져야 한다."""
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (800, 1000), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(_FONT_PATH, 22)
        lines = [
            "결제 안내서",
            "아래 계좌로 대금을 입금해 주시기 바랍니다.",
            "본 약관에 동의하지 않으시는 경우 서비스 이용이 제한될 수 있습니다.",
            "계약 조건: 납품 후 30일 이내 입금",
            "주소: 서울특별시 강남구 테헤란로 123",
            "문의: 02-1234-5678",
        ]
        y = 60
        for line in lines:
            draw.text((60, y), line, fill="black", font=font)
            y += 50
        path = self._save_tmp(image)

        self.assertEqual(id_detector.detect(path), [])

    def test_photo_with_essay_text_yields_no_findings(self) -> None:
        """실측 재현: 자기소개서에 증명사진과 "지원동기" 문단이 같이 있으면, 얼굴이
        찍히더라도 그것만으로 신분증이라고 보고 옆 문단을 address로 가려선 안 된다.
        (이 테스트는 _ANCHOR_CLASSES에 face를 다시 넣으면 실패한다.)"""
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (900, 1200), "white")
        face = Image.open(_FACE_SAMPLE).resize((220, 260))
        image.paste(face, (650, 40))
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(_FONT_PATH, 22)
        essay_lines = [
            "자기소개서",
            "지원동기",
            "저는 신안산대학교 재학 중 다양한 프로젝트를 경험하며",
            "문제 해결 능력을 길렀습니다. 이러한 경험을 바탕으로",
            "귀사에 기여하고 싶어 지원하게 되었습니다.",
            "성장과정",
            "어린 시절부터 성실함을 최우선 가치로 삼아 왔습니다.",
        ]
        y = 60
        for line in essay_lines:
            draw.text((60, y), line, fill="black", font=font)
            y += 45
        path = self._save_tmp(image)

        self.assertEqual(id_detector.detect(path), [])


if __name__ == "__main__":
    unittest.main()
