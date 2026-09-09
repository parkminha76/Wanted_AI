"""정규식으로 형식이 고정된 필드를 찾고, 검증 함수로 오탐을 걸러낸다.

parse.py의 문서 파싱 완성을 기다릴 필요 없이 raw_text만 있으면 동작한다.
필드를 하나로 뭉치지 않고 종류별로 따로 탐지한다 — 필드마다 정규식 + 검증 함수
한 쌍이다. 같은 자릿수의 무작위 숫자열(주문번호, 사번 등)을 개인정보로 오인하지
않도록, 형식이 맞아도 검증을 통과하지 못하면 후보에서 제외한다.

confidence는 검증 강도에 따라 다르게 매긴다:
- 1.0: 체크섬까지 확인됨 (주민등록번호, 사업자등록번호, 법인등록번호, 카드번호)
- 0.9: 접두어/URI 스킴이 워낙 특이해서 오탐 가능성이 낮음 (API 키/토큰, DB 접속정보)
- 0.8: 형식은 맞지만 부분 검증만 가능 (외국인등록번호, 운전면허번호, 여권번호)
- 0.6: 형식만 확인, 별도 검증 수단이 없음 (휴대폰, 이메일, IP 주소)
- 0.3: 체크섬 자체가 존재하지 않아 형식만으로는 판단 불가 (계좌번호) —
  최종 판정은 오탐 제거 분류기(models.filter_false_positive)에 맡긴다.

주의: 사업자등록번호·법인등록번호·운전면허번호·여권번호의 검증 로직은 공개된
알고리즘/자료를 근거로 작성했지만, 실제 유효한 예시로 재검산하기 전까지는
100% 신뢰하지 말 것 (ml/data_generation의 원칙과 동일).

field 값은 backend/shared/schema.py의 RiskType 문자열을 그대로 쓴다 —
여기서 다른 이름을 쓰면 scan.py가 매번 번역 테이블을 거쳐야 하고, 화면(D)이
받는 타입과 위험점수표(RISK_WEIGHTS)가 어긋난다.
"""

import datetime
import re

# 숫자 패턴은 전부 (?<!\d) ... (?!\d)로 앞뒤를 막는다. 이게 없으면 실패한 매치를
# 한 칸 밀어서 재시도하다가 원래 값보다 한 자리 짧은 부분 문자열이 우연히 형식을
# 통과해버리는 경우가 생긴다(휴대폰 번호 "010-1234-5678"이 "10-1234-5678"로 계좌번호
# 패턴에 걸리는 식). 실제로 scan.py 통합 테스트에서 이 문제로 휴대폰 번호가 계좌번호로
# 오분류되는 걸 확인하고 추가했다.

# ---------- 주민등록번호 ----------
RESIDENT_REGISTRATION_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)")

# ---------- 외국인등록번호 ----------
FOREIGN_REGISTRATION_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{6}[-\s]?[5-8]\d{6}(?!\d)")

# ---------- 사업자등록번호 ----------
BUSINESS_REGISTRATION_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{3}-?\d{2}-?\d{5}(?!\d)")

# ---------- 법인등록번호 ----------
CORPORATE_REGISTRATION_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{6}-?\d{7}(?!\d)")

# ---------- 운전면허번호 ----------
DRIVER_LICENSE_NUMBER_PATTERN = re.compile(
    r"(?<!\d)\d{2}[-\s]?\d{2}[-\s]?\d{6}[-\s]?\d{2}(?!\d)"
)
_DRIVER_LICENSE_REGION_CODE_MIN = 11
_DRIVER_LICENSE_REGION_CODE_MAX = 28

# ---------- 여권번호 ----------
PASSPORT_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9])[MSRODmsrod]\d{8}(?!\d)")
_PASSPORT_VALID_FIRST_LETTERS = frozenset("MSROD")

# ---------- 카드번호 ----------
CARD_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)")

# ---------- 계좌번호 ----------
# 은행마다 자릿수가 달라 하나의 정규식으로 형식을 완전히 못 박을 수 없다.
# 대시/공백으로 나뉜 숫자 그룹이거나, 구분자 없는 10~16자리 연속 숫자만 후보로 잡는다.
# 휴대폰 번호("010/011/016~019"로 시작하는 3그룹)는 앞쪽에서 미리 제외한다 —
# 이게 없으면 "010-1234-5678"이 그대로 계좌번호 형식도 통과해버린다.
BANK_ACCOUNT_NUMBER_PATTERN = re.compile(
    r"(?<!\d)(?!01[016789][-\s]?\d)(?:\d{2,6}(?:[-\s]\d{2,6}){1,4}|\d{10,16})(?!\d)"
)

