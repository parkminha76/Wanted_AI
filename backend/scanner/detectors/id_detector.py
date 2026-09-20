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
import threading

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
_model_lock = threading.Lock()


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


def _drop_stray_low_confidence_addresses(findings: list[dict]) -> list[dict]:
    """확신도 높은 주소가 이미 있을 때, 그 블록과 동떨어진 낮은 주소 후보를 버린다.

    address만 0.05까지 받는 이유는 주민등록증 주소가 여러 줄로 쪼개져 뒷줄이
    0.062처럼 낮게 나오기 때문이다(_CLASS_CONFIDENCE_THRESHOLDS 주석). 그 뒷줄은
    **첫 줄 바로 아래에** 붙어 있다 — 가로 범위가 겹친다.

    그런데 운전면허증에서는 이 낮은 문턱이 엉뚱한 글자를 주소로 집어 온다
    (실측 2026-09-20: 좌상단 "2종보통 2종소형 원동기" 줄이 0.080으로 잡혔다.
    진짜 주소는 반대편에서 0.943으로 따로 잡혀 있었다). 면허 종별까지 까맣게
    칠해지면 사본이 못 쓰게 된다.

    그래서 확신도 높은 주소가 있을 때만, 그것과 가로로 겹치지 않는 낮은 후보를
    이어지는 줄이 아니라고 보고 버린다. 전부 낮게 잡힌 주민등록증에서는
    비교 기준이 없으므로 예전처럼 전부 남긴다.
    """
    addresses = [
        item for item in findings if item.get("evidence", {}).get("cnn_class") == "address"
    ]
    strong = [item for item in addresses if item["confidence"] >= CONFIDENCE_THRESHOLD]
    if not strong or len(addresses) == len(strong):
        return findings

    def overlaps_strong(item: dict) -> bool:
        left, _, right, _ = item["bbox"]
        return any(
            left < anchor["bbox"][2] and anchor["bbox"][0] < right for anchor in strong
        )

    return [
        item
        for item in findings
        if item.get("evidence", {}).get("cnn_class") != "address"
        or item["confidence"] >= CONFIDENCE_THRESHOLD
        or overlaps_strong(item)
    ]


# 주소 박스를 늘릴 때 기준으로 삼는 "한 줄짜리 글자 필드"들. 이들은 카드에서 주소와
# 같은 방향으로 인쇄되고 끝까지 또렷하게 잡히는 편이라 폭의 기준이 된다.
_TEXT_EXTENT_CLASSES = {"license_number", "resident_number", "passport_number", "name"}


def _widen_address_to_text_extent(findings: list[dict]) -> list[dict]:
    """주소 박스가 글자 끝까지 못 미칠 때, 같은 카드의 다른 글자 필드 끝선까지 늘린다.

    실측(2026-09-20, 합성 운전면허증 1040x720): 주소 "서울특별시 서대문구 통일로 97"이
    x=900 근처까지 인쇄돼 있는데 박스는 x=750에서 끊겨, 사본에서 "통일로 97"이 그대로
    읽혔다. 개인정보를 가리는 것이 본업이므로 이건 오탐보다 무거운 실패다.

    고정 픽셀이나 고정 비율로 늘리면 카드·해상도마다 과하거나 모자라므로, **같은 카드에서
    이미 잡힌 다른 글자 필드의 끝선**을 기준으로 삼는다. 면허번호·주민번호처럼 한 줄로
    또렷하게 잡히는 필드가 그 카드의 글자 영역이 어디까지인지 알려준다. 기준이 주소보다
    짧으면 아무것도 하지 않는다.

    글자가 가로로 흐르면(박스가 옆으로 길면) 오른쪽 끝을, 세로로 누운 신분증이면
    아래쪽 끝을 늘린다. 원래 길이만큼까지만 늘려서, 기준이 엉뚱하게 잡혔을 때
    카드 절반이 통째로 칠해지는 일은 막는다.
    """
    references = [
        item
        for item in findings
        if item.get("evidence", {}).get("cnn_class") in _TEXT_EXTENT_CLASSES
    ]
    if not references:
        return findings

    widened = []
    for item in findings:
        if item.get("evidence", {}).get("cnn_class") != "address":
            widened.append(item)
            continue

        left, top, right, bottom = item["bbox"]
        horizontal = (right - left) >= (bottom - top)
        if horizontal:
            target = max(ref["bbox"][2] for ref in references)
            limit = right + (right - left)
            new_right = min(max(right, target), limit)
            item = {**item, "bbox": (left, top, new_right, bottom)}
        else:
            target = max(ref["bbox"][3] for ref in references)
            limit = bottom + (bottom - top)
            new_bottom = min(max(bottom, target), limit)
            item = {**item, "bbox": (left, top, right, new_bottom)}
        widened.append(item)
    return widened


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

