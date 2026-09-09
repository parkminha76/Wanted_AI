# 9/9에 A와 합의해서 고정할 것. 이후 시그니처 변경 금지.


def filter_false_positive(text, context, risk_type) -> tuple[bool, float]:
    """이 값이 진짜 개인정보인가? 반환: (진짜면 True, 확신도 0~1)
    A의 모델이 준비되기 전에는 (True, 1.0)을 돌려준다 = 전부 통과."""
    return (True, 1.0)


_INJECTION_KEYWORDS = (
    "무시하고",
    "이전 지시",
    "시스템 프롬프트",
    "역할을 무시",
    "ignore previous",
    "system prompt",
)


def is_injection(sentence) -> tuple[bool, float]:
    """이 문장이 AI에게 내리는 명령인가? 반환: (명령이면 True, 확신도 0~1)
    A의 모델이 준비되기 전에는 키워드 목록으로 우선 판정한다."""
    lowered = sentence.lower()
    hit = any(keyword.lower() in lowered for keyword in _INJECTION_KEYWORDS)
    return (hit, 1.0 if hit else 0.0)
