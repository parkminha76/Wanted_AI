"""정규식으로 형식이 고정된 필드를 찾고, 체크섬으로 오탐을 걸러낸다.

parse.py의 문서 파싱 완성을 기다릴 필요 없이 raw_text만 있으면 동작한다.
같은 자릿수의 무작위 숫자열(주문번호, 사번 등)을 개인정보로 오인하지 않도록,
형식이 맞아도 체크섬이 틀리면 후보에서 제외한다.
"""

import re

RESIDENT_REGISTRATION_NUMBER_PATTERN = re.compile(r"\d{6}[-\s]?[1-8]\d{6}")
CARD_NUMBER_PATTERN = re.compile(r"(?:\d[ -]?){13,19}\d")


def _verify_resident_registration_number(digits: str) -> bool:
    """주민등록번호 뒤 7자리 중 마지막 한 자리는 앞 12자리로 계산되는 검증 숫자다."""
    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    total = sum(int(d) * w for d, w in zip(digits[:12], weights))
    check_digit = (11 - (total % 11)) % 10
    return check_digit == int(digits[12])


def _verify_luhn(digits: str) -> bool:
    """카드번호 표준 체크섬(Luhn 알고리즘): 뒤에서부터 한 자리씩 건너뛰며 2배."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def find_resident_registration_numbers(text: str) -> list[dict]:
    """형식(6자리-성별숫자7자리)과 체크섬을 모두 통과한 주민등록번호 후보만 반환한다."""
    matches = []
    for m in RESIDENT_REGISTRATION_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) != 13:
            continue
        if not _verify_resident_registration_number(digits):
            continue
        matches.append(
            {
                "field": "resident_registration_number",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
            }
        )
    return matches


def find_card_numbers(text: str) -> list[dict]:
    """13~19자리 숫자열 중 Luhn 체크섬을 통과한 카드번호 후보만 반환한다."""
    matches = []
    for m in CARD_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        if not (13 <= len(digits) <= 19):
            continue
        if not _verify_luhn(digits):
            continue
        matches.append(
            {
                "field": "card_number",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
            }
        )
    return matches


def find_all(text: str) -> list[dict]:
    """체크섬 검증이 있는 필드들을 모두 돌려서 하나의 목록으로 합친다."""
    return find_resident_registration_numbers(text) + find_card_numbers(text)