# ---------- 휴대폰 ----------
PHONE_NUMBER_PATTERN = re.compile(r"(?<!\d)01[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")

# ---------- 이메일 ----------
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# ---------- IP 주소 ----------
IP_ADDRESS_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)

# ---------- API 키/토큰 ----------
API_KEY_OR_TOKEN_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]{20,}"
    r"|ghp_[A-Za-z0-9]{36}"
    r"|AKIA[0-9A-Z]{16}"
    r"|AIza[0-9A-Za-z_\-]{35}"
    r"|Bearer\s+[A-Za-z0-9\-._~+/]+=*"
    r"|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*",
    re.IGNORECASE,
)

# ---------- DB 접속정보 ----------
DB_CONNECTION_STRING_PATTERN = re.compile(
    r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://\S+",
    re.IGNORECASE,
)


def _verify_mod11_checksum(digits13: str) -> bool:
    """13자리 정부발급번호(주민등록번호/법인등록번호) 공통 체크섬. 뒤 12자리에
    가중치를 곱해 더한 값으로 마지막 한 자리를 검산한다."""
    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    total = sum(int(d) * w for d, w in zip(digits13[:12], weights))
    check_digit = (11 - (total % 11)) % 10
    return check_digit == int(digits13[12])


def _is_valid_birth_date(front6: str, gender_digit: str) -> bool:
    """주민등록번호 앞 6자리(YYMMDD)가 실존하는 날짜인지 확인한다.
    성별 숫자 1·2는 1900년대, 3·4는 2000년대 출생을 뜻한다."""
    century = 1900 if gender_digit in ("1", "2") else 2000
    year, month, day = int(front6[:2]), int(front6[2:4]), int(front6[4:6])
    try:
        datetime.date(century + year, month, day)
    except ValueError:
        return False
    return True


def _verify_business_registration_number(digits: str) -> bool:
    """사업자등록번호 10자리 표준 체크섬 (가중치 1,3,7,1,3,7,1,3,5)."""
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    total = sum(int(d) * w for d, w in zip(digits[:9], weights))
    total += (int(digits[8]) * 5) // 10
    check_digit = (10 - (total % 10)) % 10
    return check_digit == int(digits[9])


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


def _is_private_ipv4(ip: str) -> bool:
    """사설 IP 대역(10/8, 172.16/12, 192.168/16, 127/8) 여부."""
    a, b, *_ = (int(o) for o in ip.split("."))
    if a == 10 or a == 127:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    return False


def find_resident_registration_numbers(text: str) -> list[dict]:
    """형식(6자리-성별숫자1~4-6자리)과 생년월일 유효성 + 체크섬을 모두 통과한 후보만 반환한다."""
    matches = []
    for m in RESIDENT_REGISTRATION_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) != 13:
            continue
        if not _is_valid_birth_date(digits[:6], digits[6]):
            continue
        if not _verify_mod11_checksum(digits):
            continue
        matches.append(
            {
                "field": "rrn",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
            }
        )
    return matches


def find_foreign_registration_numbers(text: str) -> list[dict]:
    """형식(6자리-성별숫자5~8-6자리)을 통과한 외국인등록번호 후보만 반환한다.
    체크섬은 없고 뒷자리 첫 숫자가 5~8인지가 유일한 검증이다."""
    matches = []
    for m in FOREIGN_REGISTRATION_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) != 13 or digits[6] not in ("5", "6", "7", "8"):
            continue
        matches.append(
            {
                "field": "foreign_reg",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 0.8,
            }
        )
    return matches


def find_business_registration_numbers(text: str) -> list[dict]:
    """형식(3-2-5자리)과 체크섬을 모두 통과한 사업자등록번호 후보만 반환한다."""
    matches = []
    for m in BUSINESS_REGISTRATION_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) != 10:
            continue
        if not _verify_business_registration_number(digits):
            continue
        matches.append(
            {
                "field": "biz_reg",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
            }
        )
    return matches


def find_corporate_registration_numbers(text: str) -> list[dict]:
    """형식(6-7자리)과 체크섬을 모두 통과한 법인등록번호 후보만 반환한다.
    체크섬은 주민등록번호와 동일한 공식을 쓴다."""
    matches = []
    for m in CORPORATE_REGISTRATION_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) != 13:
            continue
        if not _verify_mod11_checksum(digits):
            continue
        matches.append(
            {
                "field": "corp_reg",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
            }
        )
    return matches


