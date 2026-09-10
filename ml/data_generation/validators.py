"""
신분증 합성 데이터 필드 검증
============================

custom_generator.py가 만든 값(운전면허번호/외국인등록번호/사업자등록번호/계좌번호)이
실제 유효한 형식인지 검증한다. "AI가 짠 생성 코드라도 그대로 신뢰하지 않는다"는
원칙에 따라, 체크섬이 존재하는 필드는 반드시 이 함수를 통과시킨 뒤에 학습 데이터로
쓴다.

담당: A (custom_generator.py와 세트로 관리)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 검증 가능 — 공개된 체크섬 알고리즘이 있는 것
# ---------------------------------------------------------------------------


def validate_biz_reg(number: str) -> bool:
    """사업자등록번호 체크섬 검증.

    형식: XXX-XX-XXXXX (10자리, 마지막 자리가 체크섬)
    """
    digits_str = number.replace("-", "")
    if not digits_str.isdigit() or len(digits_str) != 10:
        return False

    digits = [int(c) for c in digits_str]
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    total = sum(d * w for d, w in zip(digits[:9], weights))
    total += (digits[8] * 5) // 10  # 9번째 자리를 5배 한 뒤 몫만 더하는 표준 알고리즘
    check = (10 - total % 10) % 10
    return check == digits[9]


def validate_foreign_reg(number: str) -> bool:
    """외국인등록번호 체크섬 검증.

    형식: XXXXXX-XXXXXXX (13자리). 주민등록번호와 체크섬 로직은 동일하고,
    뒷자리 7번째 숫자만 5/6/7/8(외국인 구분 코드)이어야 한다.
    """
    digits_str = number.replace("-", "")
    if not digits_str.isdigit() or len(digits_str) != 13:
        return False

    digits = [int(c) for c in digits_str]
    if digits[6] not in (5, 6, 7, 8):
        return False

    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    total = sum(d * w for d, w in zip(digits[:12], weights))
    check = (11 - total % 11) % 10
    return check == digits[12]


def validate_rrn(number: str) -> bool:
    """주민등록번호 체크섬 검증.

    형식: XXXXXX-XXXXXXX (13자리). 외국인등록번호와 체크섬 알고리즘은 동일하고,
    뒷자리 7번째 숫자가 내국인 구분 코드(1/2/3/4)여야 한다는 점만 다르다.
    (1800년대생 9/0 코드는 실사용 빈도가 극히 낮아 학습 데이터 목적상 제외한다.)
    """
    digits_str = number.replace("-", "")
    if not digits_str.isdigit() or len(digits_str) != 13:
        return False

    digits = [int(c) for c in digits_str]
    if digits[6] not in (1, 2, 3, 4):
        return False

    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    total = sum(d * w for d, w in zip(digits[:12], weights))
    check = (11 - total % 11) % 10
    return check == digits[12]


def validate_card_luhn(number: str) -> bool:
    """카드번호 체크섬 검증 (Luhn 알고리즘 — ISO/IEC 7812 국제 공개 표준).

    계좌번호와 달리 카드번호는 은행이 아니라 카드 브랜드(Visa/Mastercard 등)가
    공통으로 쓰는 체크섬이 있다. rrn/foreign_reg/biz_reg와 같은 급의 "검증
    가능" 필드로 분류한다.
    """
    digits_str = number.replace("-", "").replace(" ", "")
    if not digits_str.isdigit() or not (12 <= len(digits_str) <= 19):
        return False  # 카드번호는 브랜드별로 12~19자리까지 다양함

    digits = [int(c) for c in digits_str]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


# ---------------------------------------------------------------------------
# 검증 불가능 — 공개된 체크섬/검증 알고리즘이 없는 것
# ---------------------------------------------------------------------------
#
# 운전면허번호: XX-XX-XXXXXX-XX (지역코드+연도+일련번호+검증번호) 구조지만,
#   뒤 2자리 검증번호 산출 로직은 도로교통공단 내부 알고리즘이라 공개돼 있지 않다.
#   실제 발급 시스템에 검증받을 일이 없는 학습용 합성 데이터이므로,
#   여기서는 "형식(자릿수, 유효 지역코드 범위)만 맞으면 통과"로 처리한다.
#
# 여권번호(화면에 보이는 문자열, 예: M12345678): 그 자체엔 체크 디지트가 없다.
#   체크 디지트는 여권 하단 MRZ(기계판독영역) 문자열 안에만 별도로 존재하고,
#   화면에 인쇄된 여권번호 자체는 "영문 1자 + 숫자 8자리" 형식만 검증 가능하다.
#   MRZ 전체를 검증하고 싶으면 아래 validate_passport_mrz_check_digit()을 쓴다
#   (ICAO 9303 국제표준 — 여권번호와 달리 이건 실제로 공개된 체크섬 알고리즘이다).
#
# 계좌번호: 은행 공통 체크섬이 없고 은행마다 자릿수/구조가 다르다.
#   검증이 아니라 "은행별로 실제 존재하는 자릿수인지"만 확인한다.

VALID_LICENSE_REGION_CODES = {
    "11", "26", "27", "28", "29", "30", "31", "36",
    "41", "42", "43", "44", "45", "46", "47", "48", "50",
}  # 서울/부산/대구/인천/광주/대전/울산/세종/경기/강원/충북/충남/전북/전남/경북/경남/제주


def validate_driver_license_format(number: str) -> bool:
    """운전면허번호 형식만 검증 (체크섬 아님 — 알고리즘 비공개).

    형식: XX-XX-XXXXXX-XX
    """
    parts = number.split("-")
    if len(parts) != 4:
        return False
    region, year, serial, check = parts
    if region not in VALID_LICENSE_REGION_CODES:
        return False
    if not (year.isdigit() and len(year) == 2):
        return False
    if not (serial.isdigit() and len(serial) == 6):
        return False
    if not (check.isdigit() and len(check) == 2):
        return False
    return True


BANK_ACCOUNT_DIGIT_LENGTHS = {
    "국민은행": 14,
    "신한은행": 12,
    "우리은행": 13,
    "하나은행": 14,
    "카카오뱅크": 13,
    "농협은행": 13,
}  # 하이픈 제외 순수 자릿수. 은행마다 다르므로 체크섬이 아니라 자릿수만 확인.


def validate_account_length(number: str, bank: str) -> bool:
    """계좌번호 자릿수만 검증 (체크섬 아님 — 은행 공통 체크섬 없음)."""
    digits_str = number.replace("-", "")
    expected = BANK_ACCOUNT_DIGIT_LENGTHS.get(bank)
    if expected is None:
        return False
    return digits_str.isdigit() and len(digits_str) == expected


def validate_passport_format(number: str) -> bool:
    """여권번호(화면 인쇄본) 형식만 검증 (체크섬 아님 — 인쇄된 번호 자체엔 체크
    디지트가 없다).

    형식: 영문 1자(M/S 등) + 숫자 8자리, 예: M12345678
    """
    if len(number) != 9:
        return False
    letter, digits = number[0], number[1:]
    return letter.isalpha() and letter.isupper() and digits.isdigit()


# ---------------------------------------------------------------------------
# ICAO 9303 체크 디지트 — MRZ(기계판독영역) 전용. 진짜 공개된 국제표준 알고리즘.
# ---------------------------------------------------------------------------
#
# 여권번호 자체(위 validate_passport_format)와는 별개다. MRZ 라인에 여권번호가
# 9자리로 채워져(빈 자리는 '<') 들어갈 때, 그 뒤에 체크 디지트 1자리가 따라붙는다.
# CNN 클래스에 "mrz"가 별도로 있으니(final-direction.md), 그 필드를 검증하고
# 싶을 때만 쓴다. 지금 스코프에서 mrz 자체를 학습 대상으로 쓰지 않으면 당장은
# 참고용으로만 남겨둔다.

_ICAO_WEIGHTS = [7, 3, 1]


def _icao_char_value(ch: str) -> int:
    if ch.isdigit():
        return int(ch)
    if ch == "<":
        return 0
    if ch.isalpha():
        return ord(ch.upper()) - ord("A") + 10  # A=10, B=11, ..., Z=35
    raise ValueError(f"MRZ에 허용되지 않는 문자: {ch}")


def compute_icao_check_digit(field: str) -> int:
    """ICAO 9303 7-3-1 가중치 체크 디지트 계산."""
    total = sum(
        _icao_char_value(ch) * _ICAO_WEIGHTS[i % 3] for i, ch in enumerate(field)
    )
    return total % 10


def validate_passport_mrz_check_digit(passport_number_field: str, check_digit: str) -> bool:
    """MRZ 상의 여권번호 필드(9자리, 빈 자리는 '<')와 체크 디지트 1자리 검증."""
    if len(passport_number_field) != 9 or len(check_digit) != 1:
        return False
    if not check_digit.isdigit():
        return False
    return compute_icao_check_digit(passport_number_field) == int(check_digit)


# ---------------------------------------------------------------------------
# 테스트 케이스 — 직접 만든 로직이므로 실제로 돌려서 확인한다.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 사업자등록번호: 체크섬 알고리즘으로 직접 역산한 유효값 vs 마지막 자리만 틀린 값
    assert validate_biz_reg("123-45-67891") is True   # 1234567891: 체크섬 맞음
    assert validate_biz_reg("123-45-67890") is False  # 마지막 자리만 다름 (실패해야 정상)
    print("사업자등록번호 검증 통과")

    # 외국인등록번호: 성별코드 자리(7번째)만 5로 바꾼 임의 생성값으로 체크섬 계산 확인
    def make_valid_foreign_reg(front6: str, gender_code: int) -> str:
        weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
        import random
        serial5 = [random.randint(0, 9) for _ in range(5)]
        digits = [int(c) for c in front6] + [gender_code] + serial5 + [0]  # 마지막 0은 체크섬 자리
        total = sum(d * w for d, w in zip(digits[:12], weights))
        check = (11 - total % 11) % 10
        digits[12] = check
        return "".join(map(str, digits))

    test_foreign = make_valid_foreign_reg("900101", 5)
    assert validate_foreign_reg(test_foreign) is True, f"실패: {test_foreign}"
    print(f"외국인등록번호 검증 통과: {test_foreign}")

    # 주민등록번호: 성별코드만 내국인 코드(1~4)로 바꿔서 같은 방식으로 확인
    def make_valid_rrn(front6: str, gender_code: int) -> str:
        weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
        import random
        serial5 = [random.randint(0, 9) for _ in range(5)]
        digits = [int(c) for c in front6] + [gender_code] + serial5 + [0]
        total = sum(d * w for d, w in zip(digits[:12], weights))
        check = (11 - total % 11) % 10
        digits[12] = check
        return "".join(map(str, digits))

    test_rrn = make_valid_rrn("990101", 1)
    assert validate_rrn(test_rrn) is True, f"실패: {test_rrn}"
    assert validate_rrn(test_rrn.replace(test_rrn[-1], str((int(test_rrn[-1]) + 1) % 10))) is False
    print(f"주민등록번호 검증 통과: {test_rrn}")

    # 카드번호 (Luhn — 공개된 국제표준 테스트 번호로 확인)
    assert validate_card_luhn("4111111111111111") is True   # Visa 공개 테스트 번호
    assert validate_card_luhn("4111111111111112") is False  # 마지막 자리 변조
    print("카드번호(Luhn) 검증 통과")

    # 운전면허 형식
    assert validate_driver_license_format("11-24-123456-78") is True
    assert validate_driver_license_format("99-24-123456-78") is False  # 없는 지역코드
    print("운전면허 형식 검증 통과")

    # 계좌번호 자릿수 (국민은행 14자리)
    assert validate_account_length("123-45-6789-01234", "국민은행") is True   # 14자리
    assert validate_account_length("123-45-6789-012", "국민은행") is False    # 12자리, 부족
    print("계좌번호 자릿수 검증 통과")

    # 여권번호 형식 (체크섬 없음, 형식만)
    assert validate_passport_format("M12345678") is True
    assert validate_passport_format("m12345678") is False  # 소문자는 실제 인쇄본과 다름
    assert validate_passport_format("M1234567") is False   # 자릿수 부족
    print("여권번호 형식 검증 통과")

    # MRZ 체크 디지트 (ICAO 9303 국제표준 — 참고용, 지금 스코프에서 필수 아님)
    # 예시: 여권번호 "L898902C3" (ICAO 9303 표준 문서의 공개 예시)의 체크 디지트는 6
    assert validate_passport_mrz_check_digit("L898902C3", "6") is True
    assert validate_passport_mrz_check_digit("L898902C3", "7") is False
    print("MRZ 체크 디지트 검증 통과 (ICAO 9303 공개 예시 기준)")

    print("\n모든 테스트 통과")