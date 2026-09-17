"""정규식으로 형식이 고정된 필드를 찾고, 검증 함수로 오탐을 걸러낸다.

parse.py의 문서 파싱 완성을 기다릴 필요 없이 raw_text만 있으면 동작한다.
필드를 하나로 뭉치지 않고 종류별로 따로 탐지한다 — 필드마다 정규식 + 검증 함수
한 쌍이다. 같은 자릿수의 무작위 숫자열(주문번호, 사번 등)을 개인정보로 오인하지
않도록, 형식이 맞아도 검증을 통과하지 못하면 후보에서 제외한다.

confidence는 검증 강도에 따라 다르게 매긴다:
- 1.0: 체크섬까지 확인됨 (주민등록번호, 외국인등록번호, 사업자등록번호, 카드번호)
- 0.9: 접두어/URI 스킴이 워낙 특이해서 오탐 가능성이 낮음 (API 키/토큰, DB 접속정보)
- 0.8: 형식은 맞지만 부분 검증만 가능 (운전면허번호, 여권번호) /
  값이 아니라 옆 라벨 단어를 근거로 잡음 (사번 — 라벨이 값 **앞**에 올 때)
- 0.6: 형식만 확인, 별도 검증 수단이 없음 (전화번호, 이메일, IP 주소, 상세 주소) /
  체크섬 알고리즘의 출처가 확정되지 않음 (법인등록번호) /
  라벨이 값 **뒤**에 와서 근거가 한 단계 약함
  (사번 — find_employee_numbers_before_label)
- 0.3: 체크섬 자체가 존재하지 않아 형식만으로는 판단 불가 (계좌번호) —
  최종 판정은 오탐 제거 분류기(models.filter_false_positive)에 맡긴다.

주의: 법인등록번호·운전면허번호·여권번호는 공개된 알고리즘/자료를 근거로
작성했지만 실제 유효한 예시로 재검산하지 못했다. 그래서 evidence.checksum을
"pass"가 아니라 "not_available"로 내보낸다 — 검증했다고 주장하지 않는다.
주민등록번호·외국인등록번호·사업자등록번호·카드번호는 A의 validators.py(실제
체크섬 검증본)를 쓰므로 이 주의 대상이 아니다.

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
#     Diners(14)가 계좌번호로 오분류됐다. (단 우리 패턴은 14~19로 좁혔다 —
#     12~13자리는 국내 계좌번호와 겹쳐서, 아래 CARD_NUMBER_PATTERN 주석 참고.)
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
# 앞뒤 하이픈도 경계로 막는다. 숫자만 막으면 3-3-7 계좌번호
# ``781-006-1980474`` 안의 ``006-1980474``처럼 우연히 체크섬을 통과한
# 뒷부분이 사업자등록번호로 선점되어 전체 계좌번호가 사라질 수 있다.
BUSINESS_REGISTRATION_NUMBER_PATTERN = re.compile(
    r"(?<![\d-])\d{3}-?\d{2}-?\d{5}(?![\d-])"
)

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

# 구분자가 있으면 **그룹 모양**으로 카드와 계좌를 가른다(실측, 2026-09-12).
# 카드번호는 브랜드가 정한 고정 묶음으로 적는다:
#     (4,4,4,4)    16자리 — Visa·Master·BC·JCB 등 국내 카드 대부분
#     (4,6,5)      15자리 — Amex
#     (4,6,4)      14자리 — Diners Club
#     (4,4,4,4,3)  19자리 — UnionPay 일부
# 국내 은행 계좌는 이 모양을 쓰지 않는다. 계좌 2,000건을 뽑아 보니 모양이
# 4-3-6 / 3-6-5 / 3-2-4-5 / 4-4-5 / 3-4-6 / 3-3-6 여섯 가지였고 위와 겹치는 것이
# 하나도 없었다.
#
# 자릿수만 보던 이전 방식은 14자리에서 충돌했다. Luhn은 자릿수와 무관하게 무작위
# 숫자열의 약 9.9%를 통과시키는데 국내 계좌도 14자리가 흔해서(국민·하나·기업),
# **계좌 2,000건 중 84건(4.2%)이 카드번호로 표시됐다** — 예: "301-684934-07224".
# 가중치는 card·account 둘 다 30점으로 같지만 확신도가 1.0 대 0.3이라 위험 점수
# 기여가 3.3배로 뛰고, 화면에도 "카드번호"라는 틀린 이름이 나간다.
# 그룹 모양으로 바꾼 뒤 같은 2,000건에서 0건이 됐고, 카드 쪽은 위 네 모양과
# 연속 표기까지 각 200건씩 100% 그대로 잡힌다.
_CARD_GROUP_SHAPES = frozenset({(4, 4, 4, 4), (4, 6, 5), (4, 6, 4), (4, 4, 4, 4, 3)})

# 구분자 없이 붙여 쓴 숫자는 모양으로 가를 수 없어 자릿수로만 본다. 15자리
# 이상만 받는다 — 국내 계좌가 12~14자리라 14 이하를 받으면 위 충돌이 되돌아온다.
# 대신 **구분자 없이 붙여 쓴 14자리 Diners 카드는 놓친다.** 국내 점유율이 사실상
# 0이고 문서에는 거의 항상 구분자를 넣어 적기 때문에 이쪽을 버렸다.
_CARD_MIN_UNSEPARATED_DIGITS = 15

# ---------- 계좌번호 ----------
# 은행마다 자릿수가 달라 하나의 정규식으로 형식을 완전히 못 박을 수 없다.
# 대시/공백으로 나뉜 숫자 그룹이거나, 구분자 없는 10~16자리 연속 숫자만 후보로 잡는다.
# 지원 대상으로 확정한 3-3-7 형식도 이 범위에 포함한다.
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

# 스프레드시트 날짜는 파서에서 "2026-03-15 00:00:00" 같은 문자열이 된다.
# 계좌 형식 정규식은 그 앞의 "2026-03-15 00"도 후보로 잡으므로, 완전한 날짜와
# 시각의 앞부분인 경우 계좌 후보에서 제외한다.
_DATE_TIME_ACCOUNT_FALSE_POSITIVE = re.compile(
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:[ T]\d{1,2})?"
)

# ---------- 생년월일 ----------
# 지금까지는 이미지 신분증(CNN)에서만 잡혔다(schema.py birth_date 주석 참고).
# 그런데 이력서·지원서 같은 일반 문서(텍스트든 OCR이든)에도 생년월일이 거의 항상
# 있는데 잡을 방법이 하나도 없었다(실측: 2026-09-17, 이력서·지원서 사진 두 장
# 모두 생년월일이 마스킹 없이 그대로 남음).
#
# 발급일자·만료일·수상일 같은 다른 날짜와 형식이 완전히 같아서(둘 다
# "YYYY.MM.DD"), 값만으로는 구분할 수 없다. address와 같은 방식으로 **앞쪽에
# 단서어가 있을 때만** 받는다 — "생년월일" 옆에 없는 날짜는 후보에서 아예
# 제외되므로, 학력·자격증 표의 다른 날짜들을 생년월일로 오인하지 않는다.
_BIRTH_DATE_PATTERN = re.compile(
    r"(?<!\d)(?:19|20)\d{2}[.\-/]\s?\d{1,2}[.\-/]\s?\d{1,2}\.?(?!\d)"
    r"|(?<!\d)(?:19|20)\d{2}년\s?\d{1,2}월\s?\d{1,2}일"
)
# 서식 라벨은 글자 사이를 띄워 쓰는 경우가 흔하다("생 년 월 일"). 공백을
# 허용하지 않으면 그 형태를 못 찾는다(실측: 2026-09-17, 지원서 서식의
# "생 년 월 일" 라벨).
_BIRTH_DATE_CUE = re.compile(r"생\s*년\s*월\s*일|생\s*일|DOB", re.IGNORECASE)
_BIRTH_DATE_CUE_WINDOW = 10


def find_birth_dates(text: str) -> list[dict]:
    """"생년월일" 같은 단서어 뒤 15자 이내에 온 날짜만 생년월일로 받는다.

    실존하는 날짜인지도 확인한다 — "1996.13.40"처럼 단서어 옆에 있어도 달력에
    없는 값은 버린다.
    """
    matches = []
    for m in _BIRTH_DATE_PATTERN.finditer(text):
        window_start = max(0, m.start() - _BIRTH_DATE_CUE_WINDOW)
        if not _BIRTH_DATE_CUE.search(text[window_start : m.start()]):
            continue
        digits = re.findall(r"\d+", m.group())
        if len(digits) != 3:
            continue
        year, month, day = (int(d) for d in digits)
        try:
            datetime.date(year, month, day)
        except ValueError:
            continue
        matches.append(
            {
                "field": "birth_date",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 0.6,
                "reason": "생년월일 단서어 뒤에 온 날짜 형식",
            }
        )
    return matches


# ---------- 성명(표 라벨) ----------
# NER은 "성 명 이수인 성별 여"처럼 표 라벨과 값 여러 개가 한 줄에 붙어 있으면
# 이름을 놓치거나 망가뜨렸다(실측: 2026-09-17, "이수인"을 "이수"로 잘라 확신도
# 0.4에 그침 — 오탐 제거 분류기 단계에서 걸러짐). 반면 "지원자 : 이예지 (인)"처럼
# 자연스러운 문장에서는 0.8대로 정확히 잡았다. 표 라벨 형태에서만 놓치므로,
# "성명"이라는 라벨 자체를 emp_no와 같은 방식(라벨 옆에 있으면 잡는다)으로
# 보강한다.
#
# "이름"은 쓰지 않는다 — "파일 이름", "회사 이름"처럼 사람이 아닌 대상에도 흔히
# 쓰여 오탐이 늘어난다. "성명"은 사람의 법적 이름을 가리킬 때만 쓰는 말이다.
# 라벨과 값 사이에 공백이나 구분자가 없으면 "성명란은"처럼 라벨에 붙은 다음
# 음절을 이름으로 잘못 캡처한다(실측: "성명란은"의 "란은"이 이름으로 잡힘).
# 그래서 `\s*` 대신 최소 한 칸 이상의 공백이나 `:`/`|`을 반드시 요구한다.
_PERSON_NAME_LABEL_PATTERN = re.compile(r"성\s*명(?:\s*[:|]\s*|\s+)([가-힣]{2,4})(?=[\s,:|]|$)")


def find_person_names_after_label(text: str) -> list[dict]:
    """"성명" 라벨 바로 뒤에 오는 2~4음절 한글을 이름 후보로 잡는다."""
    return [
        {
            "field": "person",
            "value": m.group(1),
            "start": m.start(1),
            "end": m.end(1),
            "confidence": 0.6,
            "reason": '"성명" 라벨 바로 뒤에 온 값',
        }
        for m in _PERSON_NAME_LABEL_PATTERN.finditer(text)
    ]


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

# 값이 라벨보다 **먼저** 오는 어순도 잡는다("EMP-03250 사원의 부서 이동을 승인합니다").
# 표 형태 문서에서 특히 흔하다 — 첫 칸에 사번, 그 뒤 칸에 "사원"·"직원"이 온다.
#
# 이쪽은 라벨이 뒤에 있어 근거가 약하므로 값 모양을 좁힌다. 하이픈으로 나뉜 값
# ("2026-2216", "EMP-03250", "24-04821")이거나 영문+숫자 조합("K6371", "A0317")만
# 받고, **순수 숫자만 있는 값은 받지 않는다.** 안 그러면 "총 120 사원"의 "120"이
# 사번이 된다.
#
# 그래도 "010-1234-5678 직원 연락처"처럼 다른 번호가 걸릴 수 있어서, find_all이
# 이 후보를 계좌번호와 같은 취급으로 맨 뒤에 처리한다 — 다른 탐지기가 이미 잡은
# 구간과 겹치면 버린다.
# 길이도 3~12자로 묶는다. 실측한 사번은 5~9자("R6080", "2022-9316", "37-73163")인데
# 계좌번호는 14~17자라 사이가 넓게 비어 있다. 이 빗장이 없으면 "입금 계좌
# 301-684934-07224 사원 복지비"의 계좌번호가 사번으로 둔갑한다(실제로 그랬다).
EMPLOYEE_NUMBER_TRAILING_PATTERN = re.compile(
    r"(?<![A-Za-z0-9-])"
    r"(?=[A-Za-z0-9-]{3,12}(?![A-Za-z0-9-]))"
    r"([A-Za-z0-9]+(?:-[A-Za-z0-9]+){1,2}|[A-Za-z]+[0-9][A-Za-z0-9]*)"
    r"\s*(?:사번|사원|직원|임직원)"
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
# 없다(실측에서 둘 다 오탐으로 잡혔다).
#
# 그래서 대표번호는 **아예 탐지되지 않는다.** 오탐 제거 분류기에 판정을 맡기는
# 것도 불가능하다 — 여기서 후보를 만들지 않으면 그 분류기는 호출조차 되지 않는다
# (실측 2026-09-12: "대표번호 1588-1234 로 문의" -> 탐지 0건). 대표번호를 잡기로
# 정하면 이 패턴에 넣는 변경과 대표번호가 담긴 학습 데이터가 함께 필요하다.
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

# ---------- 주소(상세 주소) ----------
# NER만으로는 주소가 조각으로 잡혀서 **번지·동호수가 마스킹되지 않았다.** A의 주소
# 평가셋(ml/eval/address_eval, 200건)에서 우리 ner.py는 도로명·지번·동호수 150건 전부를
# "시·구·동" 조각으로만 잡았다 — "충청북도 청주시 흥덕구 조례동 278-24"에서 "278-24"가,
# "... 다온빌라 111동 1017호"에서 "111동 1017호"가 사본에 그대로 남는다. 사람을 특정하는
# 부분이 정확히 그 숫자들이다.
#
# 그래서 상세 주소 전체를 한 구간으로 잡는 정규식을 둔다. A의 프로토타입
# (ml/eval/address_eval/address_pattern.py)을 옮기되 **시·도·군·구가 최소 하나 앞에
# 오도록 바꿨다.** 실측(2026-09-14, 세 가지 조건 비교):
#                                 정답 주소   주소 아닌 문장   업무 문구 20개
#   A 원본 (행정구역 선택)          150/150      20/50 오탐       17개 오탐
#   지번만 행정구역 필수            150/150      20/50 오탐        1개 오탐
#   둘 다 행정구역 필수 (채택)      150/150       0/50 오탐        0개 오탐
# A 원본의 지번 규칙은 "이름+(동|가|읍|면|리)+숫자"라서 "단가 12000", "처리 2", "평가 4",
# "활동 3"처럼 업무 문서에 흔한 말이 전부 주소가 됐다. 오탐 학습 문장 344건에서도
# "번호가 016-3204", "정보가 416-59" 같은 전화·계좌 문맥 11곳이 주소로 잡혔다(채택안 0곳).
#
# 대신 **행정구역 없이 쓴 주소는 놓친다** — "본사는 테헤란로 152에 있습니다",
# "역삼동 737 소재 사옥". 이런 경우는 NER이 잡는 조각만 가려진다. 행정구역 없는
# 도로명까지 받으면 "문서 분류 코드 한밭대로 133", "해운대로 175번 구간" 같은 문장이
# 주소가 되어(위 20건) 이쪽을 버렸다.
#
# 번지 앞의 "지하"와 번지 뒤 괄호 속 참고항목도 주소의 일부로 받는다. 표준 도로명 주소가
# "세종대로 지하 110", "반포대로 993 (반포동)" 꼴로 적히기 때문이다. 데모 고객명단.xlsx에서
# 처음 규칙은 "봉은사7로 지하987" 꼴 3곳을 통째로 놓쳐 번지가 사본에 남았고, 괄호 속 동
# 이름은 NER이 "정마을"처럼 일부만 가려 앞글자가 남았다(2026-09-14 실측).
#
# 동·호수와 건물명은 적는 방식이 여럿이라 아래를 모두 받는다. 받기 전 사본(같은 날 실측):
#   "반포대로 지하 993 (반포동) 101동 202호" -> "[주소] 101동 202호"              괄호 뒤 동호수
#   "반포대로 993, 101동 202호(반포동)"      -> "[주소], 101[주소] 202호(반포동)"  쉼표
#   "판교로 235, 래미안아파트 103동 1502호" -> "[주소], 래미안아파트 103동 1502호"
#   "판교역로 235, 에이치스퀘어 N동 7층"     -> "…에이[주소]스퀘어 N[주소] 7층"    접미사 없는 건물명·영문 동
# 사람을 특정하는 부분이 정확히 이 동·호수라서, 규칙이 안 받으면 사본에 그대로 남는다.
# 접미사 없는 건물명은 바로 뒤에 동·층·호가 올 때만 받는다 — 주소 뒤 아무 단어나 삼키지 않게.
#
# 앞쪽 경계(?<!한글·영문·숫자)는 성능 때문에 필요하다. 없으면 띄어쓰기 없는 긴 한글열에서
# 모든 글자 위치마다 행정구역 이름을 처음부터 다시 맞춰 보느라 느려진다.
_ADDRESS_ADMIN_UNIT = r"[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구)"
_ADDRESS_ROAD_NAME = r"[가-힣A-Za-z0-9·]+(?:대로|로|길)(?:\d+번길)?"
_ADDRESS_JIBUN_NAME = r"[가-힣A-Za-z0-9·]+(?:동|가|읍|면|리)"
_ADDRESS_BUILDING = r"[가-힣A-Za-z0-9·]+(?:아파트|빌라|오피스텔|타워|주택)"
# 숫자와 동/층/호 사이의 공백까지 받는 이유: OCR이 한글 음절 사이에 공백을 끼워
# 넣는 경우가 흔하다(실측: 2026-09-17, 지원서 사진에서 "101동 101호"가 "101 동
# 101 호"로 읽혀, 공백 없는 패턴으로는 둘째 줄 전체가 안 이어 붙어 주소가 첫
# 줄에서 잘렸다). 공백이 없는 원래 형식도 `\s*`가 그대로 받아준다.
_ADDRESS_DONG = r"제?(?:\d+\s*|[A-Za-z]\s*|[가나다라마바사]\s*)동"
_ADDRESS_UNIT_DETAIL = rf"(?:(?:,\s*|\s+){_ADDRESS_DONG})?(?:\s+\d+\s*층)?(?:\s+\d+\s*호)?"
# 건물명 자리에 올 수 없는 말. 이 말 뒤에 층·호가 와도 건물명으로 받지 않는다.
# 없을 때 "세종대로 110 일대 3층", "… 인근 2층", "… 앞 1층 로비"가 통째로 주소가 됐다
# (2026-09-14 실측). 사본이 새지는 않지만 멀쩡한 본문이 가려진다.
_ADDRESS_NOT_BUILDING = r"(?!(?:일대|인근|근처|부근|주변|앞|옆|뒤|건너편|방면|일원|내|외)(?=\s))"
_ADDRESS_WORD_BEFORE_UNIT = (
    rf"{_ADDRESS_NOT_BUILDING}[가-힣A-Za-z0-9·]+(?=\s+(?:{_ADDRESS_DONG}|\d+\s*층|\d+\s*호))"
)
_ADDRESS_TAIL = (
    rf"(?:(?:,\s*|\s+)(?:{_ADDRESS_BUILDING}|{_ADDRESS_WORD_BEFORE_UNIT}))?"
    rf"{_ADDRESS_UNIT_DETAIL}"
    r"(?:\s*\([가-힣A-Za-z0-9·,\s]{1,30}\))?"
    rf"{_ADDRESS_UNIT_DETAIL}"
)
_ADDRESS_ROAD_BASE = rf"{_ADDRESS_ROAD_NAME}\s+(?:지하\s*)?\d+(?:-\d+)?"
_ADDRESS_JIBUN_BASE = rf"{_ADDRESS_JIBUN_NAME}\s+(?:산\s*|지하\s*)?\d+(?:-\d+)?"
ADDRESS_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z0-9])"
    rf"(?:{_ADDRESS_ADMIN_UNIT}\s+){{1,4}}"
    rf"(?:{_ADDRESS_ROAD_BASE}|{_ADDRESS_JIBUN_BASE})"
    rf"{_ADDRESS_TAIL}"
)

# 시·도·구 없이 쓴 주소("본사는 테헤란로 152에 있습니다", "거주지: 역삼동 737-12 302호").
# 형식만으로는 주소인지 알 수 없어서 **주소 앞 15자 안에 주소 단서어가 있을 때만** 받는다
# (find_addresses). 실측(2026-09-14). 정답은 A 평가셋 주소 150건에서 시·도·구를 떼어 만든 문장:
#                                          시·도·구 뗀 정답  주소 아닌 문장 50  업무 문구
#   조건 없이 받기(지번 전부)                    150             20 오탐       다수 오탐
#   NER이 같은 자리를 장소로 볼 때(지번 전부)      98              3 오탐       0
#   앞쪽 단서어 + 지번 전부                      120              0           3 오탐
#   앞쪽 단서어 + 도로명만                        60              0           0
#   앞쪽 단서어 + 도로명 + 동·읍·면 지번 (채택)  114              0           함정 17개 중 1
# 채택안의 114는 도로명 40/50, 지번 40/50, 동·호수 포함 34/50이다. 오탐 학습 문장 408건,
# 테스트·데모 문서 40개, 인젝션 평가셋 100건에서 새로 잡힌 것은 없었다.
#
# 단서어를 **앞에서만** 찾는 이유: A 평가셋의 까다로운 음성 문장은 "세종대로 11은 가상 주소
# 예시", "혁신로 297이며 실제 배송지가 아닙니다"처럼 단서어가 뒤에 온다.
# NER 조건을 쓰지 않은 이유: "버스 노선표에는 해운대로 175번 구간"처럼 도로명이면 문맥과
# 무관하게 장소로 잡혀 오탐이 났다.
# **지번은 이름이 동·읍·면으로 끝나고 3글자 이상일 때만** 받는다. 지번 모양 전부를 받으면
# "매장 관리 3건", "위치 정보 처리 2건", "본사 평가 4점"(…리·가 + 숫자)이 주소가 됐다. 3글자
# 조건은 "활동·이동·자동·변동" 같은 두 글자 말을 거른다. 대신 "사옥 이전 작업동 3층"의
# "작업동 3"처럼 세 글자 이상에 동으로 끝나는 말은 잡힌다(함정 문구 17개 중 1개).
#
# 한계: 앞에 단서어가 없는 주소("오시는 길: 테헤란로 152")는 여전히 못 잡는다(위 채택안에서
# 36건). 문맥 문장이 A 생성기의 틀이라 실제 문서에서는 수치가 다를 수 있고, 단서어 목록도 그
# 틀을 보고 정했다. "주소 예시로 혁신로 297을 사용"처럼 단서어가 앞에 오는 예시 문장은 잡힌다.
_ADDRESS_JIBUN_WITHOUT_ADMIN_BASE = (
    r"[가-힣A-Za-z0-9·]{2,}(?:동|읍|면)\s+(?:산\s*|지하\s*)?\d+(?:-\d+)?"
)
ADDRESS_WITHOUT_ADMIN_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z0-9])"
    rf"(?:{_ADDRESS_ROAD_BASE}|{_ADDRESS_JIBUN_WITHOUT_ADMIN_BASE})"
    rf"{_ADDRESS_TAIL}"
)
_ADDRESS_CUE = re.compile(
    r"주소|소재지|거주지|배송지|주소지|발송지|수령지|본사|사옥|사무실|지점|매장|위치|도로명|번지"
)
_ADDRESS_CUE_WINDOW = 15

# 번지 바로 뒤에 "층·호"가 붙으면 주소가 아니라 건물 안 층·호실이다("사옥 이전 작업동 3층",
# "본사 관리동 302호"). 앞의 "작업동·관리동"이 동으로 끝나서 지번 모양이 되지만, 실제 지번
# 번지는 숫자 바로 뒤에 층·호가 붙지 않는다. 실측(2026-09-14): 이런 문구 4개가 모두 주소로
# 잡혔고, 거른 뒤 0개. A 평가셋 주소는 시·도·구 있는 150/150, 없는 114/150 그대로였다.
_ADDRESS_NOT_FOLLOWED_BY = ("층", "호")

# NER이 지역명으로 잡은 조각에서 시작해 번지·동호수까지 이어지는 부분. 규칙이 못 잡은 주소를
# scan.py가 NER 조각에서부터 끝까지 가릴 때 쓴다(scan._split_place_mentions). 조각이 단어
# 중간에서 끝나도("테헤란" + "로 152") 단어 끝까지 먼저 채운다.
ADDRESS_CONTINUATION_AFTER_PLACE = re.compile(
    r"[가-힣A-Za-z0-9·]*\s*(?:지하\s*|산\s*)?\d+(?:-\d+)?" rf"{_ADDRESS_TAIL}"
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


def _looks_like_card_grouping(value: str) -> bool:
    """카드번호의 묶음 모양인지 본다. 계좌번호와 가르는 핵심 기준이다
    (_CARD_GROUP_SHAPES 주석의 실측 근거 참고)."""
    groups = re.split(r"[-\s]", value.strip())
    if len(groups) == 1:
        return len(groups[0]) >= _CARD_MIN_UNSEPARATED_DIGITS
    return tuple(len(g) for g in groups) in _CARD_GROUP_SHAPES


def find_card_numbers(text: str) -> list[dict]:
    """Luhn 체크섬을 통과하고 **카드번호의 묶음 모양**인 값만 반환한다.

    브랜드마다 자릿수가 다르다(Diners 14 / Amex 15 / Visa·Master·BC 16 / UnionPay
    19). 자릿수만 보면 14자리 구간에서 국내 은행 계좌와 충돌하므로, 구분자로 나뉜
    그룹 모양까지 함께 본다.
    """
    matches = []
    for m in CARD_NUMBER_PATTERN.finditer(text):
        if not _looks_like_card_grouping(m.group()):
            continue
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
        if _DATE_TIME_ACCOUNT_FALSE_POSITIVE.fullmatch(m.group()):
            continue
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


def _employee_numbers_from(pattern, text: str, confidence: float) -> list[dict]:
    return [
        {
            "field": "emp_no",
            "value": m.group(1),
            "start": m.start(1),
            "end": m.end(1),
            "confidence": confidence,
        }
        for m in pattern.finditer(text)
    ]


def find_employee_numbers(text: str) -> list[dict]:
    """라벨이 값 **앞**에 오는 사번을 잡는다("사번 EMP-03250").

    start/end는 라벨이 아니라 **값 부분만** 가리킨다 — 마스킹해야 하는 것은
    "사번:"이 아니라 그 뒤의 값이다. 값 형식에 제약이 거의 없어 체크섬은 없지만,
    라벨 단어가 바로 앞에 있다는 것 자체가 강한 근거라 확신도를 0.8로 둔다.
    """
    return _employee_numbers_from(EMPLOYEE_NUMBER_PATTERN, text, 0.8)


def find_employee_numbers_before_label(text: str) -> list[dict]:
    """라벨이 값 **뒤**에 오는 사번을 잡는다("EMP-03250 사원의 부서 이동").

    라벨이 뒤에 있으면 그 값이 사번이라는 근거가 한 단계 약하다. 앞에 오는 경우는
    "사번:" 다음 자리가 값으로 예약되어 있지만, 뒤에 오는 경우는 문장 안의 아무
    값이나 후보가 될 수 있기 때문이다. 그래서 확신도를 0.6으로 한 단계 낮추고,
    find_all이 다른 탐지 결과와 겹치는 후보를 버린다.
    """
    return _employee_numbers_from(EMPLOYEE_NUMBER_TRAILING_PATTERN, text, 0.6)


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


def find_addresses(text: str) -> list[dict]:
    """상세 주소(도로명·지번 + 번지, 동·층·호, 괄호 참고항목까지)를 한 구간으로 잡는다.

    두 경로가 있다.
      - 시·도·군·구로 시작하는 주소(ADDRESS_PATTERN) — 형식만으로 받는다.
      - 시·도·구 없이 쓴 도로명·지번 주소(ADDRESS_WITHOUT_ADMIN_PATTERN) — 앞쪽 15자 안에
        주소 단서어가 있을 때만 받는다. 첫 경로가 이미 잡은 구간과 겹치면 건너뛴다.

    검증 수단이 없는 형식 일치라 확신도는 전화번호·이메일과 같은 0.6이다. NER(ner.py)이
    같은 자리를 "서울특별시", "강남구"처럼 조각으로도 잡는데, 둘 다 address라 가중치가
    같고 scan.py의 _dedupe가 먼저 들어온 규칙 쪽(전체 구간)을 남긴다 — 그래서 번지·
    동호수까지 한 번에 가려진다.
    """
    with_admin = [
        {
            "field": "address",
            "value": m.group(),
            "start": m.start(),
            "end": m.end(),
            "confidence": 0.6,
            "reason": "시·도·구와 번지까지 갖춘 상세 주소 형식",
        }
        for m in ADDRESS_PATTERN.finditer(text)
        if text[m.end() : m.end() + 1] not in _ADDRESS_NOT_FOLLOWED_BY
    ]
    matches = list(with_admin)

    # 겹침 검사는 시·도·구 경로 결과를 포인터 하나로 앞에서부터 따라가며 한다. 두 경로 모두
    # 앞에서부터 겹치지 않게 결과를 내므로 한 번 훑으면 된다. 찾을 때마다 전체 목록과 비교하던
    # 처음 구현은 주소가 수천 개인 문서에서 제곱으로 느려졌다 — "본사 주소 테헤란로 1 "이
    # 반복되는 10만 자 입력에서 3.2초(2026-09-14 실측).
    index = 0
    for m in ADDRESS_WITHOUT_ADMIN_PATTERN.finditer(text):
        if text[m.end() : m.end() + 1] in _ADDRESS_NOT_FOLLOWED_BY:
            continue
        while index < len(with_admin) and with_admin[index]["end"] <= m.start():
            index += 1
        if index < len(with_admin) and with_admin[index]["start"] < m.end():
            continue
        if not _ADDRESS_CUE.search(text[max(0, m.start() - _ADDRESS_CUE_WINDOW) : m.start()]):
            continue
        matches.append(
            {
                "field": "address",
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "confidence": 0.6,
                "reason": "주소 단서어 뒤에 온 도로명·지번 주소 형식",
            }
        )
    return sorted(matches, key=lambda found: found["start"])


def find_all(text: str) -> list[dict]:
    """모든 필드 탐지기를 돌려서 하나의 목록으로 합친다.

    근거가 약한 탐지기 둘(라벨이 값 뒤에 오는 사번, 계좌번호)은 맨 마지막에 따로
    처리한다. 패턴이 넓어서 다른 번호를 통째로 삼키는데, scan.py의 dedupe는 위험
    가중치만 보기 때문에(계좌 30점 > 사업자등록번호 5점) **체크섬으로 검증된 쪽이
    밀려나** 오히려 오탐이 된다. 실제로 "123-45-67891"(체크섬 통과한 사업자등록번호)이
    확신도 0.3짜리 계좌번호로 표시되는 걸 확인했다.

    그래서 다른 탐지기가 이미 잡은 구간과 겹치는 후보는 여기서 버린다 — 계좌번호는
    "다른 무엇도 아닌 숫자"일 때만 계좌번호다. 사번(라벨이 뒤)을 계좌번호보다 먼저
    처리하는 이유는 둘이 서로 겹칠 수 있어서다(사번 쪽이 길이 3~12자로 더 좁다).
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
        + find_addresses(text)
        + find_birth_dates(text)
        + find_person_names_after_label(text)
    )
    def not_overlapping(candidates: list[dict], claimed: list[tuple[int, int]]) -> list[dict]:
        return [
            m
            for m in candidates
            if not any(m["start"] < end and start < m["end"] for start, end in claimed)
        ]

    claimed = [(m["start"], m["end"]) for m in findings]

    # 라벨이 값 뒤에 오는 사번도 근거가 약해 같은 취급을 한다. "010-1234-5678 직원
    # 연락처"의 전화번호가 사번으로 둔갑하는 것을 여기서 막는다.
    late = not_overlapping(find_employee_numbers_before_label(text), claimed)
    claimed += [(m["start"], m["end"]) for m in late]

    accounts = not_overlapping(find_bank_account_numbers(text), claimed)
    return findings + late + accounts