# 앵커가 없어도 얼굴만은 예외로 살려 둔다. 실측(2026-09-17): 이력서·지원서의
# 증명사진처럼 신분증이 아닌 문서에도 사람 얼굴 사진이 흔히 실리는데, 이것도
# 가려야 할 개인정보다. 문제가 됐던 오탐(인보이스 문단이 "주소"로, 자기소개서
# 문단이 "이름"으로 잡히는 것)은 전부 글자 영역을 잘못 짚는 클래스였지, 얼굴이
# 아니었다 — 얼굴 탐지는 "이 영역이 사람 얼굴처럼 생겼는가"라는 좁고 시각적으로
# 뚜렷한 판단이라 신분증 여부와 무관하게 믿을 만하다. 그래서 앵커가 없을 때도
# 얼굴만은 남기고, 앵커가 있어야 믿을 수 있는 나머지 클래스만 통째로 버린다.
_KEEP_WITHOUT_ANCHOR = {"face"}


def _require_anchor_evidence(findings: list[dict]) -> list[dict]:
    """앵커 근거가 없으면 얼굴을 뺀 나머지 findings를 버린다.

    이 모델은 신분증 사진에만 맞춰 학습됐다(모듈 docstring 참고). 신분증이 아닌
    사진(인보이스, 스크린샷)에 돌리면 낮지 않은 확신도로도 가끔 잘못 반응한다
    (실측: 2026-09-17, 인보이스의 결제약관 문단이 "주소 영역"으로 0.519 확신도에
    잡힘 — 이 사진엔 앵커 클래스가 하나도 없었다). 앵커 하나 없이 나온 address·
    name·signature·id_meta 단독 탐지는 신분증의 일부라기보다 오탐일 가능성이
    훨씬 크므로, 화면에 "신분증 정보를 찾았다"고 보여주는 대신 아무것도 못 찾은
    것으로 취급한다 — 신분증 사진인데 앵커 부분만 잘려서 안 보이는 극단적인
    경우를 놓치더라도, 신분증이 아닌 사진을 신분증이라고 오판하는 쪽이 더 나쁘다.
    얼굴(`_KEEP_WITHOUT_ANCHOR`)은 이 판단과 무관하게 항상 남긴다.
    """
    has_anchor = any(
        item.get("evidence", {}).get("cnn_class") in _ANCHOR_CLASSES for item in findings
    )
    if has_anchor:
        return findings
    return [
        item
        for item in findings
        if item.get("evidence", {}).get("cnn_class") in _KEEP_WITHOUT_ANCHOR
    ]


