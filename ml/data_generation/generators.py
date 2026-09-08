# ml/data_generation/generators.py
from faker import Faker
import random
import datetime

fake = Faker("ko_KR")

LICENSE_REGION_CODES = list(range(11, 22))  # 서울11 ~ 제주21
VEHICLE_CLASSES = ["1종보통", "1종대형", "1종특수", "2종보통", "2종소형", "원동기장치자전거"]
POLICE_AGENCIES = [
    "서울지방경찰청장", "부산지방경찰청장", "인천지방경찰청장",
    "경기남부지방경찰청장", "경기북부지방경찰청장", "대구지방경찰청장",
]


def gen_name() -> str:
    return fake.name()


def gen_resident_number() -> str:
    while True:
        ssn = fake.ssn()
        mm, dd = ssn[2:4], ssn[4:6]
        if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
            return ssn


def gen_issue_date() -> datetime.date:
    # 최근 10년 이내 랜덤 날짜. datetime.date 객체로 리턴해야
    # 뒤에서 .year 뽑거나 연산할 때 편함 (문자열이면 매번 다시 파싱해야 해서 번거로움)
    return fake.date_between(start_date="-10y", end_date="today")


def format_date(d: datetime.date) -> str:
    # 카드에 찍히는 "2025.02.03." 형식으로 변환
    return d.strftime("%Y.%m.%d.")


def gen_license_number(issue_date: datetime.date) -> str:
    region = random.choice(LICENSE_REGION_CODES)          # AA
    year2 = str(issue_date.year)[2:]                       # BB - 발급일자 연도랑 맞춤
    serial = str(random.randint(0, 999999)).zfill(6)       # CCCCCC - 6자리 고정(0으로 채움)
    check = str(random.randint(0, 9))                      # D - 공식 비공개라 랜덤
    reissue_count = "1"                                    # E - 최초발급 가정

    return f"{region:02d}-{year2}-{serial}-{check}{reissue_count}"


def gen_expiry_date(issue_date: datetime.date) -> datetime.date:
    # 적성검사 주기 10년 가정 (dateutil 없이 처리 - 2/29 같은 극단적 케이스는 무시해도 되는 수준)
    try:
        return issue_date.replace(year=issue_date.year + 10)
    except ValueError:
        # issue_date가 2/29(윤년)인 매우 드문 경우 대비
        return issue_date.replace(month=2, day=28, year=issue_date.year + 10)


def gen_address() -> list[str]:
    raw = fake.address()  # 보통 "OO특별시 OO구 OO로 123 (OO동)" 형식

    if " (" in raw:
        line1, rest = raw.split(" (", 1)
        line2 = "(" + rest
    else:
        # 괄호 없는 주소가 나오는 경우 대비 - 그냥 한 줄로만 채움
        line1, line2 = raw, ""

    return [line1, line2]


def gen_driver_license_values() -> dict:
    issue_date = gen_issue_date()
    address_lines = gen_address()

    return {
        "name": gen_name(),
        "resident_number": gen_resident_number(),
        "license_number": gen_license_number(issue_date),
        "address": "\n".join(address_lines),
        "issue_date": format_date(issue_date),
        "expiry_date": format_date(gen_expiry_date(issue_date)),
        "vehicle_class": gen_vehicle_class(),
        "aptitude_label": "적성검사",
        "aptitude_test_date": gen_aptitude_test_date(issue_date),
        "period_label": "기    간 :  ~",        # ← "기"와 "간" 사이 스페이스 추가
        "condition_label": "조    건 :",         # ← 새로 추가
        "secondary_code": gen_secondary_code(),
        "issuing_authority": gen_issuing_authority(),
    }

def gen_vehicle_class() -> str:
    return random.choice(VEHICLE_CLASSES)


def gen_aptitude_test_date(issue_date) -> str:
    # 적성검사일은 보통 발급일 근처라 issue_date 그대로 재사용해도 무방함
    return format_date(issue_date)


def gen_secondary_code() -> str:
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # 헷갈리는 I,O 제외 (실제 이런 코드들이 보통 이렇게 함)
    letter1 = random.choice(letters)
    digits = str(random.randint(0, 999)).zfill(3)
    letter2 = random.choice(letters)
    return f"{letter1}{digits[0]}{digits[1:]}{letter2}"  # 예: "NV676V" 형태


def gen_issuing_authority() -> str:
    return random.choice(POLICE_AGENCIES)


if __name__ == "__main__":
    for _ in range(3):
        print(gen_driver_license_values())