"""누워 있는 신분증도 찾아내고, 좌표는 원본 기준으로 돌려준다.

실측(2026-09-20, 세로로 세워 찍은 주민등록증 견본 380x740): 원본 방향에서는 얼굴
하나(0.252)만 잡혀 앵커가 없었고, 반시계 90도로 돌리자 주민등록번호까지 6건이
잡혔다. 앵커가 없으면 scan.py가 "신분증이 아니다"로 거부하므로, 회전 보정이 없으면
멀쩡한 신분증이 반려된다.

좌표 역매핑이 틀어지면 마스킹이 엉뚱한 자리를 가리므로 값까지 못박아 둔다.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from backend.scanner.detectors import id_detector


def _finding(cnn_class: str, field: str, bbox: tuple) -> dict:
    return {
        "field": field,
        "value": cnn_class,
        "start": 0,
        "end": 0,
        "confidence": 0.9,
        "bbox": bbox,
        "page": 1,
        "reason": "",
        "evidence": {"cnn_class": cnn_class, "model": "infoguard_cnn_v1"},
    }


class IdDetectorRotationTest(unittest.TestCase):
    def setUp(self) -> None:
        # 가로 200 x 세로 100. 회전 좌표 계산이 정사각형에서는 틀려도 드러나지 않는다.
        self.path = os.path.join(tempfile.mkdtemp(), "card.png")
        cv2.imwrite(self.path, np.full((100, 200, 3), 240, dtype=np.uint8))

    def test_rotated_card_is_detected_and_bbox_mapped_back(self) -> None:
        def fake_frame(source):
            if isinstance(source, str):
                # 바로 세운 방향: 얼굴만 — 앵커가 없어 신분증으로 인정되지 않는다.
                return [_finding("face", "id_photo", (0.0, 0.0, 10.0, 10.0))], 200, 100
            # 돌린 방향(k=1이면 100x200): 주민등록번호가 잡힌다.
            height, width = source.shape[:2]
            return [_finding("resident_number", "rrn", (10.0, 20.0, 30.0, 40.0))], width, height

        with patch.object(id_detector, "_detect_frame", side_effect=fake_frame):
            out = id_detector.detect(self.path)

        classes = [f["evidence"]["cnn_class"] for f in out]
        self.assertIn("resident_number", classes)

        rrn = next(f for f in out if f["evidence"]["cnn_class"] == "resident_number")
        # k=1(반시계 90도)의 역변환은 (x, y) -> (orig_w - y, x)다.
        # 네 모서리를 옮기면 x는 160~180, y는 10~30이 된다.
        self.assertEqual(rrn["bbox"], (160.0, 10.0, 180.0, 30.0))
        self.assertEqual(rrn["evidence"]["rotated_k"], 1)

    def test_upright_card_is_not_rotated(self) -> None:
        """바로 세운 방향에서 앵커를 찾으면 돌려보지 않는다(비용 4배를 아낀다)."""
        calls = []

        def fake_frame(source):
            calls.append(source)
            return [_finding("resident_number", "rrn", (1.0, 2.0, 3.0, 4.0))], 200, 100

        with patch.object(id_detector, "_detect_frame", side_effect=fake_frame):
            out = id_detector.detect(self.path)

        self.assertEqual(len(calls), 1)
        self.assertEqual(out[0]["bbox"], (1.0, 2.0, 3.0, 4.0))
        self.assertNotIn("rotated_k", out[0]["evidence"])


if __name__ == "__main__":
    unittest.main()
