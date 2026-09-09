# ml/data_generation/idcard_generators.py
import random

from ml.data_generation.generators import (
    fake,
    gen_name,
    gen_resident_number,
    gen_issue_date,
    format_date,
)

# --- 이름용 한자 풀 (실제 이름-한자 매칭 아님, 시각적 다양성용) ---
COMMON_HANJA = list(
    "金李朴崔鄭姜趙尹張林吳韓申徐權黃安宋柳洪全高文孫梁裵白曺許南沈盧河劉丁成車朱禹具任羅田閔兪池嚴蔡元千方孔康玄咸卞廉"
    "民洙昊俊賢珉志惠美善淑姬京泰東熙榮圭泳治弘相現承潤炫錫鎬憲燮昌敏廷智秀允柱河州"
)

def gen_hanja_for_name(name: str) -> str:
    length = len(name.replace(" ", ""))
    return "".join(random.choices(COMMON_HANJA, k=length))


# --- 주민등록증 발급기관 ("OO시장" 형식, 면허증의 "OO지방경찰청장"과 다름) ---
PROVINCES = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
    "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도",
    "경상북도", "경상남도", "제주특별자치도",
]
CITY_NAMES = [
    "양산", "진주", "김해", "창원", "포항", "경주", "안동", "순천", "여수", "목포",
    "청주", "천안", "전주", "군산", "춘천", "원주", "강릉",
]

def gen_issuing_authority() -> str:
    # 파일이 분리돼 있어서 면허증 쪽 gen_issuing_authority랑 이름 겹쳐도 문제없음
    province = random.choice(PROVINCES)
    city = random.choice(CITY_NAMES)
    return f"{province} {city}시장"


def gen_idcard_values() -> dict:
    name = gen_name()
    hanja = gen_hanja_for_name(name)
    address = fake.address().split("\n")[0].split(" (")[0]  # 한 줄만 사용
    issue_date = gen_issue_date()

    return {
        "name": f"{name}({hanja})",
        "resident_number": gen_resident_number(),
        "address": address,
        "issue_date": format_date(issue_date),
        "issuing_authority": gen_issuing_authority(),
    }