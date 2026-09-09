import random

# (한글 성, 영문 로마자 표기) 짝지어서 관리 - 서로 다른 사람처럼 안 보이게
SURNAME_PAIRS = [
    ("홍", "HONG"), ("김", "KIM"), ("이", "LEE"), ("박", "PARK"),
    ("최", "CHOI"), ("정", "JUNG"), ("강", "KANG"), ("조", "CHO"),
    ("윤", "YOON"), ("장", "JANG"), ("임", "LIM"), ("한", "HAN"),
    ("오", "OH"), ("서", "SEO"), ("신", "SHIN"), ("권", "KWON"),
    ("황", "HWANG"), ("안", "AHN"), ("송", "SONG"), ("전", "JEON"),
    ("유", "YOO"), ("고", "KO"), ("문", "MOON"), ("양", "YANG"),
    ("손", "SON"), ("배", "BAE"), ("백", "BAEK"), ("허", "HEO"),
    ("남", "NAM"), ("심", "SIM"), ("노", "NOH"), ("하", "HA"),
    ("곽", "KWAK"), ("성", "SUNG"), ("차", "CHA"), ("주", "JOO"),
    ("우", "WOO"), ("구", "KOO"), ("민", "MIN"), ("류", "RYU"),
]

# (한글 이름, 영문 로마자 표기) 짝
GIVEN_PAIRS = [
    ("길순", "GILSOON"), ("민준", "MINJUN"), ("서연", "SEOYEON"), ("지호", "JIHO"),
    ("유나", "YUNA"), ("도윤", "DOYUN"), ("수빈", "SUBIN"), ("하은", "HAEUN"),
    ("준서", "JUNSEO"), ("지우", "JIWOO"), ("서준", "SEOJUN"), ("예은", "YEEUN"),
    ("민서", "MINSEO"), ("지민", "JIMIN"), ("예준", "YEJUN"), ("서윤", "SEOYUN"),
    ("하준", "HAJUN"), ("지안", "JIAN"), ("은우", "EUNWOO"), ("시우", "SIWOO"),
    ("다은", "DAEUN"), ("채원", "CHAEWON"), ("지훈", "JIHOON"), ("현우", "HYUNWOO"),
    ("소율", "SOYUL"), ("예린", "YERIN"), ("수아", "SUA"), ("민재", "MINJAE"),
    ("유진", "YUJIN"), ("승우", "SEUNGWOO"), ("은서", "EUNSEO"), ("우진", "WOOJIN"),
    ("채은", "CHAEEUN"), ("도현", "DOHYUN"), ("지원", "JIWON"), ("현서", "HYUNSEO"),
    ("정민", "JUNGMIN"), ("성민", "SUNGMIN"), ("재현", "JAEHYUN"), ("소연", "SOYEON"),
    ("나윤", "NAYUN"), ("아름", "AREUM"), ("동현", "DONGHYUN"), ("가은", "GAEUN"),
]

MONTHS_EN = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()

# 종류(Type) 코드 - 실제 분포에 가깝게 PM(일반 복수여권)이 압도적 비중,
# 나머지(PS 단수/PD 외교관/PO 관용)는 소수만 섞어서 다양성 확보
DOC_TYPES = ["PM", "PS", "PD", "PO"]
DOC_TYPE_WEIGHTS = [90, 5, 3, 2]


def gen_passport_number():
    return "M" + "".join(random.choices("0123456789", k=8))


def gen_mrz(doc_type: str, surname_en: str, given_en: str, passport_no: str,
            dob_yymmdd: str, sex: str, expiry_yymmdd: str) -> str:
    """
    실제 TD3 MRZ 포맷(2줄 x 44자).
    1번째 줄 시작은 '종류(Type)' 필드값 그대로 써야 함 (예: PM) - 하드코딩 금지.
    """
    line1 = f"{doc_type}KOR{surname_en}<<{given_en}"
    line1 = (line1 + "<" * 44)[:44]

    check = lambda: str(random.randint(0, 9))
    line2 = (
        passport_no.ljust(9, "<")[:9] + check() +
        "KOR" +
        dob_yymmdd + check() +
        sex +
        expiry_yymmdd + check() +
        "<" * 14 + check() +
        check()
    )
    line2 = (line2 + "<" * 44)[:44]
    return line1 + "\n" + line2


def gen_passport_values() -> dict:
    doc_type = random.choices(DOC_TYPES, weights=DOC_TYPE_WEIGHTS, k=1)[0]

    kor_surname, en_surname = random.choice(SURNAME_PAIRS)
    kor_given, en_given = random.choice(GIVEN_PAIRS)
    korean_name = kor_surname + kor_given

    passport_no = gen_passport_number()

    birth_year = random.randint(1970, 2005)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    dob_yymmdd = f"{birth_year % 100:02d}{birth_month:02d}{birth_day:02d}"
    dob_display = f"{birth_day:02d} {birth_month}월/{MONTHS_EN[birth_month-1]} {birth_year}"

    sex = random.choice(["M", "F"])

    issue_year = random.randint(2021, 2025)
    issue_display = f"15 8월/AUG {issue_year}"
    valid_years = 1 if doc_type == "PS" else 10  # PS(단수여권)만 유효기간 1년, 나머지는 10년
    expiry_year = issue_year + valid_years
    expiry_display = f"15 8월/AUG {expiry_year}"
    expiry_yymmdd = f"{expiry_year % 100:02d}0815"

    mrz = gen_mrz(doc_type, en_surname, en_given, passport_no, dob_yymmdd, sex, expiry_yymmdd)

    return {
        "type": doc_type,
        "nationality": "REPUBLIC OF KOREA",
        "passport_number": passport_no,
        "surname": en_surname,
        "given_names": en_given,
        "korean_name": korean_name,
        "date_of_birth": dob_display,
        "sex": sex,
        "issue_date": issue_display,
        "expiry_date": expiry_display,
        "mrz": mrz,
    }