def find_driver_license_numbers(text: str) -> list[dict]:
    """형식(2-2-6-2자리)과 지역코드 유효 범위를 통과한 운전면허번호 후보만 반환한다."""
    matches = []
    for m in DRIVER_LICENSE_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) != 12:
            continue
        region_code = int(digits[:2])
        if not (_DRIVER_LICENSE_REGION_CODE_MIN <= region_code <= _DRIVER_LICENSE_REGION_CODE_MAX):
            continue
        matches.append(
            {
                "field": "driver_license",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 0.8,
            }
        )
    return matches


def find_passport_numbers(text: str) -> list[dict]:
    """형식(영문자 1자리 + 숫자 8자리)과 첫 글자 종류를 통과한 여권번호 후보만 반환한다."""
    matches = []
    for m in PASSPORT_NUMBER_PATTERN.finditer(text):
        if m.group()[0].upper() not in _PASSPORT_VALID_FIRST_LETTERS:
            continue
        matches.append(
            {
                "field": "passport",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 0.8,
            }
        )
    return matches


def find_card_numbers(text: str) -> list[dict]:
    """16자리(4-4-4-4) 숫자열 중 Luhn 체크섬을 통과한 카드번호 후보만 반환한다."""
    matches = []
    for m in CARD_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        if len(digits) != 16:
            continue
        if not _verify_luhn(digits):
            continue
        matches.append(
            {
                "field": "card",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
            }
        )
    return matches


def find_bank_account_numbers(text: str) -> list[dict]:
    """은행별로 자릿수가 달라 체크섬 검증이 불가능하다. 형식만 맞으면 후보로
    넘기고, 최종 판정(진짜 계좌번호 vs 주문번호·사번 등)은 오탐 제거 분류기가 한다."""
    matches = []
    for m in BANK_ACCOUNT_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if not (10 <= len(digits) <= 16):
            continue
        matches.append(
            {
                "field": "account",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 0.3,
            }
        )
    return matches


def find_phone_numbers(text: str) -> list[dict]:
    """휴대폰 번호 형식 후보. 별도 검증 수단이 없어 형식 일치만으로 판단한다."""
    return [
        {
            "field": "phone",
            "value": m.group(),
            "start": m.start(),
            "end": m.end(),
            "confidence": 0.6,
        }
        for m in PHONE_NUMBER_PATTERN.finditer(text)
    ]


def find_emails(text: str) -> list[dict]:
    """이메일 표준 형식 후보. 별도 검증 수단이 없어 형식 일치만으로 판단한다."""
    return [
        {
            "field": "email",
            "value": m.group(),
            "start": m.start(),
            "end": m.end(),
            "confidence": 0.6,
        }
        for m in EMAIL_PATTERN.finditer(text)
    ]


def find_ip_addresses(text: str, exclude_private: bool = True) -> list[dict]:
    """IPv4 형식 후보. exclude_private=True면 사설 대역(10/8, 172.16/12,
    192.168/16, 127/8)은 결과에서 뺀다."""
    matches = []
    for m in IP_ADDRESS_PATTERN.finditer(text):
        if exclude_private and _is_private_ipv4(m.group()):
            continue
        matches.append(
            {
                "field": "ip",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 0.6,
            }
        )
    return matches


def find_api_keys_and_tokens(text: str) -> list[dict]:
    """알려진 접두어(sk-, ghp_, AKIA, AIza, Bearer, JWT)로 시작하는 API 키/토큰 후보."""
    return [
        {
            "field": "api_key",
            "value": m.group(),
            "start": m.start(),
            "end": m.end(),
            "confidence": 0.9,
        }
        for m in API_KEY_OR_TOKEN_PATTERN.finditer(text)
    ]


def find_db_connection_strings(text: str) -> list[dict]:
    """postgres://, mysql://, mongodb:// 접두어로 시작하는 DB 접속정보 URI 후보."""
    return [
        {
            "field": "db_credential",
            "value": m.group(),
            "start": m.start(),
            "end": m.end(),
            "confidence": 0.9,
        }
        for m in DB_CONNECTION_STRING_PATTERN.finditer(text)
    ]


def find_all(text: str) -> list[dict]:
    """모든 필드 탐지기를 돌려서 하나의 목록으로 합친다."""
    return (
        find_resident_registration_numbers(text)
        + find_foreign_registration_numbers(text)
        + find_business_registration_numbers(text)
        + find_corporate_registration_numbers(text)
        + find_driver_license_numbers(text)
        + find_passport_numbers(text)
        + find_card_numbers(text)
        + find_bank_account_numbers(text)
        + find_phone_numbers(text)
        + find_emails(text)
        + find_ip_addresses(text)
        + find_api_keys_and_tokens(text)
        + find_db_connection_strings(text)
    )
