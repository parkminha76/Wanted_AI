from __future__ import annotations

import re


_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("rrn", "[RRN]", re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)")),
    (
        "card",
        "[CARD]",
        re.compile(r"(?<!\d)(?:\d{4}[- ]?){3}\d{4}(?!\d)"),
    ),
    (
        "account",
        "[ACCOUNT]",
        re.compile(r"(?<!\d)\d{3}-\d{3}-\d{6}(?!\d)"),
    ),
    (
        "phone",
        "[PHONE]",
        re.compile(r"(?<!\d)01[016789]-\d{3,4}-\d{4}(?!\d)"),
    ),
    (
        "email",
        "[EMAIL]",
        re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])"),
    ),
)


def sanitize_training_text(text: str) -> dict[str, str | list[str]]:
    """외부 AI 호출 전에 명확한 개인정보 형식만 치환한다.

    이름, 조직명, 일반 장소처럼 오탐 가능성이 높은 NER 항목은 다루지 않는다.
    반환 후 호출자는 원문을 보관하지 않고 sanitized_text만 사용해야 한다.
    """
    sanitized_text = text
    shared_fields: list[str] = []

    for field, replacement, pattern in _PATTERNS:
        sanitized_text, count = pattern.subn(replacement, sanitized_text)
        if count:
            shared_fields.append(field)

    return {
        "sanitized_text": sanitized_text,
        "shared_fields": shared_fields,
    }
