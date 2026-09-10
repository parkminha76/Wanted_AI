"""한국어 NER(개체명 인식)로 이름/주소/조직명을 잡는다. 정규식으로는 못 잡는,
형식이 없는 값을 담당한다(형식이 고정된 값은 rules.py가 담당).

모델 선정 (ner_benchmark.py로 4개 후보를 실측 비교했다 — 2026-09-09)
----------------------------------------------------------------------
선택: Leo97/KoELECTRA-small-v3-modu-ner

    모델                                 로딩      추론/문장   커버리지
    Leo97/KoELECTRA-small (56MB)        1.65초    11.3ms     100%
    KPF/KPF-bert-ner (455MB)            1.85초    51.5ms     100%
    monologg/koelectra-base             1.86초    47.7ms     100%
    vmaca123/korean-pii-ner-v3 (1.3GB)  29.72초   197.2ms     94.7%

- 네 후보 중 가장 가볍고(56MB) 가장 빠르다. "10/5까지 배포 링크가 살아있어야
  한다"는 조건에서, 무거운 모델은 로딩 자체가 배포 리스크다.
- 라벨이 모두의말뭉치 표준 태그셋(B-PS/I-PS 등)으로 이미 정리되어 있어 바로 쓸 수
  있다.
- KPF-bert-ner는 후보에서 제외했다: HuggingFace에 올라간 config.json의 라벨이
  LABEL_0~LABEL_299로 전부 익명 처리되어 있다. 실제 인물/기관/지명이 몇 번
  라벨인지 매핑표를 별도 GitHub 저장소에서 구해와야 쓸 수 있는데, 로딩시간보다
  이쪽이 더 큰 리스크라 판단했다.
- koelectra-base-v3-naver-ner는 라벨은 정리되어 있지만 base 모델이라 무겁다.
  small 모델의 정확도가 부족하면 다음 후보로 바꿔 끼운다 — 모델 이름은 아래
  MODEL_NAME 상수 하나만 바꾸면 된다.
- korean-pii-ner-v3는 라벨이 NAME/ADDRESS/ORG로 우리 필요와 정확히 맞아떨어져
  기대했지만, 실측에서 세 지표 모두 꼴찌라 탈락했다(위 표 참고).

모델 로딩은 첫 detect() 호출 때 한 번만 하고 캐싱한다. import 시점에 바로
불러오면, 모델이 아직 캐시되지 않았거나 네트워크가 막힌 환경에서 `import ner`
자체가 실패해 scan.py 전체가 멎는다.

긴 문서는 반드시 잘라서 넣는다. 이 모델의 입력 한도는 512토큰인데, 넘겨도
예외가 나지 않고 경고만 찍힌 뒤 뒷부분이 조용히 버려진다. 실측으로 4,700자
문서(2,305토큰)에서 앞쪽 이름 하나만 잡히고 중간·뒤쪽 이름 둘을 놓쳤다.
고객 명단 같은 문서에서 이건 "앞의 몇 명만 마스킹하고 안전한 사본이라고
내보내는" 사고가 된다.
"""

from __future__ import annotations

MODEL_NAME = "Leo97/KoELECTRA-small-v3-modu-ner"

# 한 번에 모델에 넣을 최대 글자 수. 한국어는 대략 2글자당 1토큰이라 400자면
# 200토큰 안팎으로, 512 한도에 충분한 여유가 있다.
_MAX_CHARS_PER_CHUNK = 400

# 모두의말뭉치 NER 태그 -> schema.RiskType. 개인정보와 무관한 태그(날짜/수량/
# 이론/인공물 등)는 매핑에서 빼서 자동으로 버려지게 한다.
_TAG_TO_RISK_TYPE: dict[str, str] = {
    "PS": "person",
    "LC": "address",
    "OG": "org",
}

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline

        _pipeline = pipeline(
            "token-classification",
            model=MODEL_NAME,
            aggregation_strategy="simple",
        )
    return _pipeline


def _iter_chunks(text: str):
    """모델 입력 한도를 넘지 않게 자르고, 각 조각의 원문 시작 위치도 같이 돌려준다.
    문장 경계(.!?/줄바꿈)에서 끊고, 그런 경계가 없으면 공백에서 끊는다 —
    단어 중간에서 자르면 그 자리의 개체명을 놓친다."""
    start, length = 0, len(text)
    while start < length:
        end = min(start + _MAX_CHARS_PER_CHUNK, length)
        if end < length:
            boundary = max(text.rfind(c, start, end) for c in ".!?\n")
            if boundary <= start:
                boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary + 1
        chunk = text[start:end]
        if chunk.strip():
            yield chunk, start
        start = end


def detect(text: str) -> list[dict]:
    """rules.py와 같은 형식으로 반환한다: [{field, value, start, end, confidence}, ...]"""
    pipe = _get_pipeline()
    findings = []
    for chunk, offset in _iter_chunks(text):
        for entity in pipe(chunk):
            risk_type = _TAG_TO_RISK_TYPE.get(entity["entity_group"])
            if risk_type is None:
                continue
            start = offset + entity["start"]
            end = offset + entity["end"]
            findings.append(
                {
                    "field": risk_type,
                    # entity["word"] 대신 원문에서 잘라 쓴다. 토크나이저가 복원한
                    # 문자열은 원문과 미세하게 달라질 수 있는데, 그러면 마스킹이
                    # 그 값을 원문에서 못 찾는다. 오프셋과 값이 항상 일치해야 한다.
                    "value": text[start:end],
                    "start": start,
                    "end": end,
                    "confidence": round(float(entity["score"]), 3),
                }
            )
    return findings
