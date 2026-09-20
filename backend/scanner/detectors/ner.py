"""한국어 NER(개체명 인식)로 이름/주소/조직명을 잡는다. 정규식으로는 못 잡는,
형식이 없는 값을 담당한다(형식이 고정된 값은 rules.py가 담당).

모델 선정 (ner_benchmark.py로 4개 후보를 실측 비교했다 — 2026-09-09)
----------------------------------------------------------------------
선택: Leo97/KoELECTRA-small-v3-modu-ner

    모델                                 로딩      추론/문장   커버리지
    Leo97/KoELECTRA-small (56MB)        1.65초    11.3ms     100%
    KPF/KPF-bert-ner (455MB)            1.85초    51.5ms     100%
    monologg/koelectra-base             1.86초    47.7ms     100%
    vmaca123/korean-pii-ner-v3 (1.3GB)  29.72초   197.2ms     94.7%

- 네 후보 중 가장 가볍고(56MB) 가장 빠르다. "10/5까지 배포 링크가 살아있어야
  한다"는 조건에서, 무거운 모델은 로딩 자체가 배포 리스크다.
- 라벨이 모두의말뭉치 표준 태그셋(B-PS/I-PS 등)으로 이미 정리되어 있어 바로 쓸 수
  있다.
- KPF-bert-ner는 후보에서 제외했다: HuggingFace에 올라간 config.json의 라벨이
  LABEL_0~LABEL_299로 전부 익명 처리되어 있다. 실제 인물/기관/지명이 몇 번
  라벨인지 매핑표를 별도 GitHub 저장소에서 구해와야 쓸 수 있는데, 로딩시간보다
  이쪽이 더 큰 리스크라 판단했다.
- koelectra-base-v3-naver-ner는 라벨은 정리되어 있지만 base 모델이라 무겁다.
  small 모델의 정확도가 부족하면 다음 후보로 바꿔 끼운다 — 모델 이름은 아래
  MODEL_NAME 상수 하나만 바꾸면 된다.
- korean-pii-ner-v3는 라벨이 NAME/ADDRESS/ORG로 우리 필요와 정확히 맞아떨어져
  기대했지만, 실측에서 세 지표 모두 꼴찌라 탈락했다(위 표 참고).

모델 로딩은 첫 detect() 호출 때 한 번만 하고 캐싱한다. import 시점에 바로
불러오면, 모델이 아직 캐시되지 않았거나 네트워크가 막힌 환경에서 `import ner`
자체가 실패해 scan.py 전체가 멎는다.

긴 문서는 반드시 잘라서 넣는다. 이 모델의 입력 한도는 512토큰인데, 넘겨도
예외가 나지 않고 경고만 찍힌 뒤 뒷부분이 조용히 버려진다. 실측으로 4,700자
문서(2,305토큰)에서 앞쪽 이름 하나만 잡히고 중간·뒤쪽 이름 둘을 놓쳤다.
고객 명단 같은 문서에서 이건 "앞의 몇 명만 마스킹하고 안전한 사본이라고
내보내는" 사고가 된다.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

_BASE_MODEL_NAME = "Leo97/KoELECTRA-small-v3-modu-ner"

# 2026-09-20: 짧은 맥락(CSV 행, 번호 목록, 참석자 명단 두 줄 블록)에서 이름/
# 회사명을 놓치거나 끝 글자를 잘라 먹던 문제를, 같은 라벨 체계로 이어서 학습
# (continued fine-tuning)한 모델로 고쳤다 — ml/training/ner_finetune/README나
# 학습 스크립트 참고. 실측(주문내역.csv "오미정"/"양재호", 참석자명단.png류
# 문장)으로 베이스 대비 신뢰도가 뚜렷이 올라간 것을 확인했고, 자연스러운
# 문장에서의 원래 성능도 유지됨을 확인했다(파국적 망각 없음).
_FINETUNED_MODEL_DIR = Path(__file__).resolve().parents[3] / "ml" / "models" / "ner_person_org_v1"
_USING_FINETUNED_MODEL = _FINETUNED_MODEL_DIR.is_dir()
MODEL_NAME = str(_FINETUNED_MODEL_DIR) if _USING_FINETUNED_MODEL else _BASE_MODEL_NAME

# 2026-09-20 실측(계약서.pdf 실서비스 스캔): 파인튜닝 모델이 "법인카드"·"검수"
# 오탐은 고쳤지만, 짧은 영문 단어·주소 조각·문서 자체 텍스트("월간", "docX",
# "Security", "Approval", "오탐"조차)를 회사명으로 잘못 잡는 사례가 남아 있었다.
# 건마다 하드 네거티브를 추가하는 건 끝이 없다 — 대신 실제 계약서.pdf 전체를
# 스캔해 회사명 신뢰도를 정렬해보니, 진짜 회사명(블루웨이브 솔루션·넥스트브릿지
# 등)은 전부 0.94~0.99인 반면 이런 오탐은 전부 0.85 이하로 뚜렷이 갈렸다
# (0.89 "한빛타워"만 예외처럼 보이지만 이것도 주소 일부라 실제로는 오탐이다).
# 베이스 모델(파인튜닝 전)은 이 임계값을 적용하면 안 된다 — 기존 실측(주석
# 참고, "공인" 필터 관련)에서 진짜 회사명 "네이버"가 0.364로 나온 적이 있어,
# 베이스 모델의 신뢰도 분포는 파인튜닝 모델과 다르다. 그래서 파인튜닝 모델을
# 쓸 때만 적용한다.
_FINETUNED_ORG_MIN_CONFIDENCE = 0.90

# 한 번에 모델에 넣을 최대 글자 수. 한국어는 대략 2글자당 1토큰이라 400자면
# 200토큰 안팎으로, 512 한도에 충분한 여유가 있다.
_MAX_CHARS_PER_CHUNK = 400

# transformers Pipeline은 문자열 목록을 받으면 내부에서 묶어 추론한다. XLSX는 셀
# 하나가 chunk 하나라 고객명단.xlsx 한 파일에서 300회 넘게 모델을 따로 호출했는데,
# Railway에서는 이 순차 호출이 프록시 응답 제한을 넘겨 502가 났다. 셀 경계는 입력
# 목록의 각 원소로 그대로 유지하면서 이 개수만큼 묶어 호출한다.
# Railway의 소형 인스턴스에서는 32개 배치가 모델·토큰 텐서와 함께 메모리 한도를
# 넘겨 컨테이너가 재시작됐다. 로컬 실측은 8개(1.162초)와 32개(1.124초)의 차이가
# 0.04초뿐이라, 처리량보다 배포 안정성을 우선해 8개로 제한한다.
_BATCH_SIZE = 8

# 모두의말뭉치 NER 태그 -> schema.RiskType. 개인정보와 무관한 태그(날짜/수량/
# 이론/인공물 등)는 매핑에서 빼서 자동으로 버려지게 한다.
_TAG_TO_RISK_TYPE: dict[str, str] = {
    "PS": "person",
    "LC": "address",
    "OG": "org",
}

_pipeline = None
_pipeline_lock = threading.Lock()


def _get_pipeline():
    """모델을 한 번만 불러와 캐싱한다.

    2026-09-20 실측(Railway 배포): 락 없이 `if _pipeline is None`만 보면,
    콜드 스타트 직후 여러 요청(XLSX는 셀마다 detect()를 부른다)이 거의 동시에
    들어올 때 전부 캐시가 비어 있는 걸 보고 각자 모델을 처음부터 새로
    불러온다 — 배포 로그에 "Loading weights: 0%"가 같은 몇 초 사이 수십 번
    반복해서 시작되는 것으로 확인됐다. 작은 인스턴스에서 이게 동시에 겹치면
    CPU를 서로 뺏어가며 몇 초면 끝날 로딩이 수 분으로 늘어나고, `/samples`
    처럼 여러 파일을 한 요청 안에서 훑는 경로는 아예 Railway의 프록시 타임아웃
    (5분)을 넘겨버린다. 락으로 첫 스레드만 실제로 불러오고 나머지는 그 결과를
    기다리게 한다.
    """
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                from transformers import pipeline

                _pipeline = pipeline(
                    "token-classification",
                    model=MODEL_NAME,
                    aggregation_strategy="simple",
                )
    return _pipeline


_HANGUL_PATTERN = re.compile(r"[가-힣]")


def _iter_segment_chunks(text: str, segment_start: int, segment_end: int):
    """탭·줄바꿈으로 분리된 한 구간을 모델 입력 크기에 맞춰 나눈다.

    한글이 한 글자도 없는 조각은 건너뛴다. 실측(2026-09-20, 4,442,184자·2만
    5천 줄짜리 로그 파일): request_id·client_ip·phone·email 같은 필드가
    반복되는 줄마다 NER 입력이 하나씩 생겨(줄당 약 176자, 줄바꿈이 강제
    경계라) 배치 추론이 3천 번 넘게 돌아 180초를 넘겼다. 이 모델이 사람
    이름·회사명으로 잡는 값은 이 프로젝트가 다루는 문서에서 전부 한글이
    섞여 있다(외국 회사명도 "Liceria & Co. 비 디자인 디자인팀"처럼 한글
    문맥과 같이 나온다 — 실측 사례). 전화번호·이메일·IP처럼 형식이 고정된
    값은 이 필터와 무관하게 rules.py가 정규식으로 전체 파일을 그대로
    훑으므로(NER을 거치지 않는다), 한글 없는 로그 줄을 건너뛰어도 그
    탐지에는 영향이 없다.
    """
    start = segment_start
    while start < segment_end:
        end = min(start + _MAX_CHARS_PER_CHUNK, segment_end)
        if end < segment_end:
            boundary = max(text.rfind(c, start, end) for c in ".!?")
            if boundary <= start:
                boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary + 1
        chunk = text[start:end]
        if chunk.strip() and _HANGUL_PATTERN.search(chunk):
            yield chunk, start
        start = end


def _iter_chunks(text: str):
    """모델 입력 한도를 넘지 않게 자르고, 각 조각의 원문 시작 위치도 같이 돌려준다.

    탭과 줄바꿈은 먼저 강제 경계로 취급한다. XLSX의 서로 다른 셀은 파서에서 탭으로
    이어지므로 한 번에 모델에 넣으면 이름과 다음 셀을 하나의 인물명으로 합칠 수 있다.
    셀·문단을 넘는 NER 결과는 마스킹 범위까지 넓혀 실제 내용을 지우므로 입력 단계에서
    차단한다.
    """
    for segment in re.finditer(r"[^\t\r\n]+", text):
        yield from _iter_segment_chunks(text, segment.start(), segment.end())


_REPEAT_MIN_LENGTH = {"person": 3, "org": 4}

# 학교명(대학교/고등학교 등)은 마스킹 대상에서 뺀다 — 사용자 결정(2026-09-17):
# 전화번호·주소·생년월일과 달리 학교명은 이력서·이력서 공개 정보에 흔히 그대로
# 쓰이고, 그 자체로는 연락·사칭 같은 위험으로 이어지지 않는다. 게다가 NER이
# "조직명" 태그 하나로 회사명과 학교명을 구분 없이 잡다 보니 학교마다 걸리고
# 안 걸리는 게 들쭉날쭉해서(실측: 같은 문서에서 "신안산대학교"는 잡히고
# "안산고등학교"는 안 잡힘), 지금 상태로 두면 보호 효과보다 일관성 없어 보이는
# 부작용이 크다.
#
# "학교"로 끝나면 초등학교/중학교/고등학교/대학교를 전부 잡는다. "대학"만으로
# 끝나는 옛 표기(전문대학 등)도 따로 받는다.
_EDU_INSTITUTION_SUFFIXES = ("학교", "대학")


def _is_education_institution(text: str, start: int, end: int) -> bool:
    """[start, end) 구간(과 바로 뒤 몇 글자)이 학교명으로 끝나는가.

    NER 토크나이저가 학교명의 꼬리("학교")를 통째로 잘라 개체를 내놓는 경우가
    실측으로 확인됐다(예: "신안산대학교"에서 "신안산대"만 조직명으로 잡힘).
    잡힌 범위 뒤에 몇 글자를 더 붙여봐도 학교 접미사가 완성되면 같은 학교명으로
    본다 — 잘린 범위만 보면 "학교"가 아예 안 보여서 놓친다.
    """
    value = text[start:end]
    if value.endswith(_EDU_INSTITUTION_SUFFIXES):
        return True
    lookahead = value + text[end : end + 3]
    return lookahead.endswith(_EDU_INSTITUTION_SUFFIXES)


# 단독으로는 절대 회사명이 아닌, 자격/인증을 뜻하는 흔한 수식어. 실측(2026-09-18,
# 저해상도 이력서 사진 865f267df9c220bf.jpg): "자격증" 섹션의 자격증 이름이 OCR로
# "공인 임어시럽"처럼 깨져 읽혔는데(원문은 아마 "컴활 1급시험" 류), 모델이 그
# 문맥에서 "공인"만 떼어 회사명으로 오판했다(확신도 0.401). 신뢰도로 거르면 안
# 된다 — 같은 문서 밖 실측에서 진짜 회사명 "네이버"도 0.364로 이보다 낮게 나와서,
# 확신도 기준을 올리면 진짜 회사명까지 함께 놓친다. "공인"은 "공인중개사"·
# "공인회계사"처럼 항상 뒤에 명사가 붙어야 뜻이 서는 말이라, 그 자체로 단독
# 개체(회사명)가 되는 일이 사실상 없다 — 값이 정확히 이 목록과 같을 때만 뺀다.
#
# 2026-09-20 실측(docX-ray 배포본, 계약서류 여러 건): 파인튜닝 모델이 표 라벨·
# 마크다운 메타데이터·법률 조항 제목("제1조 (목적)", "제2조 (정산)") 같은 자리에
# 오는 짧은 한국어 업무 용어를 회사명으로 반복해서 오탐했다 — 매번 신뢰도가
# 0.94~0.98로 높아 _FINETUNED_ORG_MIN_CONFIDENCE로도 못 거르고, 문서 구조가
# 표/목록/조항 제목 등으로 계속 바뀌어 학습 데이터에 패턴을 추가해도 다음 구조에서
# 또 나왔다(법인카드→검수→한함→대상 환경→목적/정산 순으로 계속 발견됨). 재학습을
# 반복하는 대신, 실제로 회사명이 될 수 없는 흔한 업무 용어를 여기 직접 등록해
# 구조와 무관하게 확정적으로 막는다. "공인"과 같은 기준 — 값이 정확히 일치할
# 때만 뺀다(값 일부로 포함된 진짜 회사명까지 지우지 않도록).
_ORG_STANDALONE_MODIFIERS = {
    "공인",
    "목적", "정산", "검수", "승인", "접수", "발주", "납품", "비밀유지",
    "법인카드", "정보보호", "한함", "해당사항", "특이사항",
    "대상 환경", "문서 상태", "작업 일시", "작성자", "검토자", "버전",
    "하이픈 없는",
}

# 한국 사람 이름의 모양. 성 한 글자 + 이름 1~3글자라 2~4자를 벗어나지 않는다.
#
# 왜 형태로 거르나: 확신도로는 못 가른다. 실측(2026-09-20, 데모 문서 4종)에서
# 보통명사 '오류율'·'시연용'이 0.99로 잡혔는데 진짜 이름 '박진우'도 0.99였다.
# 같은 자리에 있어서 문턱을 올리면 진짜 이름이 먼저 떨어진다.
_PERSON_NAME_LENGTH = (2, 4)

# 흔한 한국 성. NER이 보통명사를 이름으로 내놓을 때 첫 글자가 성이 아닌 경우가 많다
# (실측: '시연용'의 시, '별지'의 별). 성으로 시작하지 않으면 이름으로 보지 않는다.
_KOREAN_SURNAMES = frozenset(
    "김이박최정강조윤장임한오서신권황안송전홍고문손양배백허남심노하곽성차주우구"
    "라민유진지엄채원천방공현함변염여추도소석선설마길연위표명반왕금옥육인맹제탁국어편"
)

# 이름 끝에 거의 오지 않으면서 보통명사를 만드는 꼬리. 실측에서 걸린 '기준일'·
# '정산기준일'의 일, '시연용'의 용이 여기 해당한다.
#
# '율'은 일부러 뺐다 — '하율'·'서율'·'채율'처럼 요즘 흔한 이름의 끝 글자라,
# 넣으면 진짜 이름을 놓친다. 그래서 '오류율'은 이 규칙으로 못 거른다(아래 보고 참고).
_PERSON_NOUN_TAIL = ("일", "용", "함")


def _looks_like_person_name(value: str) -> bool:
    """사람 이름의 모양을 갖췄는가. 한글 이름만 판단하고 그 외는 그대로 통과시킨다."""
    value = value.strip()
    if not value or not all("가" <= ch <= "힣" for ch in value):
        return True  # 외국어 이름 등은 이 규칙으로 판단하지 않는다
    low, high = _PERSON_NAME_LENGTH
    if not low <= len(value) <= high:
        return False
    if value[0] not in _KOREAN_SURNAMES:
        return False
    return not value.endswith(_PERSON_NOUN_TAIL)


_ORG_SUFFIX_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z0-9])"
    r"(?:주식회사\s+)?[가-힣A-Za-z0-9·]{2,}"
    r"\s+(?:솔루션|테크놀로지|테크|글로벌|그룹)"
    r"(?:\s+주식회사)?(?![가-힣A-Za-z0-9])"
)


# 회사임을 스스로 밝히는 표기. 한글·영문 양쪽을 본다.
_ORG_EVIDENCE_WORDS = (
    "주식회사", "㈜", "솔루션", "테크놀로지", "테크", "글로벌", "그룹", "코퍼레이션", "홀딩스",
    "Co", "Inc", "Ltd", "LLC", "Corp", "Company", "GmbH", "PLC",
)


def _drop_latin_orgs_without_marker(findings: list[dict]) -> list[dict]:
    """한글이 하나도 없는 조직명 후보는 회사 표기가 붙어 있을 때만 남긴다.

    실측(2026-09-20, 데모 문서 4종): 'PDF'(0.92)·'DOCX'(0.97)·'docX'(0.92)·
    'health'(0.98)가 조직명으로 잡혔다. 전부 파일 형식이나 경로 조각이다. 확신도는
    진짜 회사명과 같은 자리에 있어서 문턱으로는 못 가른다.

    한글 문서에 섞인 짧은 영문 토큰은 회사명보다 약어·파일 형식일 때가 훨씬 많다.
    그래서 영문만으로 된 후보는 'Co.'·'Inc.' 같은 표기를 달고 있을 때만 받는다 —
    'Liceria & Co.'는 남고 'PDF'는 빠진다.

    한글이 섞인 후보는 건드리지 않는다. '카카오'처럼 꼬리말 없이도 회사명인 경우가
    흔해서(test_ner_org_standalone_modifiers) 같은 잣대를 들이대면 진짜 회사명이 죽는다.

    남는 한계: '마스킹'·'한함'처럼 한글 보통명사가 조직명으로 잡히는 것은 이 규칙으로
    못 거른다. person/org를 오탐 제거 분류기에 학습시키는 것이 제대로 된 해법이다.
    """
    kept = []
    for item in findings:
        value = item["value"].strip()
        if item["field"] != "org" or any("가" <= ch <= "힣" for ch in value):
            kept.append(item)
            continue
        if any(word.lower() in value.lower() for word in _ORG_EVIDENCE_WORDS):
            kept.append(item)
    return kept


def _expand_repeated_entities(text: str, findings: list[dict]) -> list[dict]:
    """확실히 잡힌 이름·회사명의 동일 문서 내 반복 표기를 함께 반환한다."""
    expanded = list(findings)
    seeds: dict[tuple[str, str], float] = {}
    for item in findings:
        risk_type = item["field"]
        value = item["value"].strip()
        if len(value) < _REPEAT_MIN_LENGTH.get(risk_type, 10**9):
            continue
        key = (risk_type, value)
        seeds[key] = max(seeds.get(key, 0.0), float(item["confidence"]))

    for (risk_type, value), confidence in seeds.items():
        for match in re.finditer(re.escape(value), text):
            expanded.append(
                {
                    "field": risk_type,
                    "value": text[match.start() : match.end()],
                    "start": match.start(),
                    "end": match.end(),
                    "confidence": round(confidence, 3),
                }
            )

    for match in _ORG_SUFFIX_PATTERN.finditer(text):
        expanded.append(
            {
                "field": "org",
                "value": match.group(),
                "start": match.start(),
                "end": match.end(),
                "confidence": 0.85,
            }
        )
    return expanded


def detect(text: str) -> list[dict]:
    """rules.py와 같은 형식으로 반환한다: [{field, value, start, end, confidence}, ...]"""
    pipe = _get_pipeline()
    findings = []
    chunks = list(_iter_chunks(text))
    if not chunks:
        return []

    # 문자열을 하나씩 호출하면 XLSX 셀 수만큼 Python/모델 호출 비용이 반복된다.
    # 목록 배치는 각 셀을 독립 문장으로 처리하므로 개체가 셀 경계를 넘어 합쳐지지
    # 않으며, 아래 offset 보정도 기존과 같다.
    outputs = pipe([chunk for chunk, _ in chunks], batch_size=_BATCH_SIZE)
    for (_, offset), entities in zip(chunks, outputs):
        for entity in entities:
            risk_type = _TAG_TO_RISK_TYPE.get(entity["entity_group"])
            if risk_type is None:
                continue
            start = offset + entity["start"]
            end = offset + entity["end"]

            # 모델이 표의 "서명" 열 제목까지 인물명으로 합치는 경우가 있다.
            # 실제 이름 뒤의 UI/문서 라벨은 마스킹하지 않도록 경계를 되돌린다.
            if risk_type == "person":
                for suffix in (" 서명", " 날인"):
                    if text[start:end].endswith(suffix):
                        end -= len(suffix)
                        break
                # 사람 이름의 모양을 갖추지 못한 보통명사를 뺀다(_looks_like_person_name).
                if not _looks_like_person_name(text[start:end]):
                    continue

            # 영문 토큰 중간에서 시작·끝난 조직명(InfoGuard -> foGuard)은 모델의
            # 토큰 경계 오류다. 한 글자 조직명 "주"도 회사명으로 쓰지 않는다.
            if risk_type == "org":
                # 표의 필드명까지 조직명으로 합치는 결과("수행사 주식회사")에서는
                # 발주사·수행사 같은 라벨을 남기고 실제 조직 부분만 사용한다.
                leading_label = re.match(
                    r"(?:발주사|수행사|공급사|협력사|회사명|업체명|조직명)\s+",
                    text[start:end],
                )
                if leading_label:
                    start += leading_label.end()
                if end - start < 2:
                    continue
                if start > 0 and text[start - 1].isalnum() and text[start].isalnum():
                    continue
                if end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
                    continue
                if _is_education_institution(text, start, end):
                    continue
                if text[start:end] in _ORG_STANDALONE_MODIFIERS:
                    continue
                if (
                    _USING_FINETUNED_MODEL
                    and float(entity["score"]) < _FINETUNED_ORG_MIN_CONFIDENCE
                ):
                    continue

            if end <= start:
                continue
            findings.append(
                {
                    "field": risk_type,
                    # entity["word"] 대신 원문에서 잘라 쓴다. 토크나이저가 복원한
                    # 문자열은 원문과 미세하게 달라질 수 있는데, 그러면 마스킹이
                    # 그 값을 원문에서 못 찾는다. 오프셋과 값이 항상 일치해야 한다.
                    "value": text[start:end],
                    "start": start,
                    "end": end,
                    "confidence": round(float(entity["score"]), 3),
                }
            )
    # "주식회사"와 바로 뒤 회사명이 별도 개체로 나온 경우 한 범위로 합친다.
    # 공백 외 문자가 사이에 있으면 서로 다른 조직일 수 있으므로 합치지 않는다.
    merged = []
    for item in sorted(findings, key=lambda finding: finding["start"]):
        if (
            merged
            and item["field"] == "org"
            and merged[-1]["field"] == "org"
            and not text[merged[-1]["end"] : item["start"]].strip()
            and "\n" not in text[merged[-1]["end"] : item["start"]]
        ):
            merged[-1]["end"] = item["end"]
            merged[-1]["value"] = text[merged[-1]["start"] : item["end"]]
            merged[-1]["confidence"] = max(merged[-1]["confidence"], item["confidence"])
        else:
            merged.append(dict(item))
    return _expand_repeated_entities(text, _drop_latin_orgs_without_marker(merged))
