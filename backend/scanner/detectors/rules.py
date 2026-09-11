"""정규식으로 형식이 고정된 필드를 찾고, 검증 함수로 오탐을 걸러낸다.

parse.py의 문서 파싱 완성을 기다릴 필요 없이 raw_text만 있으면 동작한다.
필드를 하나로 뭉치지 않고 종류별로 따로 탐지한다 — 필드마다 정규식 + 검증 함수
한 쌍이다. 같은 자릿수의 무작위 숫자열(주문번호, 사번 등)을 개인정보로 오인하지
않도록, 형식이 맞아도 검증을 통과하지 못하면 후보에서 제외한다.

confidence는 검증 강도에 따라 다르게 매긴다:
- 1.0: 체크섬까지 확인됨 (주민등록번호, 사업자등록번호, 법인등록번호, 카드번호)
- 0.9: 접두어/URI 스킴이 워낙 특이해서 오탐 가능성이 낮음 (API 키/토큰, DB 접속정보)
- 0.8: 형식은 맞지만 부분 검증만 가능 (외국인등록번호, 운전면허번호, 여권번호)
- 0.6: 형식만 확인, 별도 검증 수단이 없음 (전화번호, 이메일, IP 주소)
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

from ml.data_generation import validators

# 체크섬 검증은 A의 validators.py를 그대로 쓴다. 같은 알고리즘을 두 벌로 들고
# 있으면 조용히 어긋나는데, 실제로 어긋나 있었다(2026-09-11 대조):
#   - 외국인등록번호: A는 체크섬까지 검증하는데 여기서는 형식만 봐서, 체크섬이
#     깨진 무작위 13자리가 외국인등록번호로 통과했다.
#   - 운전면허 지역코드: 여기서는 근거 없이 11~28 연속 범위를 썼다. 실제 코드는
#     17개(11 서울 / 41 경기 / 50 제주 …)라 경기·강원·충청·전라·경상·제주 등
#     13개 지역의 면허번호를 통째로 놓치고, 존재하지 않는 코드 14개는 통과시켰다.
#   - 카드번호: A는 브랜드별 12~19자리를 인정하는데 16자리만 봐서, Amex(15)와
#     Diners(14)가 계좌번호로 오분류됐다.
# A의 분류기(false_positive_filter.py)도 같은 함수로 학습 라벨을 만들므로,
# 여기서 같은 함수를 쓰면 학습과 추론의 판정이 어긋나지 않는다.

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
# 유효 지역코드는 validators.VALID_LICENSE_REGION_CODES(17개)를 쓴다.
DRIVER_LICENSE_NUMBER_PATTERN = re.compile(
    r"(?<!\d)\d{2}[-\s]?\d{2}[-\s]?\d{6}[-\s]?\d{2}(?!\d)"
)

# ---------- 여권번호 ----------
PASSPORT_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9])[MSRODmsrod]\d{8}(?!\d)")
_PASSPORT_VALID_FIRST_LETTERS = frozenset("MSROD")

# ---------- 카드번호 ----------
# 14~19자리. 브랜드마다 자릿수가 달라서(Diners 14 / Amex 15 / Visa·Master·BC 16)
# 4-4-4-4로 못 박으면 Amex·Diners를 놓친다.
#
# **12~13자리를 범위에서 빼는 이유**(실측, 2026-09-11): Luhn은 자릿수와 무관하게
# 무작위 숫자열의 약 9.9%를 통과시킨다. 그런데 국내 은행 계좌는 12~14자리가
# 흔하다(신한 12 / 우리·카카오·농협 13 / 국민·하나 14). 그래서 12~19로 잡으면
# 계좌번호 10건 중 1건이 카드번호로 오분류된다 — 실제로 신한 12자리와
# 카카오뱅크 13자리가 card로 잡히는 것을 확인했다.
# 국내에 12~13자리 카드는 사실상 없으므로, 그 구간을 빼면 겹치는 자릿수가
# 14 하나로 줄어든다. Luhn만으로는 이 충돌을 막을 수 없다.
CARD_NUMBER_PATTERN = re.compile(r"(?<!\d)(?:\d[-\s]?){13,18}\d(?!\d)")

# ---------- 계좌번호 ----------
# 은행마다 자릿수가 달라 하나의 정규식으로 형식을 완전히 못 박을 수 없다.
# 대시/공백으로 나뉜 숫자 그룹이거나, 구분자 없는 10~16자리 연속 숫자만 후보로 잡는다.
# 휴대폰 번호("010/011/016~019"로 시작하는 3그룹)는 앞쪽에서 미리 제외한다 —
# 이게 없으면 "010-1234-5678"이 그대로 계좌번호 형식도 통과해버린다.
#
# 그룹당 최대 7자리인 이유: 카카오뱅크가 4-2-7(3333-01-1234567)을 쓴다. 6자리로
# 두면 앞의 "3333-01"만 잡히는데, **계좌번호를 일부만 마스킹하고 뒤 7자리를
# 노출시키는 쪽이 아예 못 잡는 것보다 더 나쁘다.**
# 7자리로 넓혀도 오탐은 늘지 않는 것을 실측으로 확인했다(2026-09-10):
# 계좌 형식 커버 8/11 -> 10/11, 오탐은 8/14 그대로 — 주문번호·송장번호·날짜 등
# 오탐 후보는 전부 그룹당 6자리 이하라 7자리 확장에 걸리지 않는다.
# 마지막 그룹만 1자리를 허용하는 이유: 새마을금고형이 4-4-4-1(9002-1234-5678-9)로
# 끝자리가 검증번호 1자리다. 모든 그룹에 2자리를 요구하면 앞 14자리만 잡혀서
# **계좌번호를 일부만 마스킹하고 뒤 1자리를 노출시킨다** — 화면에는 "가렸다"고
# 표시되니 아예 못 잡는 것보다 나쁘다.
# 오탐은 늘지 않는다(실측 2026-09-11): "1-2-3"·"3-1"·"1-2" 같은 값은 그룹 크기와
# 무관하게 아래 "숫자 합계 10~16자리" 조건에서 이미 탈락한다.
BANK_ACCOUNT_NUMBER_PATTERN = re.compile(
    r"(?<!\d)(?!01[016789][-\s]?\d)"
    r"(?:\d{2,7}(?:[-\s]\d{2,7}){1,3}(?:[-\s]\d{1,7})?|\d{10,16})(?!\d)"
)

# ---------- 사번 ----------
# 사번은 회사마다 형식이 완전히 달라서(2024-0317 / A0317 / EMP-00317 / 24-04821)
# 표준 형식이 없다. 이걸 다 잡는 값 정규식을 쓰면 문서번호·버전·좌석번호까지 전부
# 걸려서 오탐 폭탄이 된다.
#
# 그래서 값의 모양이 아니라 **옆에 오는 라벨 단어를 기준점으로** 잡는다. 사번은
# 문서에서 거의 항상 "사번"이라는 단어 옆에 나온다. "문서번호 2024-0317"은 라벨이
# 달라서 걸리지 않는다 — 형식이 아니라 문맥으로 찾으므로 오탐이 거의 없다.
#
# 탐지 자체보다 중요한 목적이 하나 더 있다. A가 schema에 emp_no를 넣은 이유는
# "사번을 탐지하자"가 아니라 "사번 때문에 사업자등록번호·계좌번호가 오탐 난다"였다.
# 여기서 사번을 먼저 집어주면 find_all이 그 구간을 계좌번호 후보에서 빼주므로,
# "사번 2024-0317-05"가 계좌번호로 둔갑하는 일이 사라진다.
EMPLOYEE_NUMBER_PATTERN = re.compile(
    r"(?:사번|사원번호|직원번호|임직원번호)\s*[:은는이]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9-]{1,14}[A-Za-z0-9])"
)

# ---------- 전화번호 ----------
# 휴대폰만 보면 집·사무실 전화가 전부 계좌번호로 오분류된다(실측 2026-09-11:
# 전화 15종 중 12종이 account, 2종은 완전 미탐). 위험점수도 phone 10점이 아니라
# account 30점으로 3배 부풀려지고, 화면에는 "계좌번호 02-1234-5678"로 나간다.
# schema.py의 라벨도 "전화번호"로 집전화를 포함하는 의미다.
#
# 계좌번호와는 충돌하지 않는다(계좌 10종 전부 안전). 전화번호는 0으로 시작하고
# 국번 범위가 정해져 있어서 계좌번호 형식과 겹치는 구간이 없다.
#
# **대표번호(15XX·16XX·18XX)는 일부러 넣지 않는다.** 4자리-4자리라 금액 범위
# "1500-2000", 연도 범위 "1588-1999"과 형태가 완전히 같아서 숫자만으로는 가를 수
# 없다(실측에서 둘 다 오탐으로 잡혔다). 앞뒤 문맥("고객센터" vs "원"·"년")을 보는
# 오탐 제거 분류기가 판정할 몫이다.
PHONE_NUMBER_PATTERN = re.compile(
    r"(?<!\d)(?:"
    r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}"                             # 휴대폰
    r"|02[-\s]?\d{3,4}[-\s]?\d{4}"                                     # 서울 (7·8자리)
    r"|0(?:3[1-3]|4[1-4]|5[1-5]|6[1-4]|70)[-\s]?\d{3,4}[-\s]?\d{4}"   # 지역·인터넷전화
    r"|050\d[-\s]?\d{3,4}[-\s]?\d{4}"                                  # 안심번호
    r")(?!\d)"
)

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


# evidence.checksum에 넣는 값. A가 정한 화이트리스트 그대로다
# (B팀_종합정리_0910.md의 evidence 키 표). DB가 이 값으로 통계를 낸다.
CHECKSUM_PASS = "pass"
CHECKSUM_NOT_AVAILABLE = "not_available"


def _verify_corporate_mod11(digits13: str) -> bool:
    """법인등록번호 체크섬. 주민등록번호와 같은 공식을 쓴다고 알려져 있다.

    **근거가 확정되지 않은 알고리즘이다.** A도 validators.py에서 법인등록번호를
    "표준 공개 알고리즘 출처 확인 전이라 보류"로 남겨뒀다. 그래서 이 검사를
    통과해도 evidence.checksum은 "pass"가 아니라 "not_available"로 표시하고
    확신도도 낮게 준다 — 근거 없이 "체크섬 검증됨"이라고 주장하면, 발표에서
    알고리즘 출처를 물었을 때 답할 수 없다.

    그래도 검사를 아예 빼지는 않는다. 무작위 13자리가 통과할 확률이 1/11로
    줄어들어 오탐을 크게 깎아주기 때문이다.
    """
    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    total = sum(int(d) * w for d, w in zip(digits13[:12], weights))
    return (11 - (total % 11)) % 10 == int(digits13[12])


def _is_valid_birth_date(front6: str, gender_digit: str) -> bool:
    """주민등록번호 앞 6자리(YYMMDD)가 실존하는 날짜인지 확인한다.
    성별 숫자 1·2는 1900년대, 3·4는 2000년대 출생을 뜻한다.

    validators.validate_rrn에는 없는 추가 검사다. 체크섬만 보면 "139932-1……"
    처럼 날짜가 될 수 없는 값도 통과한다.
    """
    century = 1900 if gender_digit in ("1", "2") else 2000
    year, month, day = int(front6[:2]), int(front6[2:4]), int(front6[4:6])
    try:
        datetime.date(century + year, month, day)
    except ValueError:
        return False
    return True


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
        if not validators.validate_rrn(digits):
            continue
        matches.append(
            {
                "field": "rrn",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
                "evidence": {"checksum": CHECKSUM_PASS},
            }
        )
    return matches


def find_foreign_registration_numbers(text: str) -> list[dict]:
    """형식(6자리-성별숫자5~8-6자리)과 체크섬을 통과한 외국인등록번호만 반환한다.

    체크섬 알고리즘은 주민등록번호와 같다(validators.validate_foreign_reg).
    이전에는 뒷자리 첫 숫자만 보고 통과시켜서, 체크섬이 깨진 무작위 13자리가
    외국인등록번호로 잡혔다.
    """
    matches = []
    for m in FOREIGN_REGISTRATION_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if not validators.validate_foreign_reg(digits):
            continue
        matches.append(
            {
                "field": "foreign_reg",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
                "evidence": {"checksum": CHECKSUM_PASS},
            }
        )
    return matches


def find_business_registration_numbers(text: str) -> list[dict]:
    """형식(3-2-5자리)과 체크섬을 모두 통과한 사업자등록번호 후보만 반환한다."""
    matches = []
    for m in BUSINESS_REGISTRATION_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if not validators.validate_biz_reg(digits):
            continue
        matches.append(
            {
                "field": "biz_reg",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
                "evidence": {"checksum": CHECKSUM_PASS},
            }
        )
    return matches


def find_corporate_registration_numbers(text: str) -> list[dict]:
    """형식(6-7자리)과 체크섬을 모두 통과한 법인등록번호 후보만 반환한다.
    체크섬은 주민등록번호와 동일한 공식을 쓴다.

    한계: 자릿수(13)도 체크섬 공식도 주민등록번호와 같아서, 앞 6자리가 우연히
    유효한 날짜이고 7번째가 1~4인 법인등록번호는 형식만으로 주민등록번호와
    구분할 수 없다. 그런 값은 dedupe에서 위험도가 높은 rrn(40점)으로 남아
    실제 위험도(법인등록번호 5점)보다 8배 부풀려진다. 원리적 한계라 규칙으로는
    못 고치고, 앞뒤 문맥("법인등록번호:" 같은)을 보는 오탐 제거 분류기가
    붙어야 갈린다. 앞 6자리가 날짜가 아닌 대부분의 법인등록번호는 rrn 쪽이
    생년월일 검증에서 탈락하므로 정상적으로 corp_reg로 잡힌다."""
    matches = []
    for m in CORPORATE_REGISTRATION_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) != 13:
            continue
        if not _verify_corporate_mod11(digits):
            continue
        matches.append(
            {
                "field": "corp_reg",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                # 체크섬 알고리즘의 출처가 확정되지 않았다(_verify_corporate_mod11 참고).
                # 검증했다고 주장하지 않고, 확신도도 형식 일치 수준으로만 준다.
                "confidence": 0.6,
                "evidence": {"checksum": CHECKSUM_NOT_AVAILABLE},
            }
        )
    return matches


def find_driver_license_numbers(text: str) -> list[dict]:
    """형식(2-2-6-2자리)과 유효 지역코드를 통과한 운전면허번호만 반환한다.

    지역코드는 validators.VALID_LICENSE_REGION_CODES(실제 17개)를 쓴다. 이전에는
    근거 없이 11~28 연속 범위를 써서 경기(41)·강원(42)·충청·전라·경상·제주(50) 등
    13개 지역의 면허번호를 통째로 놓쳤고, 존재하지 않는 코드 14개(12~25)는
    통과시켰다.

    뒤 2자리 검증번호 산출 로직은 도로교통공단 내부 알고리즘이라 공개돼 있지 않다
    (validators.py 참고). 그래서 체크섬은 "not_available"이다.
    """
    matches = []
    for m in DRIVER_LICENSE_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) != 12:
            continue
        if digits[:2] not in validators.VALID_LICENSE_REGION_CODES:
            continue
        matches.append(
            {
                "field": "driver_license",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 0.8,
                "evidence": {"checksum": CHECKSUM_NOT_AVAILABLE},
            }
        )
    return matches


def find_passport_numbers(text: str) -> list[dict]:
    """형식(영문자 1자리 + 숫자 8자리)을 통과한 여권번호 후보만 반환한다.

    인쇄된 여권번호 자체에는 체크 디지트가 없다 — 체크 디지트는 하단 MRZ
    문자열 안에만 있다(validators.py의 ICAO 9303 설명 참고). 그래서 형식
    검증까지만 하고 체크섬은 "not_available"이다.
    """
    matches = []
    for m in PASSPORT_NUMBER_PATTERN.finditer(text):
        if not validators.validate_passport_format(m.group().upper()):
            continue
        if m.group()[0].upper() not in _PASSPORT_VALID_FIRST_LETTERS:
            continue
        matches.append(
            {
                "field": "passport",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 0.8,
                "evidence": {"checksum": CHECKSUM_NOT_AVAILABLE},
            }
        )
    return matches


def find_card_numbers(text: str) -> list[dict]:
    """12~19자리 숫자열 중 Luhn 체크섬을 통과한 카드번호만 반환한다.

    브랜드마다 자릿수가 다르다(Visa 16 / Amex 15 / Diners 14). 16자리만 보면
    Amex·Diners가 계좌번호로 오분류된다.
    """
    matches = []
    for m in CARD_NUMBER_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if not validators.validate_card_luhn(digits):
            continue
        matches.append(
            {
                "field": "card",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
                "evidence": {"checksum": CHECKSUM_PASS},
            }
        )
    return matches


def find_bank_account_numbers(text: str) -> list[dict]:
    """은행별로 자릿수가 달라 체크섬 검증이 불가능하다. 형식만 맞으면 후보로
    넘기고, 최종 판정(진짜 계좌번호 vs 주문번호·사번 등)은 오탐 제거 분류기가 한다.

    validators.validate_account_length는 은행명을 인자로 받는데 스캔 시점에는
    어느 은행인지 알 수 없어서 쓰지 못한다. 그래서 자릿수 범위만 본다.
    """
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
                "evidence": {"checksum": CHECKSUM_NOT_AVAILABLE},
            }
        )
    return matches


def find_employee_numbers(text: str) -> list[dict]:
    """"사번"·"사원번호" 같은 라벨 뒤에 오는 값을 사번으로 잡는다.

    start/end는 라벨이 아니라 **값 부분만** 가리킨다 — 마스킹해야 하는 것은
    "사번:"이 아니라 그 뒤의 값이다. 값 형식에 제약이 거의 없어 체크섬은 없지만,
    라벨 단어가 바로 앞에 있다는 것 자체가 강한 근거라 확신도를 0.8로 둔다.
    """
    return [
        {
            "field": "emp_no",
            "value": m.group(1),
            "start": m.start(1),
            "end": m.end(1),
            "confidence": 0.8,
        }
        for m in EMPLOYEE_NUMBER_PATTERN.finditer(text)
    ]


def find_phone_numbers(text: str) -> list[dict]:
    """전화번호 형식 후보(휴대폰·집·사무실·인터넷전화·안심번호). 별도 검증 수단이
    없어 형식 일치만으로 판단한다. 대표번호(15XX 등)는 패턴에서 제외했다 —
    PHONE_NUMBER_PATTERN 주석 참고."""
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
    """모든 필드 탐지기를 돌려서 하나의 목록으로 합친다.

    계좌번호만 맨 마지막에 따로 처리한다. 은행별 자릿수를 못 박을 수 없어 패턴이
    넓다 보니 다른 번호를 통째로 삼키는데, scan.py의 dedupe는 위험 가중치만 보기
    때문에(계좌 30점 > 사업자등록번호 5점) **체크섬으로 검증된 쪽이 밀려나** 오히려
    오탐이 된다. 실제로 "123-45-67891"(체크섬 통과한 사업자등록번호)이 확신도 0.3짜리
    계좌번호로 표시되는 걸 확인했다. 그래서 다른 탐지기가 이미 잡은 구간과 겹치는
    계좌번호 후보는 여기서 버린다 — 계좌번호는 "다른 무엇도 아닌 숫자"일 때만
    계좌번호다.
    """
    findings = (
        find_resident_registration_numbers(text)
        + find_foreign_registration_numbers(text)
        + find_business_registration_numbers(text)
        + find_corporate_registration_numbers(text)
        + find_driver_license_numbers(text)
        + find_passport_numbers(text)
        + find_card_numbers(text)
        + find_employee_numbers(text)
        + find_phone_numbers(text)
        + find_emails(text)
        + find_ip_addresses(text)
        + find_api_keys_and_tokens(text)
        + find_db_connection_strings(text)
    )
    claimed = [(m["start"], m["end"]) for m in findings]
    accounts = [
        m
        for m in find_bank_account_numbers(text)
        if not any(m["start"] < end and start < m["end"] for start, end in claimed)
    ]
    return findings + accounts
