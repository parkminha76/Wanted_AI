"""InfoGuard 상세 주소 규칙 검증용 합성 평가 데이터 200건 생성.

학습 데이터가 아니다. B의 주소 탐지 규칙을 적용하기 전에 정확한 span과 일반
장소 오탐 여부를 재현 가능하게 확인하기 위한 고정 평가셋이다.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path


SEED = 20260913
DEFAULT_OUTPUT = Path("ml/eval/address_eval/address_cases.json")

REGIONS = [
    "서울특별시 강남구",
    "서울특별시 마포구",
    "부산광역시 해운대구",
    "대구광역시 수성구",
    "인천광역시 연수구",
    "광주광역시 북구",
    "대전광역시 유성구",
    "울산광역시 남구",
    "세종특별자치시",
    "경기도 성남시 분당구",
    "경기도 수원시 영통구",
    "강원특별자치도 춘천시",
    "충청북도 청주시 흥덕구",
    "충청남도 천안시 서북구",
    "전북특별자치도 전주시 완산구",
    "전라남도 순천시",
    "경상북도 포항시 북구",
    "경상남도 창원시 성산구",
    "제주특별자치도 제주시",
]

ROAD_NAMES = [
    "테헤란로", "판교로", "센텀중앙로", "대학로", "세종대로",
    "충장대로", "달구벌대로", "송도과학로", "법원로", "한밭대로",
    "중앙로", "도산대로", "영동대로", "가락시장길", "월드컵북로",
    "양재천로", "해운대로", "첨단과기로", "엑스포로", "누리로",
    "광교중앙로", "혁신로", "과학기술로", "산업단지로", "문화로",
    "판교로256번길", "양재천로19길", "서초중앙로8길", "동판교로52번길",
]

NEIGHBORHOODS = [
    "역삼동", "서교동", "우동", "범어동", "송도동", "용봉동", "궁동",
    "삼산동", "어진동", "백현동", "이의동", "효자동", "복대동", "불당동",
    "효자동3가", "조례동", "장성동", "상남동", "노형동", "애월읍", "조천읍",
    "남면", "북면", "청평리", "대정읍",
]

BUILDING_NAMES = [
    "한빛아파트", "푸른마을아파트", "새봄빌라", "센트럴오피스텔",
    "미래타워", "가온아파트", "누리주택", "해든아파트", "다온빌라",
    "솔빛아파트",
]

POSITIVE_TEMPLATES = [
    "배송지는 {value}입니다.",
    "계약서에 기재된 주소는 {value}입니다.",
    "반품 물품을 {value}로 보내주세요.",
    "신청인의 거주지는 {value}로 확인됩니다.",
    "세금계산서 수령 주소: {value}",
    "방문 예정지는 {value}이니 확인 바랍니다.",
    "고객 배송지 {value}로 접수했습니다.",
    "서류 발송지는 {value}입니다.",
    "사업장 소재지는 {value}로 등록되어 있습니다.",
    "비상 연락망의 자택 주소는 {value}입니다.",
]

PLACES = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기도", "강원도", "제주도", "강남역", "서울역", "광화문", "판교",
    "송도", "한강", "해운대", "인천공항", "제주공항", "테헤란로", "대학로",
    "홍대입구", "여의도", "남산",
]

NEGATIVE_TEMPLATES = [
    "이번 회의는 {value}에서 진행합니다.",
    "{value} 지역의 분기 매출을 분석했습니다.",
    "출장지는 {value}로 결정되었습니다.",
    "{value} 상권에 관한 보고서를 작성했습니다.",
    "행사는 {value} 인근에서 열릴 예정입니다.",
    "{value} 지사 직원이 온라인 회의에 참석했습니다.",
    "채용 대상 지역은 {value}입니다.",
    "이번 조사는 {value} 방문객을 대상으로 합니다.",
]

# 도로명과 숫자가 함께 있지만 실제 주소가 아닌 문장. 단순 정규식만으로는 이
# 문맥을 구분하기 어려우므로 규칙의 한계를 확인하는 hard negative로 둔다.
ADDRESS_LIKE_NEGATIVE_TEMPLATES = [
    "버스 노선표에는 {value}번 구간으로 표시되어 있습니다.",
    "교육 자료에서 {value}은 가상 주소 예시로만 사용했습니다.",
    "테스트 케이스 이름은 {value}이며 실제 배송지가 아닙니다.",
    "문서 분류 코드 {value}을 새 버전에서 폐기했습니다.",
    "회의에서는 {value}이라는 임의 문자열을 비교했습니다.",
]


def _record(text: str, value: str, label: int, kind: str, index: int) -> dict:
    start = text.index(value)
    return {
        "text": text,
        "type": "address",
        "start": start,
        "end": start + len(value),
        "label": label,
        "address_kind": kind,
        "source": "synthetic_address_eval",
        "group_id": f"{kind}_{index % 10:02d}",
    }


def _wrap(value: str, index: int) -> str:
    return POSITIVE_TEMPLATES[index % len(POSITIVE_TEMPLATES)].format(value=value)


def generate(seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []

    # 도로명 주소 50건
    for index in range(50):
        region = REGIONS[index % len(REGIONS)]
        road = ROAD_NAMES[(index * 7) % len(ROAD_NAMES)]
        number = 10 + ((index * 37) % 480)
        suffix = f"-{1 + index % 37}" if index % 4 == 0 else ""
        value = f"{region} {road} {number}{suffix}"
        rows.append(_record(_wrap(value, index), value, 1, "road", index))

    # 지번 주소 50건
    for index in range(50):
        region = REGIONS[(index * 3) % len(REGIONS)]
        neighborhood = NEIGHBORHOODS[(index * 5) % len(NEIGHBORHOODS)]
        mountain = "산 " if index % 7 == 0 else ""
        number = 1 + ((index * 29) % 390)
        suffix = f"-{1 + index % 48}" if index % 3 else ""
        value = f"{region} {neighborhood} {mountain}{number}{suffix}"
        rows.append(_record(_wrap(value, index + 50), value, 1, "jibun", index))

    # 아파트·동·호가 포함된 주소 50건
    for index in range(50):
        region = REGIONS[(index * 5) % len(REGIONS)]
        building = BUILDING_NAMES[index % len(BUILDING_NAMES)]
        dong = 101 + index % 18
        ho = (2 + index % 20) * 100 + 1 + (index * 7) % 20
        if index % 2 == 0:
            road = ROAD_NAMES[(index * 11) % len(ROAD_NAMES)]
            number = 20 + ((index * 31) % 350)
            base = f"{region} {road} {number}"
        else:
            neighborhood = NEIGHBORHOODS[(index * 7) % len(NEIGHBORHOODS)]
            number = 1 + ((index * 17) % 300)
            base = f"{region} {neighborhood} {number}"
        value = f"{base} {building} {dong}동 {ho}호"
        rows.append(_record(_wrap(value, index + 100), value, 1, "unit", index))

    # 도로명+숫자지만 문맥상 주소가 아닌 사례 20건. 정규식만으로 해결하기
    # 어려운 오탐을 일부러 포함해 평가가 지나치게 쉬워지는 것을 막는다.
    for index in range(20):
        road = ROAD_NAMES[(index * 3) % len(ROAD_NAMES)]
        number = 10 + ((index * 41) % 450)
        value = f"{road} {number}"
        template = ADDRESS_LIKE_NEGATIVE_TEMPLATES[index % len(ADDRESS_LIKE_NEGATIVE_TEMPLATES)]
        rows.append(_record(template.format(value=value), value, 0, "location_only", index))

    # 단순 장소명 30건: 주소로 가리면 안 되는 hard negative
    for index in range(30):
        value = PLACES[index % len(PLACES)]
        template = NEGATIVE_TEMPLATES[(index // len(PLACES) + index) % len(NEGATIVE_TEMPLATES)]
        text = template.format(value=value)
        rows.append(_record(text, value, 0, "location_only", index + 20))

    rng.shuffle(rows)
    validate(rows)
    return rows


def validate(rows: list[dict]) -> None:
    if len(rows) != 200:
        raise ValueError(f"정확히 200건이어야 함: {len(rows)}")
    if len({row["text"] for row in rows}) != len(rows):
        raise ValueError("중복 문장이 있음")
    counts = Counter(row["address_kind"] for row in rows)
    expected = {"road": 50, "jibun": 50, "unit": 50, "location_only": 50}
    if dict(counts) != expected:
        raise ValueError(f"종류별 건수가 다름: {dict(counts)}")
    for index, row in enumerate(rows):
        if row["label"] not in (0, 1):
            raise ValueError(f"{index}: label 오류")
        start, end = row["start"], row["end"]
        if not 0 <= start < end <= len(row["text"]):
            raise ValueError(f"{index}: start/end 범위 오류")
        if not row["text"][start:end].strip():
            raise ValueError(f"{index}: 후보 span이 비어 있음")


def main() -> None:
    parser = argparse.ArgumentParser(description="주소 규칙 검증용 합성 평가셋 생성")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    rows = generate(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"저장: {args.output}")
    print("총 200건: road=50, jibun=50, unit=50, location_only=50")


if __name__ == "__main__":
    main()
