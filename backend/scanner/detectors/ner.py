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

import re

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


def _iter_segment_chunks(text: str, segment_start: int, segment_end: int):
    """탭·줄바꿈으로 분리된 한 구간을 모델 입력 크기에 맞춰 나눈다."""
    start = segment_start
    while start < segment_end:
        end = min(start + _MAX_CHARS_PER_CHUNK, segment_end)
        if end < segment_end:
            boundary = max(text.rfind(c, start, end) for c in ".!?")
            if boundary <= start:
                boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary + 1
        chunk = text[start:end]
        if chunk.strip():
            yield chunk, start
        start = end


def _iter_chunks(text: str):
    """모델 입력 한도를 넘지 않게 자르고, 각 조각의 원문 시작 위치도 같이 돌려준다.

    탭과 줄바꿈은 먼저 강제 경계로 취급한다. XLSX의 서로 다른 셀은 파서에서 탭으로
    이어지므로 한 번에 모델에 넣으면 이름과 다음 셀을 하나의 인물명으로 합칠 수 있다.
    셀·문단을 넘는 NER 결과는 마스킹 범위까지 넓혀 실제 내용을 지우므로 입력 단계에서
    차단한다.
    """
    for segment in re.finditer(r"[^\t\r\n]+", text):
        yield from _iter_segment_chunks(text, segment.start(), segment.end())


_REPEAT_MIN_LENGTH = {"person": 3, "org": 4}

_ORG_SUFFIX_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z0-9])"
    r"(?:주식회사\s+)?[가-힣A-Za-z0-9·]{2,}"
    r"\s+(?:솔루션|테크놀로지|테크|글로벌|그룹)"
    r"(?:\s+주식회사)?(?![가-힣A-Za-z0-9])"
)


def _expand_repeated_entities(text: str, findings: list[dict]) -> list[dict]:
    """확실히 잡힌 이름·회사명의 동일 문서 내 반복 표기를 함께 반환한다."""
    expanded = list(findings)
    seeds: dict[tuple[str, str], float] = {}
    for item in findings:
        risk_type = item["field"]
        value = item["value"].strip()
        if len(value) < _REPEAT_MIN_LENGTH.get(risk_type, 10**9):
            continue
        key = (risk_type, value)
        seeds[key] = max(seeds.get(key, 0.0), float(item["confidence"]))

    for (risk_type, value), confidence in seeds.items():
        for match in re.finditer(re.escape(value), text):
            expanded.append(
                {
                    "field": risk_type,
                    "value": text[match.start() : match.end()],
                    "start": match.start(),
                    "end": match.end(),
                    "confidence": round(confidence, 3),
                }
            )

    for match in _ORG_SUFFIX_PATTERN.finditer(text):
        expanded.append(
            {
                "field": "org",
                "value": match.group(),
                "start": match.start(),
                "end": match.end(),
                "confidence": 0.85,
            }
        )
    return expanded


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

            # 모델이 표의 "서명" 열 제목까지 인물명으로 합치는 경우가 있다.
            # 실제 이름 뒤의 UI/문서 라벨은 마스킹하지 않도록 경계를 되돌린다.
            if risk_type == "person":
                for suffix in (" 서명", " 날인"):
                    if text[start:end].endswith(suffix):
                        end -= len(suffix)
                        break

            # 영문 토큰 중간에서 시작·끝난 조직명(InfoGuard -> foGuard)은 모델의
            # 토큰 경계 오류다. 한 글자 조직명 "주"도 회사명으로 쓰지 않는다.
            if risk_type == "org":
                # 표의 필드명까지 조직명으로 합치는 결과("수행사 주식회사")에서는
                # 발주사·수행사 같은 라벨을 남기고 실제 조직 부분만 사용한다.
                leading_label = re.match(
                    r"(?:발주사|수행사|공급사|협력사|회사명|업체명|조직명)\s+",
                    text[start:end],
                )
                if leading_label:
                    start += leading_label.end()
                if end - start < 2:
                    continue
                if start > 0 and text[start - 1].isalnum() and text[start].isalnum():
                    continue
                if end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
                    continue

            if end <= start:
                continue
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
    # "주식회사"와 바로 뒤 회사명이 별도 개체로 나온 경우 한 범위로 합친다.
    # 공백 외 문자가 사이에 있으면 서로 다른 조직일 수 있으므로 합치지 않는다.
    merged = []
    for item in sorted(findings, key=lambda finding: finding["start"]):
        if (
            merged
            and item["field"] == "org"
            and merged[-1]["field"] == "org"
            and not text[merged[-1]["end"] : item["start"]].strip()
            and "\n" not in text[merged[-1]["end"] : item["start"]]
        ):
            merged[-1]["end"] = item["end"]
            merged[-1]["value"] = text[merged[-1]["start"] : item["end"]]
            merged[-1]["confidence"] = max(merged[-1]["confidence"], item["confidence"])
        else:
            merged.append(dict(item))
    return _expand_repeated_entities(text, merged)
