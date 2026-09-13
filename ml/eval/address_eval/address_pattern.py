"""B의 rules.py에 전달하기 전 검증하는 상세 주소 정규식 프로토타입."""

from __future__ import annotations

import re


ADMIN_PREFIX = (
    r"(?:(?:[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구))\s+){0,4}"
)
ROAD_NAME = r"[가-힣A-Za-z0-9·]+(?:대로|로|길)(?:\d+번길)?"
ROAD_BASE = rf"{ADMIN_PREFIX}{ROAD_NAME}\s+\d+(?:-\d+)?"
JIBUN_NAME = r"[가-힣A-Za-z0-9·]+(?:동|가|읍|면|리)"
JIBUN_BASE = rf"{ADMIN_PREFIX}{JIBUN_NAME}\s+(?:산\s*)?\d+(?:-\d+)?"
BUILDING_NAME = r"[가-힣A-Za-z0-9·]+(?:아파트|빌라|오피스텔|타워|주택)"
UNIT_DETAIL = (
    rf"(?:\s+{BUILDING_NAME})?"
    r"(?:\s+제?\d+동)?"
    r"(?:\s+\d+층)?"
    r"(?:\s+\d+호)?"
)

ADDRESS_PATTERN = re.compile(rf"(?:{ROAD_BASE}|{JIBUN_BASE}){UNIT_DETAIL}")


def find_address_spans(text: str) -> list[tuple[int, int]]:
    """상세 주소로 판단한 원문 기준 (start, end) 목록을 반환한다."""
    return [(match.start(), match.end()) for match in ADDRESS_PATTERN.finditer(text)]

