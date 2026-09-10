"""
DB에 저장되는 고정 코드 정의
============================

Finding.reason, ScanResult.error를 DB에 저장할 때 자유 텍스트를 그대로 쓰지
않고 이 파일에 정의된 고정 코드로 변환한다. 이유: 자유 텍스트 문자열 안에는
개발자가 실수로(또는 나중에 로직이 바뀌면서) 원문 조각이 섞여 들어갈 여지가
항상 있다. 고정된 코드 집합만 허용하면 그 여지 자체가 없어진다.

evidence도 마찬가지로 화이트리스트 방식으로 바꾼다 — "이 키들은 금지"가
아니라 "이 키들만 허용"이어야, 나중에 새로운 키가 실수로 추가돼도 기본값이
안전(거부) 쪽이 된다.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# ScanResult.error 코드
# ---------------------------------------------------------------------------

ERROR_CODES = {
    "parse_failed",       # 파일 파싱 자체가 실패
    "unsupported_format", # 지원 안 하는 파일 형식
    "file_too_large",
    "timeout",
    "unknown",
}


def derive_error_code(error_message: str | None) -> str | None:
    """예외 메시지(자유 텍스트, 파일 경로/내용이 섞여 있을 수 있음)를 절대 그대로
    저장하지 않고, 알려진 패턴에 매칭해 고정 코드로만 변환한다.
    """
    if not error_message:
        return None

    msg = error_message.lower()
    if "pars" in msg or "파싱" in error_message:  # parse/parsing 둘 다 매칭
        return "parse_failed"
    if "format" in msg or "형식" in error_message or "unsupported" in msg:
        return "unsupported_format"
    if "size" in msg or "크기" in error_message or "large" in msg:
        return "file_too_large"
    if "timeout" in msg or "시간 초과" in error_message:
        return "timeout"
    return "unknown"


# ---------------------------------------------------------------------------
# Finding.reason 코드 — source/evidence 조합으로 결정한다.
# ---------------------------------------------------------------------------

REASON_CODES = {
    "format_match",              # 정규식 형식만 일치 (체크섬 없는 필드)
    "checksum_pass",
    "checksum_fail",
    "ner_match",
    "classifier_high_confidence",
    "classifier_low_confidence",
    "hidden_text_detected",      # 흰 글씨/폰트0/제로폭 등 (구체적 방식은 evidence.render_mode 등으로만)
    "injection_pattern_match",
    "cnn_detection",
}

_CLASSIFIER_CONFIDENCE_THRESHOLD = 0.7


def derive_reason_code(risk_type: str, source: str, confidence: float, evidence: dict) -> str:
    """Finding.type/source/confidence/evidence(화이트리스트 통과 후)를 보고
    고정된 reason 코드를 정한다. schemas.py의 자유 텍스트 reason은 이 함수의
    입력으로 쓰지 않는다 — 자유 텍스트를 파싱해서 코드를 유추하는 건 깨지기
    쉽고, 애초에 원문이 섞여 들어올 통로를 하나 더 만드는 셈이라 피한다.

    type을 가장 먼저 확인하는 이유: source만 보면 injection 여부가 사라진다.
    예를 들어 인젝션이 문맥 분류기로 잡히면 source="classifier"인데, type을
    안 보고 source만으로 분기하면 일반 PII 오탐 분류와 구분이 안 되는
    classifier_high_confidence로 뭉개진다. type="injection"이면 무조건
    injection_pattern_match를 우선 반환해서 이 구분을 보존한다.
    """
    if risk_type == "injection":
        return "injection_pattern_match"
    if source == "rule":
        checksum = evidence.get("checksum")
        if checksum == "pass":
            return "checksum_pass"
        if checksum == "fail":
            return "checksum_fail"
        return "format_match"
    if source == "ner":
        return "ner_match"
    if source == "classifier":
        return (
            "classifier_high_confidence"
            if confidence >= _CLASSIFIER_CONFIDENCE_THRESHOLD
            else "classifier_low_confidence"
        )
    if source == "format":
        return "hidden_text_detected"
    if source == "cnn":
        return "cnn_detection"
    return "format_match"  # 알 수 없는 source는 가장 보수적인 코드로


# ---------------------------------------------------------------------------
# Finding.evidence 화이트리스트 — 허용된 키와 값 형식만 통과시킨다.
# ---------------------------------------------------------------------------

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_KNOWN_MODELS = {"fp_filter_v1", "injection_classifier_v1", "infoguard_cnn_v1"}


def _valid_font_size(v) -> bool:
    return isinstance(v, (int, float)) and 0 <= v <= 200


def _valid_color(v) -> bool:
    return isinstance(v, str) and bool(_HEX_COLOR_RE.match(v))


def _valid_render_mode(v) -> bool:
    return isinstance(v, int) and 0 <= v <= 7  # PDF 텍스트 렌더 모드는 0~7 범위


def _valid_checksum(v) -> bool:
    return v in ("pass", "fail", "not_available")  # 원문 해시 금지, 결과값만


def _valid_probability(v) -> bool:
    return isinstance(v, (int, float)) and 0.0 <= v <= 1.0


def _valid_model(v) -> bool:
    return isinstance(v, str) and v in _KNOWN_MODELS


def _valid_opacity(v) -> bool:
    return isinstance(v, (int, float)) and 0.0 <= v <= 1.0  # 0.0 = 완전 투명


def _valid_intent_score(v) -> bool:
    return isinstance(v, (int, float)) and 0.0 <= v <= 1.0


# hidden_reason은 "어떤 방식으로 숨겨졌나"(수법 분류, 통계용)이고,
# intent_score는 "그게 얼마나 의도적으로 보이나"(0.0~1.0, 위험도 반영용)다.
# 이 둘을 하나로 합치지 않는 이유: 같은 "흰 글씨" 수법이어도 진짜 숨기려고
# 한 것과 편집 중 우연히 남은 서식 잔재는 위험도가 다르다. hidden_reason만
# 있으면 "무슨 수법인지"는 알아도 "그게 위험한 건지"는 못 나타낸다.
#
# 목록은 B의 실제 탐지 로직 기준(2026-09-10 확정)으로 맞춤. render_mode/
# opacity/font_size/color는 evidence의 동명 키(수치)와 짝을 이루는
# "이 값으로 탐지했다"는 표시이고, 나머지는 그 네 개로 깔끔하게 안 잡히는
# 케이스(문서 형식별 특수 서식)를 위한 것이다. vanish/web_hidden/
# blank_format/invisible_a/invisible_b는 정확한 정의를 B에게 확인 중 —
# 일단 값 자체는 통과시켜두고 의미는 나중에 문서화한다.
#
# intent_score를 DB에 저장하는 이유는 XAI 근거 표시와 통계용이고, 실제
# 위험점수 계산에 반영하려면 B가 Finding을 만들 때 이 값이 높을수록
# Finding.confidence도 높게 잡아줘야 한다 — compute_risk_score()가
# weight x confidence x log(count) 구조라 confidence를 통해서만 점수에
# 반영되고, evidence 내부 값을 직접 읽어서 계산하지는 않는다.
#
# (2026-09-10) B는 confidence를 intent_score 그대로 쓰지 않고
# "intent_score x 판독 확신도"로 분리해서 계산하기로 함 — 예: 흰 글씨는
# 확실히 찾았지만(intent_score=0.9) 배경색을 못 읽어 흰 배경인지 확신
# 못하면(판독 확신도=0.8) confidence=0.72. 이건 B가 Finding 만들 때
# 자체적으로 계산하는 로직이라 evidence 화이트리스트나 스키마 변경이
# 필요 없다 — confidence는 원래 Finding의 평범한 float 필드다.
_HIDDEN_REASONS = {
    "render_mode",         # PDF 렌더 모드로 탐지 (evidence.render_mode와 짝)
    "opacity",             # 투명도로 탐지 (evidence.opacity와 짝)
    "font_size",           # 폰트 크기로 탐지 (evidence.font_size와 짝)
    "color",               # 글자색=배경색으로 탐지, 배경색 확인됨 (evidence.color/bg와 짝)
    "color_unknown_bg",    # 글자색은 의심스러운데 배경색을 확인 못함
    "vanish",              # 문서 서식의 "숨김(vanish)" 속성 — 정의 확인 중
    "web_hidden",          # HTML/CSS 숨김 속성 (display:none 등) — 정의 확인 중
    "blank_format",        # 빈 것처럼 보이게 만든 서식 — 정의 확인 중
    "sheet_very_hidden",   # 엑셀 "매우 숨김(veryHidden)" 시트
    "sheet_hidden",        # 엑셀 일반 숨김 시트
    "row_hidden",          # 숨긴 행
    "col_hidden",          # 숨긴 열
    "invisible_a",         # 비가시 텍스트 유형 A — 정의 확인 중
    "invisible_b",         # 비가시 텍스트 유형 B — 정의 확인 중
    "other",               # 위에 없는 새 숨김 방식 발견 시 임시로 사용
}


def _valid_hidden_reason(v) -> bool:
    return isinstance(v, str) and v in _HIDDEN_REASONS


# 키 -> 값 검증 함수. 여기 없는 키는 전부 버려진다 (화이트리스트).
_EVIDENCE_VALIDATORS = {
    "font_size": _valid_font_size,
    "color": _valid_color,
    "bg": _valid_color,
    "render_mode": _valid_render_mode,
    "checksum": _valid_checksum,
    "prob_positive": _valid_probability,
    "model": _valid_model,
    "opacity": _valid_opacity,
    "hidden_reason": _valid_hidden_reason,
    "intent_score": _valid_intent_score,
}


def sanitize_evidence(evidence: dict) -> dict:
    """허용된 키+유효한 값만 통과. 나머지는 조용히 버린다(에러 대신 드롭 —
    분류기가 실험적으로 새 키를 넣었다가 파이프라인이 죽는 것보다, 그 값이
    누락되는 게 안전 쪽 실패다).

    이 함수는 converters.py에서 명시적으로도 호출되지만, tables.py의
    FindingRow.evidence에 @validates가 걸려 있어 어떤 경로로 값이 들어오든
    (마이그레이션 스크립트, 다른 API 등) 반드시 이 함수를 한 번 더 통과한다 —
    이중 방어.
    """
    result = {}
    for key, validator in _EVIDENCE_VALIDATORS.items():
        if key in evidence and validator(evidence[key]):
            result[key] = evidence[key]
    return result


# ---------------------------------------------------------------------------
# RiskType 화이트리스트 — findings.type, scan_results.finding_counts의 키,
# training_events.detected_field가 전부 이 목록 안의 값만 갖도록 강제한다.
# ---------------------------------------------------------------------------

def get_valid_risk_types() -> frozenset[str]:
    """backend/shared/schema.py의 RiskType Literal에서 허용 값 목록을 직접
    추출한다. 여기서 값을 하드코딩하지 않는 이유: RiskType이 늘어날 때마다
    이 파일도 같이 고쳐야 한다면 둘이 어긋날 여지가 생긴다. Literal의 실제
    정의를 매번 조회하면 어긋날 수가 없다.
    """
    import typing
    from backend.shared.schema import RiskType

    return frozenset(typing.get_args(RiskType))


def validate_risk_type(value: str | None) -> bool:
    """None(미탐지)은 허용, 값이 있으면 RiskType 목록에 있는 것만 허용."""
    if value is None:
        return True
    return value in get_valid_risk_types()