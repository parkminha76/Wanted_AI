"""신분증 이미지에서 개인정보 영역을 찾는다. A가 학습시킨 YOLO 모델 호출부다.

텍스트 레이어가 없는 파일(신분증 사진, 스캔본 PDF)은 정규식·NER·서식 검사로
아무것도 할 수 없다. scan.py가 parse.py의 kind="image" 판정을 보고 이쪽으로
보내고, 여기서 얼굴·주민번호·서명 같은 영역을 좌표와 함께 돌려준다.

모델: ml/models/infoguard_cnn_v1.pt (ml/모델사용가이드.md 참고)
A가 재학습해도 경로는 고정이라 이 파일을 고칠 필요가 없다.

CNN은 OCR이 아니라 객체 탐지다 — "여기에 주민등록번호가 있다"는 영역만 알려주고
값 자체는 읽지 못한다. 그래서 value에는 읽어낸 값이 아니라 무엇을 찾았는지를
담고, 마스킹은 bbox 좌표로 한다.
"""

from __future__ import annotations

import os

MODEL_PATH = os.path.join("ml", "models", "infoguard_cnn_v1.pt")

# 탐지 신뢰도가 이 아래면 버린다. 낮게 두면 신분증 아닌 사진에서도 얼굴·서명이
# 잡혀 오탐이 되고, 높게 두면 기울어진 사진에서 주민번호를 놓친다.
CONFIDENCE_THRESHOLD = 0.25

# 같은 영역을 겹쳐 잡은 박스를 합치는 기준(NMS). ultralytics 기본값 0.7로 두면
# 같은 주민등록번호 자리가 두 건으로 잡혀서, 화면에 같은 항목이 두 번 뜨고
# type_counts가 "주민등록번호 2건"으로 틀어진다(발표 자료에 그대로 실린다).
#
# 0.3인 근거(합성 운전면허증 실측, 2026-09-11): 중복으로 잡힌 쌍의 IoU는
# 0.30~0.66인데, 서로 **다른** 클래스 간 최대 IoU는 0.08이었다. 그 사이를 끊으면
# 중복만 사라지고 인접한 다른 필드는 살아남는다. NMS는 같은 클래스끼리만
# 비교하므로, 신분증 두 장이 한 사진에 있어도(IoU 0) 각각 잡힌다.
_NMS_IOU_THRESHOLD = 0.3

# YOLO 클래스 -> schema.RiskType.
#
# 모델은 12개 클래스를 구분하는데 schema의 이미지 전용 타입은 3개(id_photo,
# signature, id_meta)뿐이다. 나머지는 텍스트 파이프라인과 **같은 타입으로 보낸다** —
# 신분증 사진에서 주민번호 영역을 찾았으면 그건 id_meta(10점)가 아니라 rrn(40점)이다.
# 위험도는 값이 어디에 적혀 있었는지가 아니라 무슨 값인지로 정해진다.
#
# sex(성별)와 mrz(여권 기계판독영역)는 schema에 대응 타입이 없다. 가장 가까운
# 타입으로 보내되 원래 클래스명을 evidence에 남겨서, 화면이 구체적으로 표시할 수
# 있고 나중에 schema에 타입이 추가되면 이 표만 고치면 되게 한다.
# mrz를 passport로 보내는 이유: MRZ 블록에는 여권번호·생년월일·성별·만료일이
# 인코딩되어 있어 여권번호 한 줄보다 오히려 더 많이 새는 자리다.
_CLASS_TO_RISK_TYPE: dict[str, str] = {
    "face": "id_photo",
    "name": "person",
    "resident_number": "rrn",
    "license_number": "driver_license",
    "address": "address",
    "issue_date": "id_meta",
    "expiry_date": "id_meta",
    "signature": "signature",
    "passport_number": "passport",
    "date_of_birth": "birth_date",
    "sex": "id_meta",
    "mrz": "passport",
}

# 화면에 그대로 나가는 문구다. CNN이 값을 읽은 것이 아니라 영역을 찾았을 뿐이라는
# 점이 드러나야 한다 — "주민등록번호 123456-1234567"처럼 보이면 안 된다.
_CLASS_LABELS: dict[str, str] = {
    "face": "얼굴 사진",
    "name": "이름 영역",
    "resident_number": "주민등록번호 영역",
    "license_number": "운전면허번호 영역",
    "address": "주소 영역",
    "issue_date": "발급일자",
    "expiry_date": "유효기간",
    "signature": "서명·도장",
    "passport_number": "여권번호 영역",
    "date_of_birth": "생년월일",
    "sex": "성별",
    "mrz": "여권 기계판독영역(MRZ)",
}

_model = None


def _get_model():
    """첫 호출 때 한 번만 로드하고 캐싱한다. import 시점에 불러오면 모델 파일이
    없는 환경에서 `import id_detector` 자체가 실패해 scan.py 전체가 멎는다."""
    global _model
    if _model is None:
        from ultralytics import YOLO

        _model = YOLO(MODEL_PATH)
    return _model


def detect(path: str) -> list[dict]:
    """이미지 1장에서 개인정보 영역을 찾는다.

    rules.py와 같은 형식에 좌표를 더해 돌려준다:
        [{field, value, start, end, confidence, bbox, page, reason, evidence}, ...]

    start/end는 0으로 둔다 — 이미지에는 문자 오프셋이라는 개념이 없다. 마스킹은
    bbox로 한다. 그래서 scan.py의 _dedupe는 이 결과에 아무 일도 하지 못한다
    (구간 겹침을 start/end로 판정하는데 둘 다 0이라 항상 "안 겹침"이 된다).
    겹친 박스를 합치는 일은 아래 NMS가 책임진다.
    """
    model = _get_model()
    findings: list[dict] = []
    for result in model.predict(
        path, conf=CONFIDENCE_THRESHOLD, iou=_NMS_IOU_THRESHOLD, verbose=False
    ):
        names = result.names
        for box in result.boxes:
            class_name = names[int(box.cls)]
            risk_type = _CLASS_TO_RISK_TYPE.get(class_name)
            if risk_type is None:
                continue
            x0, y0, x1, y1 = (float(v) for v in box.xyxy[0])
            label = _CLASS_LABELS.get(class_name, class_name)
            findings.append(
                {
                    "field": risk_type,
                    "value": label,
                    "start": 0,
                    "end": 0,
                    "confidence": round(float(box.conf), 3),
                    "bbox": (x0, y0, x1, y1),
                    "page": 1,
                    "reason": f"신분증 이미지에서 {label}을 찾았다",
                    "evidence": {"cnn_class": class_name, "model": "infoguard_cnn_v1"},
                }
            )
    return findings