def _get_model():
    """첫 호출 때 한 번만 로드하고 캐싱한다. import 시점에 불러오면 모델 파일이
    없는 환경에서 `import id_detector` 자체가 실패해 scan.py 전체가 멎는다.

    락으로 감싸는 이유는 ner.py의 `_get_pipeline` 주석 참고 — 동시 요청이
    콜드 스타트 직후 이 모델을 여러 번 동시에 새로 불러오는 걸 막는다."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from ultralytics import YOLO

                _model = YOLO(MODEL_PATH)
    return _model


def _has_anchor(findings: list[dict]) -> bool:
    """신분증에만 나오는 클래스를 하나라도 찾았는가(_ANCHOR_CLASSES 참고)."""
    return any(
        item.get("evidence", {}).get("cnn_class") in _ANCHOR_CLASSES for item in findings
    )


def _detect_rotated(path: str) -> list[dict] | None:
    """사진 속 신분증이 누워 있을 때를 위해 90/180/270도로 돌려 다시 본다.

    이 모델은 바로 세운 신분증으로 학습했다. 실측(2026-09-20, 세로로 세워 찍은
    주민등록증 견본): 원본 방향에서는 얼굴 하나(0.252)만 잡혀 앵커가 없었고,
    반시계 90도로 돌리자 주민등록번호·이름·발급일자까지 6건이 잡혔다. 앵커가 없으면
    scan.py가 "신분증이 아니다"로 보고 거부하므로, 돌리지 않으면 멀쩡한 신분증이
    반려된다.

    앵커가 없을 때만 돈다 — 바로 세운 사진까지 매번 네 배 비용을 물지 않는다.
    text_ocr.py가 OCR에서 같은 일을 하며 쓰는 규칙을 그대로 따른다.

    좌표는 돌린 그림 기준으로 나오므로 원본 좌표로 되돌려서 내보낸다. 마스킹은
    원본 파일 위에 그리기 때문에, 이걸 빼먹으면 엉뚱한 자리가 가려진다.
    """
    import cv2
    import numpy as np

    # text_ocr의 좌표 역매핑을 그대로 쓴다. 같은 회전 규칙(np.rot90의 k)을 두 군데서
    # 따로 구현하면 한쪽만 틀어져도 마스킹이 엉뚱한 자리를 가린다.
    from backend.scanner.detectors.text_ocr import _map_bbox_from_rotated

    # YOLO가 경로를 받을 때 cv2로 읽어 BGR로 다루므로 여기서도 cv2로 읽는다.
    # PIL로 읽어 RGB로 넘기면 색 순서가 뒤바뀌어 탐지 품질이 달라진다.
    image = cv2.imread(path)
    if image is None:
        return None
    orig_h, orig_w = float(image.shape[0]), float(image.shape[1])

    for k in (1, 2, 3):
        # np.rot90은 음수 stride를 가진 뷰를 돌려준다. ultralytics는 연속 배열을
        # 기대하므로 복사해서 넘긴다.
        rotated = np.ascontiguousarray(np.rot90(image, k=k))
        found, width, height = _detect_frame(rotated)
        found = _filter_passport_incompatible(found)
        found = _drop_stray_low_confidence_addresses(found)
        found = _widen_address_to_text_extent(found)
        found = _add_license_secondary_face(found, width, height)
        if _has_anchor(found):
            for item in found:
                item["bbox"] = _map_bbox_from_rotated(item["bbox"], k, orig_w, orig_h)
                item["evidence"]["rotated_k"] = k
            return found
    return None


def _detect_frame(source) -> tuple[list[dict], int, int]:
    """한 방향에서 추론한다. source는 파일 경로 또는 BGR 배열이다.

    반환값은 (findings, 이미지 너비, 이미지 높이)다. 너비·높이는
    `_add_license_secondary_face`가 쓰는데, 돌린 그림에서는 원본과 뒤바뀌므로
    그 그림 기준 값을 그대로 돌려줘야 한다.
    """
    model = _get_model()
    findings: list[dict] = []
    image_width = image_height = 0
    for result in model.predict(
        source, conf=_INFERENCE_CONFIDENCE_FLOOR, iou=_NMS_IOU_THRESHOLD, verbose=False
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
    return findings, image_width, image_height


def detect(path: str) -> list[dict]:
    """이미지 1장에서 개인정보 영역을 찾는다.

    rules.py와 같은 형식에 좌표를 더해 돌려준다:
        [{field, value, start, end, confidence, bbox, page, reason, evidence}, ...]

    start/end는 0으로 둔다 — 이미지에는 문자 오프셋이라는 개념이 없다. 마스킹은
    bbox로 한다. 그래서 scan.py의 _dedupe는 이 결과에 아무 일도 하지 못한다
    (구간 겹침을 start/end로 판정하는데 둘 다 0이라 항상 "안 겹침"이 된다).
    겹친 박스를 합치는 일은 NMS가 책임진다.

    바로 세운 방향에서 앵커를 못 찾으면 돌려서 한 번 더 본다(`_detect_rotated`).
    """
    findings, image_width, image_height = _detect_frame(path)
    findings = _filter_passport_incompatible(findings)
    findings = _drop_stray_low_confidence_addresses(findings)
    findings = _widen_address_to_text_extent(findings)
    findings = _add_license_secondary_face(findings, image_width, image_height)

    if not _has_anchor(findings):
        rotated = _detect_rotated(path)
        if rotated is not None:
            findings = rotated

    return _require_anchor_evidence(findings)
