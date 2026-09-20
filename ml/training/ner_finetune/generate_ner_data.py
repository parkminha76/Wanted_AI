"""이름·회사명 NER 파인튜닝용 합성 학습 데이터를 만든다.

왜 필요한가
-----------
실측(2026-09-19~20, CSV·이미지 데모 파일 3종): `Leo97/KoELECTRA-small-v3-modu-ner`
(현재 backend/scanner/detectors/ner.py가 그대로 쓰는 사전학습 모델)가 자연스러운
문장에서는 사람 이름·회사명을 잘 잡지만(신뢰도 0.9대), CSV 행("ORD-2026-10234,
2026-09-01,오미정,010-3000-5000,...")이나 목록형 줄("1. 김지영 (넥스트브릿지)")
처럼 **짧고 맥락 없는 자리**에서는 이름을 통째로 놓치거나("오미정"→아예 안 잡힘)
끝 글자를 잘라 먹는다("양재호"→"양재"). 이 모델은 이 프로젝트가 학습시킨 적이
없는 순수 사전학습 모델이라(ml/training/ 아래 다른 셋과 달리 전용 폴더가 없었다),
같은 라벨 체계(B-PS/I-PS 사람, B-OG/I-OG 조직 등 — Leo97 모델의 id2label 그대로)
로 이런 "짧은 맥락" 문장을 더 넣어 파인튜닝하면 CSV·이미지 OCR 결과 둘 다 같이
좋아진다(같은 모델을 쓰기 때문).

무엇을 만드는가
---------------
(text, entities) 쌍의 JSONL이다. entities는 [start, end, label] 목록이고
label은 Leo97 라벨 체계의 "PS"(사람) 또는 "OG"(조직)다 — B-/I- 접두어는
학습 스크립트가 토큰화하면서 붙인다(이 파일은 문자 오프셋만 책임진다).

패턴은 실제로 겪은 실패 사례를 그대로 재현한다:
  - CSV 행(콤마로 이어붙인 여러 필드 사이에 이름이 낀 경우)
  - 번호 목록("1. 이름 (회사)")
  - 참석자 명단 두 줄 블록(이름 줄 + 연락처·이메일 줄)
  - 탭·파이프로 나눈 표 행
  - 라벨 없이 이름만 한 줄
자연스러운 문장(정상 케이스)도 일정 비율 섞는다 — 짧은 맥락만 넣으면 모델이
기존에 잘하던 자연스러운 문장 성능을 잃을 수 있다(파국적 망각). 하드 네거티브
(이름 자리에 이름이 아닌 값이 오는 경우)도 넣어 "그 자리는 무조건 이름"이라고
위치만으로 외우지 않게 한다.

실행:
    uv run python -m ml.training.ner_finetune.generate_ner_data
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from faker import Faker

random.seed(20260920)
fake = Faker("ko_KR")
Faker.seed(20260920)

OUT_DIR = Path(__file__).resolve().parent / "data"

# 접두어 20개 x 접미어 15개(=300 조합)로는 4000건짜리 학습셋에서 계속
# 재사용되어 모델이 "회사명 자리에 오는 특정 단어들"을 위치가 아니라 통째로
# 외워버릴 위험이 있다(과적합). Faker의 ko_KR company()가 훨씬 다양한
# 실제스러운 한국 회사명(주식회사/유한회사 포함, 지역명·업종명 조합)을
# 만들어주므로 이를 주 소스로 쓰고, 위 하드코딩 조합은 "접두어+접미어" 스타일
# 표기(참석자명단.png류에서 실제로 본 스타일)를 보조로 섞는 데만 쓴다.
_ORG_PREFIXES = [
    "한빛", "대한", "테크노", "블루웨이브", "넥스트브릿지", "그린필드", "실버라인",
    "골든게이트", "스카이라인", "베스트", "코어", "프라임", "센트럴", "유니온",
    "브라이트", "넥스젠", "이노", "스마트", "퓨처", "클리어", "한서", "동방",
    "신성", "우리", "미래", "다솜", "하나로", "은하", "청담", "가온",
]
_ORG_SUFFIXES = [
    "전자", "소프트", "메가", "솔루션", "시스템즈", "네트웍스", "테크", "정보통신",
    "물류", "바이오", "에너지", "컨설팅", "파트너스", "그룹", "인더스트리",
    "케미칼", "머티리얼즈", "모빌리티", "헬스케어", "미디어", "커머스", "로지스틱스",
]

# 회사명 뒤에 흔히 붙는 법인 표기 — Faker의 fake.company()가 만든 이름 앞에
# 붙은 "(주)"/"주식회사"/"유한회사" 등을 뗀 "맨 이름"도 섞어야, 문서에서
# 법인 표기 없이 회사명만 쓰는 경우(예: "넥스트브릿지에서 근무")도 학습된다.
_LEGAL_ENTITY_PREFIXES = ("(주) ", "(유) ", "주식회사 ", "유한회사 ")


def _gen_org() -> str:
    roll = random.random()
    if roll < 0.55:
        name = fake.company()
        if random.random() < 0.4:
            for legal_prefix in _LEGAL_ENTITY_PREFIXES:
                if name.startswith(legal_prefix):
                    name = name[len(legal_prefix):]
                    break
        return name
    prefix = random.choice(_ORG_PREFIXES)
    suffix = random.choice(_ORG_SUFFIXES)
    # "블루웨이브 솔루션"처럼 띄어 쓰는 경우와 "한빛전자"처럼 붙여 쓰는 경우 섞는다.
    return f"{prefix} {suffix}" if random.random() < 0.35 else f"{prefix}{suffix}"


def _gen_phone() -> str:
    return f"010-{random.randint(1000,9999)}-{random.randint(1000,9999)}"


def _gen_email(name_ascii: str) -> str:
    return f"{name_ascii}{random.randint(1,99)}@example.com"


# ---------------------------------------------------------------------------
# 패턴별 생성기. 전부 (text, entities) 하나를 돌려준다.
# ---------------------------------------------------------------------------


def _mark(text_parts: list[str], entities: list[list], value: str, label: str | None) -> None:
    """text_parts에 value를 이어붙이고, label이 있으면 그 구간을 entities에 기록한다."""
    start = sum(len(p) for p in text_parts)
    text_parts.append(value)
    if label:
        entities.append([start, start + len(value), label])


def gen_csv_row() -> tuple[str, list]:
    """실측 재현: 개발문서.md·주문내역.csv류. 콤마로 이어붙인 여러 필드 사이에
    이름이 낀다 — 앞뒤에 자연어 문맥이 전혀 없다."""
    parts: list[str] = []
    entities: list[list] = []
    order_id = f"ORD-2026-{random.randint(10000,99999)}"
    date = f"2026-{random.randint(1,12):02d}-{random.randint(1,28):02d} {random.randint(0,23):02d}:00"
    name = fake.name()
    phone = _gen_phone()
    product = random.choice(["무선 이어폰", "보조배터리", "텀블러", "노트북 파우치", "블루투스 스피커"])
    fields = [order_id, date]
    _mark(parts, entities, ",".join(fields) + ",", None)
    _mark(parts, entities, name, "PS")
    _mark(parts, entities, f",{phone},{product}", None)
    return "".join(parts), entities


def gen_numbered_list_with_org() -> tuple[str, list]:
    """실측 재현: 참석자명단.png. "1. 이름 (회사)" 형태."""
    parts: list[str] = []
    entities: list[list] = []
    idx = random.randint(1, 20)
    name = fake.name()
    org = _gen_org()
    _mark(parts, entities, f"{idx}. ", None)
    _mark(parts, entities, name, "PS")
    _mark(parts, entities, " (", None)
    _mark(parts, entities, org, "OG")
    _mark(parts, entities, ")", None)
    return "".join(parts), entities


def gen_attendee_two_lines() -> tuple[str, list]:
    """실측 재현: 참석자명단.png의 두 줄 블록(이름/소속 줄 + 연락처 줄)."""
    parts: list[str] = []
    entities: list[list] = []
    name = fake.name()
    org = _gen_org()
    phone = _gen_phone()
    email = _gen_email("guest")
    _mark(parts, entities, name, "PS")
    _mark(parts, entities, "  (", None)
    _mark(parts, entities, org, "OG")
    _mark(parts, entities, ")\n", None)
    _mark(parts, entities, f"{phone}    {email}", None)
    return "".join(parts), entities


def gen_table_row() -> tuple[str, list]:
    """실측 재현: 계약서.pdf·숨은명령.docx류 표 행. 탭 또는 파이프로 칸을 나눈다."""
    parts: list[str] = []
    entities: list[list] = []
    sep = random.choice(["\t", " | "])
    role = random.choice(["정산 문의", "계약 변경", "보안 신고", "기술 지원", "채용 문의"])
    name = fake.name()
    phone = _gen_phone()
    _mark(parts, entities, role + sep, None)
    _mark(parts, entities, name, "PS")
    _mark(parts, entities, sep + phone, None)
    return "".join(parts), entities


def gen_bare_label_value() -> tuple[str, list]:
    """실측 재현: "성명 이수인" 류. 라벨 바로 뒤에 이름만, 다른 문맥 없음."""
    parts: list[str] = []
    entities: list[list] = []
    label = random.choice(["성명", "담당자", "작성자", "수신인", "발신인", "계약 담당자"])
    name = fake.name()
    _mark(parts, entities, label + " ", None)
    _mark(parts, entities, name, "PS")
    return "".join(parts), entities


def gen_org_only_row() -> tuple[str, list]:
    """회사명만 짧은 맥락에 있는 경우(이름 없이)."""
    parts: list[str] = []
    entities: list[list] = []
    label = random.choice(["거래처", "공급사", "발주처", "협력사"])
    org = _gen_org()
    _mark(parts, entities, label + ": ", None)
    _mark(parts, entities, org, "OG")
    return "".join(parts), entities


def gen_natural_sentence() -> tuple[str, list]:
    """정상 케이스(자연스러운 문장) — 파인튜닝이 기존 성능을 깎지 않게 섞는다."""
    parts: list[str] = []
    entities: list[list] = []
    name = fake.name()
    org = _gen_org()
    template = random.choice([
        ("{name}님이 {org}에서 근무 중입니다.", ("name", "org")),
        ("{org} 소속 {name} 담당자에게 문의해 주세요.", ("org", "name")),
        ("이 계약은 {name}님과 {org}이 체결했습니다.", ("name", "org")),
        ("{name}입니다. 잘 부탁드립니다.", ("name",)),
        ("{org}은 올해 매출이 크게 늘었습니다.", ("org",)),
    ])
    sentence, order = template
    cursor = 0
    for key in order:
        literal = "{" + key + "}"
        idx = sentence.index(literal, cursor)
        _mark(parts, entities, sentence[cursor:idx], None)
        value = name if key == "name" else org
        _mark(parts, entities, value, "PS" if key == "name" else "OG")
        cursor = idx + len(literal)
    _mark(parts, entities, sentence[cursor:], None)
    return "".join(parts), entities


# 실측(2026-09-20): 이력서류 "2022 - 2023 Liceria & Co. 비 디자인 디자인팀"에서
# 학교명 필터 회귀 테스트(test_ner_school_exclusion.py)가 깨졌다 — 회사명 자체는
# 여전히 0.94로 잘 잡았지만, 이번 학습 데이터에 없던 "영문 회사명 + 바로 뒤에
# 붙는 한글 부서 접미어(팀/부/실/본부)" 조합에서 경계가 부서 접미어 중간까지
# 번져(ner.py의 "단어 중간에서 끊긴 조직명" 안전장치에 걸려 통째로 버려졌다.
# 순수 한글 회사명 생성기(_gen_org)만 계속 써서 영문 회사명 형태를 아예 학습에
# 안 넣은 게 원인으로 보인다 — 영문 회사명과 부서 접미어 경계를 같이 가르친다.
_ENGLISH_ORGS = [
    "Liceria & Co.", "Nomad Coders", "Bright Path Inc.", "Vertex Solutions",
    "Union Bay Ltd.", "Nova Systems", "Crestline Partners", "Argon Digital",
]
_DEPARTMENT_SUFFIXES = ["팀", "부", "실", "본부", "센터", "그룹"]


def gen_career_entry() -> tuple[str, list]:
    """실측 재현: 이력서 경력 목록 "연도범위 회사명. 부서명접미어" — 회사명
    경계가 바로 뒤에 붙는 부서 접미어(공백 없음) 앞에서 정확히 끊겨야 한다."""
    parts: list[str] = []
    entities: list[list] = []
    y1 = random.randint(2015, 2023)
    y2 = y1 + random.randint(1, 3)
    org = random.choice(_ENGLISH_ORGS) if random.random() < 0.5 else _gen_org()
    dept = random.choice(["디자인", "개발", "마케팅", "영업", "인사", "재무", "전략기획"])
    suffix = random.choice(_DEPARTMENT_SUFFIXES)
    _mark(parts, entities, f"{y1} - {y2} ", None)
    _mark(parts, entities, org, "OG")
    _mark(parts, entities, f". {dept}{suffix}", None)
    return "".join(parts), entities


def gen_hard_negative_csv_row() -> tuple[str, list]:
    """실측 재현: "이름 자리"에 이름이 아닌 값이 오는 하드 네거티브 — 위치만
    보고 무조건 이름으로 외우지 않게 막는다(쿠폰번호·접수번호 오탐 사례와
    같은 이유로, org/person 쪽도 대칭으로 넣는다)."""
    parts: list[str] = []
    entities: list[list] = []
    order_id = f"ORD-2026-{random.randint(10000,99999)}"
    date = f"2026-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
    not_a_name = random.choice(["무선 이어폰 세트", "보조배터리 20000mAh", "쿠폰 적용", "당일 배송"])
    phone = _gen_phone()
    _mark(parts, entities, f"{order_id},{date},", None)
    _mark(parts, entities, not_a_name, None)  # 라벨 없음 — 이름이 아니다
    _mark(parts, entities, f",{phone}", None)
    return "".join(parts), entities


# 실측(2026-09-20, docX-ray 배포본): gen_table_row("역할\t이름\t연락처")로 학습한
# 뒤, 계약서류 표에서 이름/회사명이 아닌 흔한 업무 라벨("법인카드", "검수",
# "정보보호" 등)까지 회사명(OG)으로 오탐하는 회귀가 생겼다 — "탭/파이프로 나뉜
# 첫 칸은 대체로 PS/OG"라고 위치만으로 과일반화한 것으로 보인다.
# gen_hard_negative_csv_row가 "이름 자리"의 하드 네거티브를 다루듯, 이번엔
# "표 라벨 자리"의 하드 네거티브를 대칭으로 넣는다 — 실제 계약서/보고서 표에
# 흔한 라벨들이고, 전부 개체명이 아니다(entities가 빈 리스트).
_TABLE_LABEL_HARD_NEGATIVES = [
    "법인카드", "검수", "정산", "정보보호", "승인", "접수", "발주", "납품",
    "품질보증", "손해배상", "비밀유지", "계약기간", "지급조건", "분쟁해결",
    "하자보수", "인수인계", "보안서약", "정산 계좌", "결제 방법", "배송 조건",
]


def gen_hard_negative_table_label() -> tuple[str, list]:
    """실측 재현: 계약서류 표에서 "법인카드\\t3991-..." 같은 라벨 자리를
    회사명으로 오탐하던 것 — 라벨은 개체명이 아니라고 대칭으로 가르친다."""
    parts: list[str] = []
    entities: list[list] = []
    sep = random.choice(["\t", " | "])
    label = random.choice(_TABLE_LABEL_HARD_NEGATIVES)
    value = random.choice([
        _gen_phone(),
        f"{random.randint(100,999)}-{random.randint(10,99)}-{random.randint(10000,99999)}",
        "월간 결과보고서 제출 후 5영업일 안에 검토한다",
        "업무 중 취득한 고객정보와 인증정보를 제3자에게 제공하지 않는다",
        f"{random.randint(1000,9999)}-{random.randint(1000,9999)}-{random.randint(1000,9999)}-{random.randint(1000,9999)}",
    ])
    _mark(parts, entities, label + sep + value, None)
    return "".join(parts), entities


_GENERATORS = [
    (gen_csv_row, 20),
    (gen_numbered_list_with_org, 20),
    (gen_attendee_two_lines, 15),
    (gen_table_row, 15),
    (gen_bare_label_value, 10),
    (gen_org_only_row, 10),
    (gen_natural_sentence, 15),
    (gen_hard_negative_csv_row, 8),
    (gen_hard_negative_table_label, 12),
    (gen_career_entry, 14),
]


def generate(n: int) -> list[dict]:
    weighted = []
    for generator, weight in _GENERATORS:
        weighted.extend([generator] * weight)

    seen_text: set[str] = set()
    examples = []
    attempts = 0
    while len(examples) < n and attempts < n * 5:
        attempts += 1
        generator = random.choice(weighted)
        text, entities = generator()
        if text in seen_text:
            continue
        seen_text.add(text)
        examples.append({"text": text, "entities": entities, "source": generator.__name__})
    return examples


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    examples = generate(4000)
    random.shuffle(examples)
    split = int(len(examples) * 0.9)
    train, val = examples[:split], examples[split:]

    for name, subset in (("train.jsonl", train), ("val.jsonl", val)):
        path = OUT_DIR / name
        with open(path, "w", encoding="utf-8") as fh:
            for example in subset:
                fh.write(json.dumps(example, ensure_ascii=False) + "\n")
        print(f"{path}: {len(subset)}건")

    by_source: dict[str, int] = {}
    for example in examples:
        by_source[example["source"]] = by_source.get(example["source"], 0) + 1
    print("패턴별 개수:", by_source)


if __name__ == "__main__":
    main()
