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

# 주소는 글자가 여러 줄이고 바탕 무늬와 겹쳐 다른 필드보다 신뢰도가 낮게 나온다.
# 실제 주민등록증 샘플에서 주소 첫 줄은 0.208, 이어지는 두 줄은 0.062로 나뉘어
# 검출됐다. 첫 줄만 가리면 상세 주소가 그대로 남으므로 주소 클래스만 낮은 후보까지
# 받는다. 전체 기준을 낮추면 다른 클래스 오탐도 함께 늘어나므로 나머지는 0.25다.
# MRZ가 있는 여권에서는 아래 문서 규칙으로 address 후보를 전부 제거한다.
_CLASS_CONFIDENCE_THRESHOLDS: dict[str, float] = {"address": 0.05}
_INFERENCE_CONFIDENCE_FLOOR = min(
    [CONFIDENCE_THRESHOLD, *_CLASS_CONFIDENCE_THRESHOLDS.values()]
)

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


def _class_threshold(class_name: str) -> float:
    return _CLASS_CONFIDENCE_THRESHOLDS.get(class_name, CONFIDENCE_THRESHOLD)


def _filter_passport_incompatible(findings: list[dict]) -> list[dict]:
    """MRZ가 있는 여권에서 문서 구조상 불가능한 필드 오탐을 제거한다.

    여권에는 주소·주민등록번호·운전면허번호가 인쇄되지 않는다. 또한 펼친 여권에서
    얼굴이 위아래 두 개 잡힌 경우, 실제 성명은 MRZ와 같은 아래쪽 인적사항 면에
    있고 위쪽 안내문·천공번호에서 나온 name 후보는 오탐이다.
    """
    classes = [item.get("evidence", {}).get("cnn_class") for item in findings]
    if "mrz" not in classes:
        return findings

    incompatible = {"address", "resident_number", "license_number"}
    filtered = [
        item
        for item in findings
        if item.get("evidence", {}).get("cnn_class") not in incompatible
    ]

    faces = sorted(
        (item for item in filtered if item.get("evidence", {}).get("cnn_class") == "face"),
        key=lambda item: item["bbox"][1],
    )
    if len(faces) >= 2:
        data_page_top = faces[-1]["bbox"][1]
        filtered = [
            item
            for item in filtered
            if not (
                item.get("evidence", {}).get("cnn_class") == "name"
                and ((item["bbox"][1] + item["bbox"][3]) / 2) < data_page_top
            )
        ]
    return filtered


def _add_license_secondary_face(
    findings: list[dict], width: int, height: int
) -> list[dict]:
    """국내 운전면허증 우측의 작은 보조 얼굴 사진을 추가로 가린다.

    작은 홀로그램 얼굴은 현재 YOLO가 후보로 내지 않는 경우가 있다. 면허번호와
    주민번호·주소가 함께 검출되고 큰 얼굴이 하나뿐일 때만 국내 면허증 레이아웃으로
    판단해 우측 보조 사진 영역을 추가한다. 이미 두 얼굴이 잡혔거나 문서 유형이
    불확실하면 고정 좌표를 적용하지 않는다.
    """
    classes = [item.get("evidence", {}).get("cnn_class") for item in findings]
    required = {"license_number", "resident_number", "address"}
    if not required.issubset(classes) or classes.count("face") != 1:
        return findings

    confidence = min(
        item["confidence"]
        for item in findings
        if item.get("evidence", {}).get("cnn_class") in required
    )
    return [
        *findings,
        {
            "field": "id_photo",
            "value": "얼굴 사진",
            "start": 0,
            "end": 0,
            "confidence": round(confidence, 3),
            "bbox": (width * 0.81, height * 0.43, width * 0.98, height * 0.79),
            "page": 1,
            "reason": "운전면허증 우측 보조 얼굴 영역을 찾았다",
            "evidence": {
                "cnn_class": "face",
                "model": "infoguard_cnn_v1",
                "layout_rule": "kr_driver_license_secondary_face",
            },
        },
    ]


# 신분증에서만 나오는 확실한 근거들. address·name·signature·id_meta는 신분증이
# 아닌 문서(계약서 서명란, 인보이스의 주소·이름 문구)에도 흔해서 이것만으로는
# "신분증 사진이다"를 보장하지 못한다.
#
# face와 date_of_birth는 앵커에서 뺐다 — 자기소개서·이력서에도 지원자 증명사진과
# 생년월일이 흔히 함께 실려서(실측: 2026-09-17, 지원서 사진에서 얼굴이 앵커로
# 인정되는 바람에 "지원동기" 문단이 address 0.05 문턱을 넘어 같이 가려졌다),
# 이 둘은 신분증이 아닌 문서에서도 흔히 나와 "신분증이다"를 보장하지 못한다.
# 주민등록번호·면허번호·여권번호·MRZ는 신분증이 아니면 나올 이유가 없는
# 클래스라 이것들만 앵커로 쓴다.
_ANCHOR_CLASSES = {"resident_number", "license_number", "passport_number", "mrz"}


def _require_anchor_evidence(findings: list[dict]) -> list[dict]:
    """앵커 근거가 하나도 없으면 이 사진을 신분증으로 보지 않고 findings를 통째로 버린다.

    이 모델은 신분증 사진에만 맞춰 학습됐다(모듈 docstring 참고). 신분증이 아닌
    사진(인보이스, 스크린샷)에 돌리면 낮지 않은 확신도로도 가끔 잘못 반응한다
    (실측: 2026-09-17, 인보이스의 결제약관 문단이 "주소 영역"으로 0.519 확신도에
    잡힘 — 이 사진엔 앵커 클래스가 하나도 없었다). 앵커 하나 없이 나온 address·
    name·signature·id_meta 단독 탐지는 신분증의 일부라기보다 오탐일 가능성이
    훨씬 크므로, 화면에 "신분증 정보를 찾았다"고 보여주는 대신 아무것도 못 찾은
    것으로 취급한다 — 신분증 사진인데 앵커 부분만 잘려서 안 보이는 극단적인
    경우를 놓치더라도, 신분증이 아닌 사진을 신분증이라고 오판하는 쪽이 더 나쁘다.
    """
    has_anchor = any(
        item.get("evidence", {}).get("cnn_class") in _ANCHOR_CLASSES for item in findings
    )
    return findings if has_anchor else []


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
    image_width = image_height = 0
    for result in model.predict(
        path, conf=_INFERENCE_CONFIDENCE_FLOOR, iou=_NMS_IOU_THRESHOLD, verbose=False
    ):
        image_height, image_width = result.orig_shape
        names = result.names
        for box in result.boxes:
            class_name = names[int(box.cls)]
            confidence = float(box.conf)
            if confidence < _class_threshold(class_name):
                continue
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
                    "confidence": round(confidence, 3),
                    "bbox": (x0, y0, x1, y1),
                    "page": 1,
                    "reason": f"신분증 이미지에서 {label}을 찾았다",
                    "evidence": {"cnn_class": class_name, "model": "infoguard_cnn_v1"},
                }
            )
    findings = _filter_passport_incompatible(findings)
    findings = _add_license_secondary_face(findings, image_width, image_height)
    return _require_anchor_evidence(findings)
