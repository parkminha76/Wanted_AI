"""신분증이 아닌 일반 이미지(인보이스, 스크린샷, 디자인 이력서 등) 안의 글자를
OCR로 읽어 텍스트 파이프라인(rules.py/ner.py/models.py)을 그대로 돌린다.

왜 필요한가
-----------
id_detector.py(CNN)는 신분증 사진에 고정된 12개 영역(얼굴·주민번호·서명 등)만
찾도록 학습됐다. 얼굴도 신분증도 없는 일반 문서 사진(인보이스, 채팅 스크린샷,
영수증)을 올리면 CNN이 찾을 게 하나도 없어서 findings가 비고, 위험점수 0(안전)으로
나간다 — 그런데 그 안에 전화번호·계좌번호 같은 진짜 개인정보가 그대로 있을 수 있다
(실측: 2026-09-17, 인보이스 PNG에 전화번호·계좌번호가 있었는데 마스킹이 전혀 안 됨).

접근
----
EasyOCR로 이미지 속 글자를 읽어 raw_text를 다시 만들고(각 단어가 raw_text의 어느
구간에서 왔는지도 같이 기록한다), scan.scan_text()를 그대로 불러 문서 텍스트와
똑같은 정확도(정규식+체크섬, NER, 인젝션, 오탐 제거)로 판정한다. 새 판정 로직을
따로 만들지 않는다 — 같은 값이라도 이미지에서 왔다고 다르게 판단할 이유가 없고,
로직을 둘로 쪼개면 한쪽만 개선되고 다른 쪽은 뒤처진다.

찾은 값의 offset(raw_text 기준)을 다시 그 단어(들)의 픽셀 bbox로 되짚어 돌려준다.
masking/mask.py의 `_mask_image`는 출처와 무관하게 bbox만 있으면 칠하므로, 여기서
새로 만질 코드가 없다.

Tesseract에서 EasyOCR로 바꾼 이유(2026-09-18)
----------------------------------------------
Tesseract는 스캔한 문서·인쇄물처럼 "밝은 배경 + 어두운 글씨"인 단순한 이미지를
전제로 만들어진 엔진이다. 캔바·미리캔버스류 이력서 템플릿처럼 화려한 배경
무늬·장식 폰트·아이콘이 섞인 그래픽 디자인에서는 실측으로 확인된 것만도 이만큼
있었다 — 히어로 타이틀("최태오")이 완전히 다른 글자("EM"·"2")로 읽힘, 페이지
전체를 한 번에 읽을 때만 특정 줄의 특정 글자가 통째로 사라짐("최태오의 발자취"
→"최 오의 발자취"), 위치 핀 아이콘 옆 "서울특별시"에서 "서"가 통째로 사라짐,
장식 아이콘이 "ITQAAS AS — |" 같은 글자로 오인식되어 인젝션 분류기를 오탐시킴.
이런 문제들은 --psm 값을 바꾸거나 잘라서 재시도하는 식으로 부분적으로만
완화됐을 뿐 근본적으로 해결되지 않았다(배포 환경에서는 Tesseract 엔진
버전(5.5.0 vs 5.5.3)만 달라도 같은 이미지를 다르게 읽는 사고까지 있었다 —
Dockerfile 참고). EasyOCR(딥러닝 기반 검출+인식)로 바꾸자 같은 이미지 2장에서
위 문제가 전부 한 번에 해결됐다(실측 비교). 기울어진 사진(`_deskew`가 하던 일)도
EasyOCR의 검출기가 회전에 강해 별도 보정 없이 바로 읽는다.

한계
----
- OCR이 아예 못 읽은 글자(너무 흐리거나 장식체와 겹친 경우)는 애초에 텍스트로
  변환되지 않으므로 탐지할 수 없다. 이런 경우 CNN처럼 "확신 있게 안전"이라고
  말할 수 없다 — 이미지 검사는 원래 완전하지 않다는 한계를 그대로 갖는다.
- 값이 여러 줄에 걸치면(주소 등) bbox를 그 줄들을 모두 감싸는 사각형 하나로
  만든다. 그 사각형 안에 값과 무관한 다른 글자가 끼어 있으면 같이 가려진다 —
  PDF의 evidence["rects"](줄마다 따로)보다 거칠지만, 값을 덜 가리는 쪽보다는
  안전한 방향이다.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

# 한국어 문서이므로 한국어를 기본으로 하되 영어 라벨(Invoice, CHOI-TAEO 등)도
# 같이 읽는다.
_EASYOCR_LANGS = ["ko", "en"]

# 이 밑은 잡음으로 보고 버린다. 배경 장식 무늬(반복되는 옅은 글자 등)가 실측
# (2026-09-18, 이력서 사진 2장)에서 0.01~0.24 확신도로 잡혔고, 실제 값은 가장
# 낮은 것도 0.41이었다 — 둘 사이에 뚜렷한 간격이 있어 0.3을 문턱으로 쓴다.
_EASYOCR_MIN_CONFIDENCE = 0.3

# 표 안에 긴 문단이 통째로 들어간 셀(자기소개서 등)은 글자가 작고 줄도 많아서
# 정상적으로 적힌 진짜 내용인데도 확신도가 낮게 나온다(실측: 2026-09-18, 지원서
# 사진의 "지원동기" 문단 — "저는 식품 공장에서... 홍길동입니다: A식품 B식품"
# 줄이 확신도 0.21로 잡혀 0.3 문턱에 걸려 raw_text에서 통째로 빠졌다. 그 안의
# "A식품"/"B식품"은 바로 위 표에서 이미 회사명으로 확정된 값이었는데도 문단
# 쪽에서는 안 가려졌다). 그렇다고 전체 문턱을 낮추면 장식 배경 잡음(위 주석의
# 0.01~0.24대 글자들)까지 raw_text에 섞여 NER·인젝션 분류기가 오판할 자리가
# 늘어난다(실측: 2026-09-18, 그런 잡음이 "ITQAAS AS — \|"처럼 읽혀 인젝션
# 분류기를 오탐시킨 적이 실제로 있었다).
#
# 그래서 문턱을 두 단계로 나눈다 — 이 낮은 문턱은 `_find_cross_referenced_values`
# 전용이다: 표에서 이미 확정된 값과 **정확히 같은 문자열**을 찾는 데만 쓰므로,
# 이 문턱으로 걸러낸 잡음이 섞여 있어도(잡음이 우연히 "A식품"과 똑같은 문자열일
# 리는 없다) NER·인젝션 판정에는 전혀 들어가지 않아 위 오탐 경로가 열리지 않는다.
_CROSS_REFERENCE_MIN_CONFIDENCE = 0.15

# 서식류(인보이스·명세서)는 "라벨 줄" 다음에 "값 줄"이 따로 오는 경우가 흔하다
# ("입금 계좌" 다음 줄에 "국민 6127-02-384915"). 줄마다 무조건 줄바꿈으로 끊으면
# 값 줄에는 "계좌"라는 단어가 없어서, 오탐 제거 분류기가 문맥만 보고 진짜
# 계좌번호를 주문번호 같은 하드 네거티브로 착각한다(실측: 2026-09-17, 이
# 인보이스에서 계좌번호가 통째로 걸러짐 — prob_positive 0.444). 숫자도 문장부호도
# 없는 짧은 줄은 "라벨"로 보고 다음 줄과 공백으로 이어 붙여, 분류기가 라벨과 값을
# 한 문맥으로 보게 한다.
#
# 원래 12자까지 받았는데, 그러면 실제 서식 라벨("입금계좌" 4자, "생년월일" 4자,
# "연락처" 3자 — 전부 5자 이하)보다 훨씬 긴, 문장에 가까운 문구까지 "라벨"로
# 오인된다(실측: 2026-09-18, 이력서 히어로 타이틀 "고미리입니다"(6자)가 라벨로
# 잡혀 다음 줄["개인정보"/"학력사항"]에 공백으로 이어붙었고, "고미리입니다"가
# 그 뒤 문맥에 묻혀 NER이 이름을 못 알아봤다 — 단독으로 두면 잡힘). 실제 관찰된
# 라벨 중 가장 긴 것(5자)보다 살짝만 여유를 두고, 이름·문구가 우연히 여기
# 걸리지 않도록 좁힌다.
_LABEL_MAX_LEN = 5
_LABEL_DISALLOWED = re.compile(r"[0-9.!?]")
_HANGUL = re.compile(r"[가-힣]")

# 라벨처럼 보이는 줄이라도, 실은 서로 멀리 떨어진 항목 여러 개가 우연히 같은
# 가로 줄로 묶인 것일 수 있다(실측: 2026-09-18, 2단 이력서 레이아웃에서 왼쪽
# "개인정보"와 오른쪽 "학력사항"이 같은 세로 위치라 `_group_into_rows`가 한
# 줄로 묶었고, 둘 다 각자 "라벨처럼 보여서" 다음 줄["고미리" 이름이 있는
# 줄]까지 공백으로 이어붙었다 — "개인정보 학력사항 고미리 2008 2011
# 예지디자인고등학교"라는 뒤죽박죽 문맥이 되어 NER이 "고미리"를 이름으로
# 못 알아봤다, 같은 이름을 단독으로 넣으면 잡힌다). 진짜 한 라벨 문구는 단어
# 사이 간격이 좁다 — 이 배수보다 넓게 떨어진 항목이 줄 안에 하나라도 있으면
# 서로 다른 열이 우연히 한 줄로 묶인 것으로 보고 라벨 취급하지 않는다.
_LABEL_INTERNAL_GAP_RATIO = 2.0

# 이미지 OCR이 숫자 "0"을 글자 "O"로 잘못 읽는 경우가 있다(실측: 2026-09-18,
# 전화번호 "010-000-0000"이 "010-000-0OOO"로 읽혀 전화번호 정규식이 마지막
# 네 자리를 숫자로 못 봐서 통째로 놓침). 숫자가 최소 하나는 섞인 연속 구간
# 안에서만 O/o를 0으로 되돌린다 — 그런 구간 밖의 "O"(예: 영문 단어 속 글자)는
# 건드리지 않는다.
_DIGIT_CONFUSABLE_RUN = re.compile(r"[0-9Oo]{2,}")

# 실제 개인정보 값(전화번호·계좌번호·이름)은 항상 본문 크기로 적힌다는 전제가
# 이력서 히어로 타이틀처럼 이름 자체를 큰 제목으로 인쇄하는 디자인에는 안 맞는다
# (실측: 2026-09-18). 그래서 오버사이즈 판정은 더 이상 글자를 버리는 데 쓰지
# 않고, org(회사명) 오탐만 가리는 데 쓴다 — 예전 인보이스 제목 "INVOICE"가
# 회사명으로 오탐되던 사례(`detect()` 참고)를 막는 용도로만 남긴다.
_OVERSIZED_HEIGHT_RATIO = 1.8

# 같은 "줄"로 볼 세로 중심 오차 허용치. 두 검출의 세로 중심이 (그 줄 높이 ×
# 이 비율) 이내로 가까우면 같은 줄로 묶는다 — 표 헤더처럼 한 행에 칸이 여러 개
# 나란히 있으면 칸마다 검출이 따로 나오는데, 그것들을 하나의 줄로 다시 모아야
# `_find_table_column_cells`가 열 경계를 계산할 수 있다.
_ROW_CENTER_TOLERANCE = 0.6

# 헤더 문구가 검출 두 개로 쪼개지는 경우("주요"+"업무")를 다시 붙이는 데 쓴다
# (`_merge_touching_header_cells` 참고). 글자 높이의 이 비율보다 가까우면
# "붙어 있다"로 본다.
_TOUCHING_GAP_RATIO = 0.9

# 표에 헤더 행이 있으면("회사명 | 기간 | 경력 | 소속") NER의 자유 텍스트 추론보다
# 헤더가 열의 의미를 훨씬 정확히 알려준다. 실측(2026-09-17): NER이 옆 칸("경력"
# 열, 실제 값 "UI 디자인")의 OCR 오독 글자("UI"→"비")를 회사명 개체 끝에 붙여
# "Liceria & Co. 비"로 잡았고(마스킹 박스가 어중간하게 끊겨 "디자인"이 그대로
# 드러나 보임), 같은 열의 "Fauget"은 아예 회사명으로 인식하지 못해 마스킹에서
# 빠졌다. "회사명"/"직장명" 헤더가 있으면 그 열 전체를 기하학적으로(헤더 밑
# 같은 x축 범위) 확정해서 이 두 문제를 같이 없앤다.
#
# "학교명"은 일부러 안 넣는다 — 학교명은 마스킹 대상이 아니다(ner.py의
# 학교명 제외 결정과 일관, `_is_education_institution` 참고).
_COLUMN_FIELD_LABELS: dict[str, str] = {
    "회사명": "org",
    "직장명": "org",
    "근무처": "org",
}

# 표 헤더 밑으로 몇 줄까지 데이터 행으로 볼지의 안전판. 정상적인 표라면 세로
# 간격 검사(`_TABLE_ROW_GAP_RATIO`)가 먼저 걸리지만, 혹시 그게 안 걸리는
# 경우에도 표 밖 문단 전체를 끝없이 훑는 사고는 막는다.
_MAX_TABLE_ROWS = 20

# 이번 줄과 이전 줄 사이 세로 간격이 지금까지 본 행 높이 중앙값의 이 배수를
# 넘으면 표를 벗어난 것으로 본다. 가로 겹침만으로는 표가 폭이 넓을 때(다음
# 섹션 제목도 왼쪽 정렬이면 겹쳐 보임) 잘 안 걸려서 보조 신호로만 같이 쓴다.
_TABLE_ROW_GAP_RATIO = 1.75

# "경력정보" 같은 목록형 섹션(표 헤더 없이 "연도 - 연도  회사 설명" 줄이 나열된
# 형태)에서 쓴다. `_COLUMN_FIELD_LABELS`와 달리 표 열이 아니라 섹션 제목이다
# (실측: 2026-09-18, 이력서 사진 — "경력정보" 밑에 이런 목록이 있었는데 NER이
# "디자인전략 매직 디자인 인수"는 아예 못 잡고 "리우나 주거디자인 콘텐츠
# 마케팅"은 사람 이름으로 잘못 잡았다). `_find_career_list_entries` 참고.
_CAREER_LIST_HEADERS: dict[str, str] = {
    "경력정보": "org",
    "경력사항": "org",
    "근무경력": "org",
    "직장경력": "org",
}

# 헤더보다 이만큼 왼쪽까지는 "같은 열"로 본다. 2단 레이아웃에서 왼쪽 칸 글자가
# 같은 가로줄에 섞여 들어오는 걸 걸러내는 데 쓴다(`_find_career_list_entries`
# 주석의 "전산운용기능사" 실측 사례 참고) — 헤더 자신보다 왼쪽에 있는 글자는
# 다른 열의 내용일 가능성이 크다.
_CAREER_LIST_COLUMN_MARGIN = 40.0

# 실측(2026-09-18, 865f267df9c220bf.jpg): "회사명" 열 값과 "소속" 열 값 사이
# 가로 간격이 줄 높이(14px)의 12배가 넘었다(176px). 반면 진짜 여러 단어짜리
# 회사명은 EasyOCR이 한 덩어리로 검출해 애초에 이 정도로 벌어질 일이 없다 —
# 넉넉히 5배를 문턱으로 잡는다.
_CAREER_LIST_VALUE_GAP_RATIO = 5.0

# 항목이 "연도 - 연도"로 시작하는지 볼 때 쓴다. 4자리 두 개를 그대로 요구한다
# — "수상경력"의 "2008. 06"(연도 + 월)과 모양이 달라서, 이 패턴이 옆 섹션까지
# 잘못 삼킬 위험이 낮다.
_BARE_YEAR = re.compile(r"^(?:19|20)\d{2}$")

# 실측(2026-09-18, 저해상도 이력서 사진 865f267df9c220bf.jpg): "연도 - 연도"가
# 항상 두 칸으로 따로 검출되는 게 아니다 — 같은 문서 안에서도 어떤 줄은
# "2022"/"2023"로 갈리고, 어떤 줄은 "2020 - 2021"처럼 한 칸으로 통째로
# 검출됐다(구분자도 "-"뿐 아니라 저해상도 오독으로 "2024 * 2025"처럼 "*"가
# 나오기도 한다). 한 칸짜리도 놓치지 않는다.
_YEAR_RANGE_MERGED = re.compile(r"^(?:19|20)\d{2}\s*[-*~–—]\s*(?:19|20)\d{2}$")

# 헤더 아래로 몇 줄까지 훑을지, 줄 사이 간격이 얼마나 벌어지면 목록을 벗어난
# 것으로 볼지 — `_MAX_TABLE_ROWS`/`_TABLE_ROW_GAP_RATIO`와 같은 값을 그대로 쓴다.
_CAREER_LIST_MAX_ROWS = _MAX_TABLE_ROWS
_CAREER_LIST_ROW_GAP_RATIO = _TABLE_ROW_GAP_RATIO


def _find_career_list_entries(lines: list[list[tuple[str, tuple]]]) -> list[dict]:
    """"경력정보" 같은 목록형 섹션에서 "연도 - 연도" 뒤에 오는 글자를 회사명으로 잡는다.

    `_find_table_column_cells`는 "회사명" 같은 열 헤더가 있는 진짜 표에만 쓸 수
    있다. 표가 아니라 목록인 섹션은 그런 헤더가 없어 NER에 기대야 하는데,
    NER이 이 모양의 회사명(짧은 고유명사+일반명사 조합, 조사 없는 나열문)에
    약하다는 게 이 세션에서 거듭 확인됐다(`디자인전략 매직 디자인 인수`,
    `리우나 주거디자인 콘텐츠 마케팅` 등). 대신 이 섹션의 항목이 전부
    "연도 - 연도  회사 설명" 형태라는 구조를 이용해 기하학적으로 잡는다 —
    NER 추론이 아니라 `_find_table_column_cells`와 같은 접근이다.

    2단 레이아웃이라 같은 가로줄에 왼쪽 칸("자격증" 등)의 글자가 같이 잡힐 수
    있다(실측: "2008.03 전산운용기능사"와 "2006 2009 (주) MD..."가 한 줄로
    묶임). 그래서 헤더와 같은 x축(그 왼쪽 경계 근처)에 있는 단어만 후보로
    보고, 그보다 왼쪽에 있는 다른 열의 글자는 애초에 뺀다.

    값의 bbox는 문자 위치 비례 계산(`_bbox_for_range`)이 아니라 그 항목에
    실제로 걸린 단어들의 bbox를 그대로 합친 것이다 — 단어 하나하나가 이미
    분리돼 있어서 근사가 필요 없다.

    "경력정보"/"경력사항" 같은 섹션 제목은 진짜 표(예: "기간"/"회사명"/"경력"/
    "소속" 열 헤더가 있는 표)의 제목으로도 쓰인다(실측: 2026-09-18, "이력서"
    샘플 — `_find_table_column_cells`가 이미 정확히 처리하는 문서인데, 이
    함수가 "경력사항"이라는 같은 제목만 보고 또 훑다가 "회사명"·"경력"·"소속"
    여러 칸의 글자를 한 값으로 뭉쳐 잡았다). 그래서 훑을 구간 안에
    `_match_header_labels`가 인식하는 진짜 열 헤더 행이 하나라도 있으면, 그건
    표라는 뜻이므로 이 섹션 전체를 건너뛴다 — `_find_table_column_cells`가
    이미 담당한다.
    """
    results: list[dict] = []
    for header_index, line in enumerate(lines):
        header = next(
            ((text, bbox) for text, bbox in line if text in _CAREER_LIST_HEADERS), None
        )
        if header is None:
            continue
        header_text, header_bbox = header
        field = _CAREER_LIST_HEADERS[header_text]
        column_left = header_bbox[0] - _CAREER_LIST_COLUMN_MARGIN

        window = lines[header_index + 1 : header_index + 1 + _CAREER_LIST_MAX_ROWS]
        if any(_match_header_labels(row) for row in window):
            continue

        row_heights = [header_bbox[3] - header_bbox[1]]
        previous_bottom = header_bbox[3]
        for row in window:
            top, bottom = _line_span(row)
            gap = top - previous_bottom
            if gap > statistics.median(row_heights) * _CAREER_LIST_ROW_GAP_RATIO:
                break
            row_heights.append(bottom - top)
            previous_bottom = bottom

            column_words = [(text, bbox) for text, bbox in row if bbox[0] >= column_left]
            if len(column_words) < 2:
                continue
            first_text, _first_bbox = column_words[0]
            if (
                len(column_words) >= 3
                and _BARE_YEAR.match(first_text)
                and _BARE_YEAR.match(column_words[1][0])
            ):
                remainder = column_words[2:]
            elif _YEAR_RANGE_MERGED.match(first_text) and len(column_words) >= 3:
                # "연도 - 연도"가 한 칸으로 통째로 검출된 경우. 뒤에 최소
                # 두 칸은 더 있어야 한다 — 한 칸만 남았을 때 그 칸이 회사명이
                # 아니라 다른 열(예: "경력"란의 업무 설명)일 위험이 있어서다
                # (실측: 같은 문서의 다른 줄에서 회사명·소속 칸이 통째로
                # OCR에서 빠지고 "경력"란 한 칸만 남았는데, 이 조건이 없으면
                # 그 업무 설명을 회사명으로 잘못 잡는다).
                remainder = column_words[1:]
            else:
                continue

            # 표인데 열 헤더를 못 읽어 여기로 떨어진 경우, remainder에 다음 열
            # (예: "소속")의 글자까지 섞여 들어올 수 있다(실측: "회사명"란
            # "FauBct" 다음 "소속"란 "디자인터"가 176px 떨어져 있는데도 한
            # 값으로 뭉쳐 잡혀, 마스킹 박스가 "경력"란까지 통째로 덮었다).
            # 진짜 여러 단어짜리 회사명(실측: "디자인전략 매직 디자인 인수")은
            # EasyOCR이 애초에 한 덩어리로 검출해 이 문제가 없다 — 칸 사이
            # 가로 간격이 줄 높이의 몇 배를 넘으면 그 뒤는 다른 열로 보고 자른다.
            row_height = bottom - top
            trimmed = [remainder[0]]
            for text, bbox in remainder[1:]:
                if bbox[0] - trimmed[-1][1][2] > row_height * _CAREER_LIST_VALUE_GAP_RATIO:
                    break
                trimmed.append((text, bbox))
            remainder = trimmed

            value = " ".join(text for text, _bbox in remainder)
            cell_bbox = remainder[0][1]
            for _text, bbox in remainder[1:]:
                cell_bbox = _union(cell_bbox, bbox)
            results.append(
                {
                    "field": field,
                    "value": value,
                    "start": 0,
                    "end": 0,
                    "confidence": 0.85,
                    "bbox": cell_bbox,
                    "page": 1,
                    "reason": f'"{header_text}" 목록에서 연도 뒤에 오는 글자를 회사명으로 판단',
                    "evidence": {"ocr": True, "career_list_entry": True},
                    "source": "rule",
                }
            )
    return results


def _looks_like_label(line_text: str) -> bool:
    """실제 서식 라벨("입금 계좌" 등)만 다음 줄과 이어 붙인다.

    한글이 하나도 없는 짧은 줄까지 라벨로 보면, 두 칸짜리 머리말(로고 "Villa"와
    제목 "INVOICE"처럼 서로 다른 열에 있는데 세로 위치만 가까운 글자)이 한 문장으로
    엮여 NER이 그 사이 전체를 회사명으로 잘못 묶는다(실측: 2026-09-17, 'Vill'과
    'INVOICE'가 이어 붙어 "Vill INVOICE"가 조직명으로 잡히면서 마스킹 상자가
    머리말 절반을 뒤덮었다). 이 제품의 실제 서식 라벨은 전부 한글이라 이 조건으로
    로고·장식 문구를 걸러낸다.
    """
    compact = line_text.replace(" ", "")
    if not compact or len(compact) > _LABEL_MAX_LEN:
        return False
    if not _HANGUL.search(compact):
        return False
    return not _LABEL_DISALLOWED.search(compact)


def _row_is_single_cluster(line: list[tuple[str, tuple]]) -> bool:
    """줄 안의 항목들이 서로 가깝게 붙어 하나의 문구를 이루는가. `_LABEL_INTERNAL_GAP_RATIO` 참고.

    `line`은 이미 x좌표로 정렬돼 있다(`_group_into_rows`가 그렇게 만든다).
    항목이 하나뿐이면 당연히 하나의 문구다.
    """
    if len(line) <= 1:
        return True
    for (_prev_text, prev_bbox), (_text, bbox) in zip(line, line[1:]):
        height = max(prev_bbox[3] - prev_bbox[1], bbox[3] - bbox[1], 1.0)
        gap = bbox[0] - prev_bbox[2]
        if gap > height * _LABEL_INTERNAL_GAP_RATIO:
            return False
    return True


def _normalize_digit_confusable_letters(text: str) -> str:
    """숫자가 섞인 연속 구간 안의 "O"/"o"를 "0"으로 되돌린다. `_DIGIT_CONFUSABLE_RUN` 참고.

    길이를 바꾸지 않는다(한 글자를 한 글자로만 바꾼다) — `_words_from_lines`가
    이미 만들어 둔 `_Word.start/end` 오프셋이 이 함수 호출 뒤에도 그대로
    유효해야 하기 때문이다. 순서를 바꾸면(예: 먼저 정규화하고 나중에 offset을
    매기면) 코드가 더 간단해지지만, 그러면 표 열 인식(`_find_table_column_cells`)이
    보는 `lines`의 원문 글자와 raw_text가 달라져 헷갈린다 — 그래서 완성된
    raw_text에 제자리 치환만 한다.
    """

    def _replace(match: re.Match) -> str:
        run = match.group()
        if not any(ch.isdigit() for ch in run):
            return run
        return run.replace("O", "0").replace("o", "0")

    return _DIGIT_CONFUSABLE_RUN.sub(_replace, text)


@dataclass
class _Word:
    start: int          # 이 모듈이 다시 만든 raw_text 기준 offset
    end: int
    bbox: tuple[float, float, float, float]   # 원본 이미지 픽셀 좌표


def _touching(a: tuple, b: tuple) -> bool:
    """b가 a 바로 옆에 거의 붙어 있는가(같은 헤더 문구의 다음 조각일 가능성)."""
    gap = b[0] - a[2]
    height = max(a[3] - a[1], b[3] - b[1])
    if height <= 0:
        return False
    return gap <= height * _TOUCHING_GAP_RATIO


def _union(a: tuple, b: tuple) -> tuple:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


_reader = None


def _get_reader():
    """첫 호출 때 한 번만 모델을 불러와 캐싱한다. import 시점에 불러오면 모델 파일이
    없는 환경에서 `import text_ocr` 자체가 실패해 scan.py 전체가 멎는다."""
    global _reader
    if _reader is None:
        import easyocr

        _reader = easyocr.Reader(_EASYOCR_LANGS, gpu=False)
    return _reader


def _polygon_to_bbox(polygon) -> tuple[float, float, float, float]:
    """EasyOCR이 주는 4점 다각형(기울어진 글자면 사각형도 기운다)을 축에 나란한
    bbox로 바꾼다. 원래 다각형보다 넓어질 수 있지만, 마스킹은 덜 가리는 쪽보다
    넓게 가리는 쪽이 안전하다(이 파일 전체에서 일관된 원칙)."""
    xs = [float(point[0]) for point in polygon]
    ys = [float(point[1]) for point in polygon]
    return (min(xs), min(ys), max(xs), max(ys))


# 실측(2026-09-18, 모바일로 노트북 화면을 세로로 세워 찍은 사진): 사진이 90도
# 돌아간 채로 들어오면 EasyOCR이 거의 못 읽는다 — 잘못된 방향에서도 낱글자
# 하나짜리 검출은 우연히 확신도가 높게 나올 수 있어("0" 0.99, "채" 0.89 등)
# 확신도만으로는 "제대로 읽혔는지"를 가늠할 수 없다. 2글자 이상이면서 확신도가
# 뚜렷이 높은(>0.6) 검출의 글자 수 합으로 점수를 매긴다 — 실제 단어가 읽혔을
# 때만 이 점수가 커진다(같은 사진을 바로 세워 읽으면 "최태오의 발자쥐"(8자,
# 0.97) 등으로 점수가 10을 훌쩍 넘지만, 잘못된 방향에서는 거의 0에 머문다).
_ROTATION_RECOVERY_K_VALUES = (1, 2, 3)  # np.rot90 k: 반시계 90도 / 180도 / 시계 90도
_ROTATION_RECOVERY_TRIGGER_SCORE = 10.0


def _rotation_quality_score(results) -> float:
    return sum(
        len(text.strip())
        for _polygon, text, confidence in results
        if confidence > 0.6 and len(text.strip()) >= 2
    )


def _map_point_from_rotated(x: float, y: float, k: int, orig_w: float, orig_h: float) -> tuple[float, float]:
    """`np.rot90(arr, k=k)`로 돌린 이미지 위의 점 (x, y)를 원본 이미지 좌표로
    되돌린다. `_ROTATION_RECOVERY_K_VALUES`의 각 k에 대한 역변환이다."""
    if k == 1:
        return orig_w - y, x
    if k == 2:
        return orig_w - x, orig_h - y
    if k == 3:
        return y, orig_h - x
    return x, y


def _map_bbox_from_rotated(
    bbox: tuple[float, float, float, float], k: int, orig_w: float, orig_h: float
) -> tuple[float, float, float, float]:
    if k == 0:
        return bbox
    left, top, right, bottom = bbox
    corners = [(left, top), (right, top), (left, bottom), (right, bottom)]
    mapped = [_map_point_from_rotated(x, y, k, orig_w, orig_h) for x, y in corners]
    xs = [p[0] for p in mapped]
    ys = [p[1] for p in mapped]
    return (min(xs), min(ys), max(xs), max(ys))


def _group_into_rows(
    detections: list[tuple[str, tuple]],
) -> list[list[tuple[str, tuple]]]:
    """세로 위치가 가까운 검출들을 같은 줄로 묶는다.

    EasyOCR은 검출 순서를 보장하지 않고, 표처럼 한 행에 칸이 여러 개면 칸마다
    별개의 검출로 나온다. 중심 y가 비슷한 것들을 한 줄로 묶고, 줄 안에서는 x로
    정렬해 읽는 순서를 만든다. `_ROW_CENTER_TOLERANCE` 참고.
    """
    if not detections:
        return []

    ordered = sorted(detections, key=lambda item: ((item[1][1] + item[1][3]) / 2, item[1][0]))
    rows: list[list[tuple[str, tuple]]] = []
    row_center = 0.0
    row_height = 0.0

    for text, bbox in ordered:
        center = (bbox[1] + bbox[3]) / 2
        height = bbox[3] - bbox[1]
        if rows and abs(center - row_center) <= max(row_height, height) * _ROW_CENTER_TOLERANCE:
            rows[-1].append((text, bbox))
        else:
            rows.append([(text, bbox)])
        current = rows[-1]
        row_center = sum((b[1] + b[3]) / 2 for _, b in current) / len(current)
        row_height = max(b[3] - b[1] for _, b in current)

    return [sorted(row, key=lambda item: item[1][0]) for row in rows]


def _oversized_row_flags(rows: list[list[tuple[str, tuple]]]) -> list[bool]:
    """줄마다 제목 크기인지 표시한다. `_OVERSIZED_HEIGHT_RATIO` 주석 참고.

    줄의 대표 높이는 그 줄에서 가장 큰 검출의 높이로 잡는다.
    """
    if not rows:
        return []
    row_heights = [max(bbox[3] - bbox[1] for _, bbox in row) for row in rows]
    doc_median = statistics.median(row_heights)
    max_height = doc_median * _OVERSIZED_HEIGHT_RATIO
    return [height > max_height for height in row_heights]


def _ocr_lines(
    path: str,
) -> tuple[
    list[list[tuple[str, tuple[float, float, float, float]]]],
    list[bool],
    list[list[tuple[str, tuple[float, float, float, float]]]],
    tuple[int, float, float] | None,
]:
    """이미지 1장을 OCR해서 줄 단위로 묶는다. 각 줄은 (글자, bbox) 목록이다.

    두 번째 반환값은 각 줄이 제목 크기(`_oversized_row_flags` 참고)였는지를 같은
    순서로 나열한 목록이다.

    세 번째 반환값(`weak_rows`)은 `_CROSS_REFERENCE_MIN_CONFIDENCE`까지 낮춘
    문턱으로 다시 묶은 줄 목록이다 — `_EASYOCR_MIN_CONFIDENCE`에 걸려 본문
    `rows`에는 없는, 더 낮은 확신도의 글자까지 담는다. EasyOCR을 다시 부르지
    않는다(같은 `results`를 재사용) — 이미지 OCR은 비용이 커서 같은 이미지를
    두 번 돌리지 않는다.

    네 번째 반환값(`rotation`)은 사진이 통째로 돌아간 것으로 판단해 회전
    보정을 적용했으면 `(k, 원본 너비, 원본 높이)`, 아니면 `None`이다. 이 값이
    있으면 `rows`/`weak_rows`의 bbox는 "바로 세운" 좌표계다 — 줄 묶기·표 인식
    등 이후 모든 구조 판정이 가로쓰기를 가정하므로, 회전된 채로 넘기면 줄
    묶기부터 깨진다. 마스킹은 원본 파일 위에 그리므로, 최종 bbox를 실제로
    돌려주기 전에(`detect()` 끝에서) `_map_bbox_from_rotated`로 원본 좌표로
    되돌려야 한다.
    """
    reader = _get_reader()
    results = reader.readtext(path)
    rotation: tuple[int, float, float] | None = None

    if _rotation_quality_score(results) < _ROTATION_RECOVERY_TRIGGER_SCORE:
        # 실측(2026-09-18, 모바일로 노트북 화면을 세로로 세워 찍은 사진): 기본
        # 방향에서 이 정도로 부실하게 읽힐 때만 — 흔한 정상 문서까지 매번 4배
        # 비용을 물지 않으려고 — 90/180/270도로 돌려 다시 읽어보고 제일 잘
        # 읽히는 각도를 고른다.
        from PIL import Image
        import numpy as np

        with Image.open(path) as img:
            arr = np.array(img.convert("RGB"))
        orig_h, orig_w = float(arr.shape[0]), float(arr.shape[1])

        best_score = _rotation_quality_score(results)
        best_results = results
        best_k = 0
        for k in _ROTATION_RECOVERY_K_VALUES:
            rotated_results = reader.readtext(np.rot90(arr, k=k))
            score = _rotation_quality_score(rotated_results)
            if score > best_score:
                best_score = score
                best_results = rotated_results
                best_k = k

        if best_k != 0 and best_score >= _ROTATION_RECOVERY_TRIGGER_SCORE:
            results = best_results
            rotation = (best_k, orig_w, orig_h)

    detections: list[tuple[str, tuple]] = []
    weak_detections: list[tuple[str, tuple]] = []
    for polygon, text, confidence in results:
        text = text.strip()
        if not text or confidence < _CROSS_REFERENCE_MIN_CONFIDENCE:
            continue
        bbox = _polygon_to_bbox(polygon)
        weak_detections.append((text, bbox))
        if confidence >= _EASYOCR_MIN_CONFIDENCE:
            detections.append((text, bbox))

    rows = _group_into_rows(detections)
    flags = _oversized_row_flags(rows)
    weak_rows = _group_into_rows(weak_detections)
    return rows, flags, weak_rows, rotation


def _ocr_words(path: str) -> tuple[str, list[_Word]]:
    """이미지 1장을 OCR해서 (다시 만든 raw_text, 단어별 offset+bbox 목록)을 돌려준다."""
    lines, flags, _weak_lines, _rotation = _ocr_lines(path)
    text, words, _oversized_ranges = _words_from_lines(lines, flags)
    return text, words


def _words_from_lines(
    lines: list[list[tuple[str, tuple[float, float, float, float]]]],
    oversized_flags: list[bool] | None = None,
) -> tuple[str, list[_Word], list[tuple[int, int]]]:
    """`_ocr_lines`가 만든 줄 목록을 raw_text 하나로 이어붙인다.

    같은 줄의 단어는 공백으로 잇는다. 줄과 줄 사이는 원칙적으로 줄바꿈이지만,
    앞 줄이 라벨처럼 보이면(_looks_like_label) 공백으로 이어 붙인다 — 그래야
    "입금 계좌"(라벨 줄) 다음의 "국민 6127-02-384915"(값 줄)이 오탐 제거
    분류기에게 "계좌"라는 문맥을 잃지 않고 전달된다.

    `detect()`가 이 `lines`를 표 열 인식(`_find_table_column_cells`)에도 같이
    쓴다 — OCR을 두 번 돌리지 않으려고 `_ocr_words(path)`에서 분리했다.

    세 번째 반환값은 제목 크기였던 줄들이 raw_text에서 차지하는 [start, end)
    구간이다. `detect()`가 그 구간과 겹치는 org(회사명) 판정만 가려내는 데 쓴다
    — 나머지 판정은 이 구간과 무관하게 정상적으로 받는다.
    """
    parts: list[str] = []
    words: list[_Word] = []
    oversized_ranges: list[tuple[int, int]] = []
    cursor = 0

    for line_index, line_words in enumerate(lines):
        if line_index > 0:
            previous_line = lines[line_index - 1]
            previous_text = "".join(text for text, _ in previous_line)
            is_label = _looks_like_label(previous_text) and _row_is_single_cluster(previous_line)
            separator = " " if is_label else "\n"
            parts.append(separator)
            cursor += len(separator)

        line_start = cursor
        for word_index, (text, bbox) in enumerate(line_words):
            if word_index > 0:
                parts.append(" ")
                cursor += 1
            start = cursor
            parts.append(text)
            cursor += len(text)
            words.append(_Word(start=start, end=cursor, bbox=bbox))

        if oversized_flags and line_index < len(oversized_flags) and oversized_flags[line_index]:
            if cursor > line_start:
                oversized_ranges.append((line_start, cursor))

    return "".join(parts), words, oversized_ranges


def _bbox_for_range(words: list[_Word], start: int, end: int) -> tuple | None:
    """[start, end) 구간과 겹치는 단어들을 모두 감싸는 사각형. 겹치는 단어가 없으면 None.

    None을 돌려주면 호출부가 그 finding을 버린다 — 가릴 좌표를 모르는 채로
    findings에 남기면 화면에는 뜨는데 마스킹 사본에서는 안 가려지는 항목이 생긴다.

    EasyOCR은 문장 하나를 통째로 검출 하나(bbox 하나)로 묶어서 돌려줄 때가
    있다(실측: 2026-09-18, 지원서 사진의 "지원동기" 문단 첫 줄 전체 — "저는
    식품 공장에서... 홍길동입니다: A식품 B식품" — 가 EasyOCR 검출 하나였다).
    그 안에서 "A식품"만 찾았다고 해서 검출의 bbox 전체(문장 전체 폭)를
    그대로 돌려주면, 값과 무관한 문장 전체가 마스킹으로 덮인다. 그래서 구간이
    한 단어의 일부만 겹치면, 그 단어 폭 안에서 글자 위치 비율만큼 가로로
    좁혀 돌려준다. 구간이 단어 전체를 덮으면(대부분의 경우) 비율이 0~1이 되어
    원래 단어 bbox 그대로 나온다 — 기존 동작과 같다.

    "글자 폭이 균일하다"는 가정은 따옴표·공백처럼 실제로는 훨씬 좁은 글자가
    섞여 있으면 깨진다(실측: 2026-09-18, "'쎄게다' 예술아카데미 회원 브랜딩"
    한 줄 안에서 "쎄게다"를 좁혀 잡았더니, 앞의 따옴표·공백이 평균보다
    좁아서 계산이 실제 위치보다 오른쪽으로 밀려 "쎄" 글자 왼쪽 절반이 가려지지
    않고 그대로 노출됐다 — 문장 전체를 덮던 예전 문제와 반대로, 이번엔 **덜**
    가려져서 더 위험하다). 그래서 평균 글자 폭 하나만큼 양옆으로 더 넓혀
    돌려준다 — 이 근사가 어느 방향으로 틀리든 그 오차를 흡수할 여유를 준다.
    단어 자기 자신의 bbox 밖으로는 안 나간다(그러면 예전의 "문장 전체 덮기"
    문제가 되살아난다).
    """
    boxes: list[tuple[float, float, float, float]] = []
    for w in words:
        if w.start >= end or w.end <= start:
            continue
        word_length = w.end - w.start
        left, top, right, bottom = w.bbox
        if word_length <= 0:
            boxes.append((left, top, right, bottom))
            continue
        overlap_start = max(w.start, start)
        overlap_end = min(w.end, end)
        width = right - left
        char_width = width / word_length
        sub_left = left + width * (overlap_start - w.start) / word_length - char_width
        sub_right = left + width * (overlap_end - w.start) / word_length + char_width
        sub_left = max(left, sub_left)
        sub_right = min(right, sub_right)
        boxes.append((sub_left, top, sub_right, bottom))
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _overlaps_any(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    """[start, end)가 `ranges`의 구간 중 하나와라도 겹치는가. `detect()`의 org 필터용."""
    return any(start < r_end and r_start < end for r_start, r_end in ranges)


def _match_header_labels(
    line: list[tuple[str, tuple]],
) -> list[tuple[int, int, str, str]]:
    """줄에서 `_COLUMN_FIELD_LABELS`의 라벨을 찾아 (시작 단어 인덱스, 끝 단어 인덱스, 라벨, 필드유형) 목록을 돌려준다.

    라벨과 정확히 같은 단어 하나만 찾지 않는다 — OCR이 "회사명"을 "회사"+"명"처럼
    단어 경계와 다르게 쪼개는 경우가 있다. 그래서 `_looks_like_label`처럼 줄
    전체를 이어붙인 문자열에서 라벨을 찾은 뒤, 그 위치가 원래 몇 번째 단어(들)에
    걸쳐 있었는지 역으로 찾는다.
    """
    char_to_word: list[int] = []
    compact_parts: list[str] = []
    for word_index, (word_text, _bbox) in enumerate(line):
        compact_parts.append(word_text)
        char_to_word.extend([word_index] * len(word_text))
    compact = "".join(compact_parts)

    matches: list[tuple[int, int, str, str]] = []
    for label, field in _COLUMN_FIELD_LABELS.items():
        position = compact.find(label)
        if position == -1:
            continue
        word_start = char_to_word[position]
        word_end = char_to_word[position + len(label) - 1]
        matches.append((word_start, word_end, label, field))
    return matches


def _header_cells(
    line: list[tuple[str, tuple]], matches: list[tuple[int, int, str, str]]
) -> list[tuple[tuple, str | None, str | None]]:
    """줄의 단어들을 "헤더 셀" 단위로 묶는다.

    라벨에 걸린 단어 구간(`_match_header_labels`가 찾은 범위)은 하나로 합쳐
    셀 하나로 보고, 그 외 단어는 하나씩 그대로 둔다. 각 셀은
    (bbox, field 또는 None, label 또는 None)이다 — field/label이 있으면
    그 열이 우리가 값을 잡을 대상이라는 뜻이다.
    """
    field_by_word: dict[int, tuple[str, str, int, int]] = {}
    for word_start, word_end, label, field in matches:
        for index in range(word_start, word_end + 1):
            field_by_word[index] = (field, label, word_start, word_end)

    cells: list[tuple[tuple, str | None, str | None]] = []
    index = 0
    while index < len(line):
        matched = field_by_word.get(index)
        if matched is not None:
            field, label, word_start, word_end = matched
            cell_bbox = line[word_start][1]
            for word_index in range(word_start + 1, word_end + 1):
                cell_bbox = _union(cell_bbox, line[word_index][1])
            cells.append((cell_bbox, field, label))
            index = word_end + 1
        else:
            cells.append((line[index][1], None, None))
            index += 1
    return _merge_touching_header_cells(cells)


def _merge_touching_header_cells(
    cells: list[tuple[tuple, str | None, str | None]],
) -> list[tuple[tuple, str | None, str | None]]:
    """라벨이 없는 헤더 셀 중 서로 거의 붙어 있는 것들을 하나로 합친다.

    "주요"+"업무"처럼 한 헤더 문구가 OCR 토큰 두 개로 쪼개지면, 합치지 않을
    경우 서로 다른 두 열로 다뤄져서 마지막 열의 경계 폭 계산이 실제 헤더
    폭보다 좁게 잡힌다(실측: 2026-09-17 — 그 결과로 "주요업무" 열의 진짜
    데이터가 계산된 범위 밖으로 밀려나 표 끝에 도달한 것으로 잘못 판정되어,
    OCR이 값을 못 읽은 옆 칸조차 방어적으로 가릴 기회를 놓쳤다). 라벨이
    걸린 대상 열은 이미 `_header_cells`가 자기 몫끼리 합쳤으니 그대로 두고,
    라벨 없는 셀끼리만 본다.
    """
    merged: list[tuple[tuple, str | None, str | None]] = []
    for bbox, field, label in cells:
        if (
            merged
            and field is None
            and merged[-1][1] is None
            and _touching(merged[-1][0], bbox)
        ):
            merged[-1] = (_union(merged[-1][0], bbox), None, None)
        else:
            merged.append((bbox, field, label))
    return merged


def _column_boundaries(
    cells: list[tuple[tuple, str | None, str | None]],
) -> dict[int, tuple[float, float]]:
    """헤더 셀들을 x좌표로 정렬하고, 인접한 셀 사이 중점을 열 경계로 쓴다.

    가운데 열은 양옆 이웃까지의 중간 지점을 경계로 쓴다. 첫 열의 왼쪽 끝과
    마지막 열의 오른쪽 끝은 이웃이 없어 중점을 구할 수 없으므로, 그 열
    자신의 폭(반대쪽 이웃까지의 거리)의 절반만큼만 바깥으로 열어 둔다 —
    표의 실제 좌우 테두리를 몰라도 "이 열이겠거니" 싶은 정도까지만 받는다는
    뜻이다.

    이 폭 제한이 전에는 없었다(첫 열 왼쪽 끝을 무조건 0, 즉 이미지 왼쪽
    끝까지 열어 뒀다) — 실측 버그(2026-09-17, 지원서 사진): "직장명" 열
    왼쪽에 세로 선으로 나뉜 완전히 별도의 병합 셀(여러 행에 걸친 행 그룹
    라벨 "아르바이트\n경력사항")이 있었는데, 그 라벨 글자가 이미지 왼쪽
    끝과 "직장명" 열 첫 데이터 사이 어딘가에 있다는 이유만으로 회사명 값으로
    잘못 잡혀 라벨 자체가 마스킹으로 가려졌다. 열 폭만큼만 바깥으로 열어
    두면 이런 완전히 다른 셀의 글자까지 삼키는 일이 줄어든다.
    """
    order = sorted(range(len(cells)), key=lambda i: cells[i][0][0])
    last = len(order) - 1
    midpoints = [
        (cells[order[i]][0][2] + cells[order[i + 1]][0][0]) / 2 for i in range(last)
    ]

    boundaries: dict[int, tuple[float, float]] = {}
    for position, cell_index in enumerate(order):
        cell_left = cells[cell_index][0][0]
        cell_right = cells[cell_index][0][2]
        left = midpoints[position - 1] if position > 0 else None
        right = midpoints[position] if position < last else None
        if left is None:
            left = max(0.0, cell_left - (right - cell_left) / 2)
        if right is None:
            right = cell_right + (cell_right - left) / 2
        boundaries[cell_index] = (left, right)
    return boundaries


def _line_span(line: list[tuple[str, tuple]]) -> tuple[float, float]:
    return (min(b[1] for _, b in line), max(b[3] for _, b in line))


def _row_looks_like_header(line: list[tuple[str, tuple]]) -> bool:
    """이 줄이 (우리가 찾던 표가 아니라) **다른** 표의 헤더 행처럼 보이는가.

    실측(2026-09-18, 실제 지원서 사진): "직장명" 표 바로 밑에 표 사이 간격
    없이 "자격증" 표("발급일자"/"자격증명"/"등급" 헤더)가 곧장 붙어 있었다 —
    두 표의 줄 간격이 완전히 같아서(둘 다 44px) `_TABLE_ROW_GAP_RATIO` 세로
    간격 검사로는 표 경계를 전혀 못 잡았고, "발급일자"·"2020년 4월"이 회사명
    값으로 잘못 잡혔다.

    헤더 행의 특징은 칸마다 전부 짧은 라벨 모양 글자라는 것이다("발급일자",
    "자격증명", "등급" — `_looks_like_label` 기준을 전부 통과한다). 반면 진짜
    데이터 행은 칸마다 성격이 섞여 있다 — 회사명 칸은 라벨 모양이어도
    ("삼성전자") 기간 칸은 숫자가 섞여 있어 라벨 모양이 아니다. 그래서 "칸이
    둘 이상이고 전부 라벨 모양"이면 헤더로 본다 — 데이터 행은 보통 날짜·숫자
    칸이 하나는 있어서 이 조건에 걸리지 않는다.
    """
    if len(line) < 2:
        return False
    return all(_looks_like_label(text) for text, _bbox in line)


def _collect_column_rows(
    following_lines: list[list[tuple[str, tuple]]],
    column_left: float,
    column_right: float,
    first_column_range: tuple[float, float],
    last_column_range: tuple[float, float],
    header_height: float,
) -> list[tuple[str | None, tuple]]:
    """헤더 다음 줄들을 훑어 대상 열의 셀 값들을 모은다. `_TABLE_ROW_GAP_RATIO`/`_MAX_TABLE_ROWS` 참고.

    텍스트가 `None`이면 값을 못 읽었지만 표 구조상 이 자리에 값이 있어야
    한다고 판단해 방어적으로 잡은 자리다(아래 함수 본문 참고).

    행이 하나씩 늘어날 때마다 그 줄의 높이를 같이 기록해서, 다음 줄과의
    세로 간격을 "지금까지 본 행 높이"와 비교한다 — 표가 몇 줄짜리든 그 표
    자신의 줄 간격을 기준으로 판단하므로, 줄 간격이 넓은 표와 좁은 표 모두에
    맞는다.

    "이 줄이 아직 표 안인가"는 **대상 열 자체에 글자가 있으면 무조건 그렇다**로
    본다 — 그게 이 함수가 찾으려는 값 그 자체이기 때문이다(실측: 2026-09-17,
    지원서의 "직장명" 표 첫 행은 OCR이 "주요업무" 칸을 아예 못 읽어 그 칸이
    비었는데, 그렇다고 이미 읽은 "직장명" 칸 값까지 버리면 안 됐다). 대상 열이
    비어 있을 때만 표의 **첫 열과 마지막 열 둘 다**에 글자가 있는지로 판단한다
    (전체 가로 범위 어딘가에 글자가 있는지만 보면 너무 헐겁다 — 실측: 같은
    문서군에서 표 다음에 나온 좌우 두 섹션 제목("자격증" / "수상 및 기타
    능력")이 표와 같은 왼쪽 여백에서 시작해 가로 범위 대부분과 겹쳐서 표 다음
    줄로 잘못 포함되고, 그 아래 완전히 다른 표의 값까지 엉뚱하게 회사명으로
    잡혔다. 진짜 표 행은 왼쪽 첫 열부터 오른쪽 마지막 열까지 값이 흩어져
    있지만, 그 뒤에 오는 산문·다른 섹션 제목은 보통 그렇게 양 끝까지 안 걸친다).
    """
    rows: list[tuple[str, tuple]] = []
    row_heights = [header_height]
    previous_bottom: float | None = None

    for line in following_lines[:_MAX_TABLE_ROWS]:
        top, bottom = _line_span(line)
        if previous_bottom is not None:
            gap = top - previous_bottom
            if gap > statistics.median(row_heights) * _TABLE_ROW_GAP_RATIO:
                break

        if _row_looks_like_header(line):
            # 다음 표의 헤더 행으로 넘어간 것이다(`_row_looks_like_header` 참고) —
            # 세로 간격만으로는 못 잡는다. 여기서 멈추지 않으면 그 표의 헤더
            # 글자("발급일자" 등)와 첫 데이터 행까지 이 열의 값으로 잘못 잡힌다.
            break

        cell_words = [
            (text, bbox)
            for text, bbox in line
            if column_left <= (bbox[0] + bbox[2]) / 2 < column_right
        ]
        if cell_words:
            cell_text = " ".join(text for text, _ in cell_words)
            cell_bbox = cell_words[0][1]
            for _text, bbox in cell_words[1:]:
                cell_bbox = _union(cell_bbox, bbox)
            rows.append((cell_text, cell_bbox))
        else:
            centers = [(b[0] + b[2]) / 2 for _, b in line]
            touches_first = any(
                first_column_range[0] <= c < first_column_range[1] for c in centers
            )
            touches_last = any(
                last_column_range[0] <= c < last_column_range[1] for c in centers
            )
            if not (touches_first and touches_last):
                # 실측(2026-09-17)으로 "이 줄만 건너뛰고 계속 훑기"도
                # 시도해봤는데, 표를 벗어난 자기소개서 문단·서명란까지
                # 전부 회사명으로 잘못 잡는 훨씬 심한 회귀가 났다 — 대상
                # 열의 x축 범위에 우연히 걸리는 글자가 페이지 어디에나
                # 있을 수 있어서, 한 번 훑기를 계속 허용하면 표 끝을 아예
                # 못 찾게 된다. 표 중간 행 하나가 통째로 안 읽혀도 그 아래
                # 멀쩡한 행을 놓치는 게, 표 밖 내용을 잘못 가리는 것보다는
                # 안전하다 — 그래서 여기서 멈춘다.
                break
            # 대상 열은 비었지만 이 행 자체는 진짜 표 행이다(첫 열·마지막
            # 열 둘 다에 값이 있음) — OCR이 이 칸의 글자를 통째로 못 읽었을
            # 뿐, 표 구조상 값이 있어야 하는 자리라는 건 안다. 값을 모른 채로
            # 자리만이라도 방어적으로 가린다 — `id_detector.py`가 얼굴 영역을
            # 값을 읽지 않고 좌표만으로 가리는 것과 같은 방식이다. `None`으로
            # 표시해서 "실제로 읽은 값"과 구분한다.
            rows.append((None, (column_left, top, column_right, bottom)))

        row_heights.append(bottom - top)
        previous_bottom = bottom

    return rows


def _find_table_column_cells(
    lines: list[list[tuple[str, tuple]]],
) -> list[dict]:
    """표 헤더 행(예: "회사명")을 찾아 그 열 전체를 그 유형의 값으로 확정한다.

    NER은 한 줄짜리 평문에서 개체명을 추론하다 보니 표에서는 옆 셀 글자가
    끝에 붙거나(경계 오염) 값을 아예 놓치는 경우가 있다(`_COLUMN_FIELD_LABELS`
    주석 참고). 표는 이미 헤더가 열의 의미를 알려주므로, 자유 텍스트 추론
    대신 기하학적으로(헤더 밑 같은 x축 범위) 확정한다.
    """
    results: list[dict] = []
    for header_index, header_line in enumerate(lines):
        matches = _match_header_labels(header_line)
        if not matches:
            continue
        cells = _header_cells(header_line, matches)

        # 헤더 셀이 하나뿐이면(이웃 헤더가 없으면) 경계를 계산할 근거가 없다
        # — 왼쪽 끝 0, 오른쪽 끝 무한대인 "열 하나"가 되어 그 아래 모든 행의
        # 글자를 통째로 삼켜버린다. 이럴 땐 아무것도 안 잡는 쪽이 안전하다 —
        # 지금과 같은 "탐지 안 됨"이지, 다른 정상 결과까지 덮어쓰는 "잘못된
        # 거대한 셀"보다 훨씬 낫다.
        if len(cells) < 2:
            continue

        boundaries = _column_boundaries(cells)
        order = sorted(range(len(cells)), key=lambda i: cells[i][0][0])
        first_column_range = boundaries[order[0]]
        last_column_range = boundaries[order[-1]]
        header_top, header_bottom = _line_span(header_line)
        header_height = header_bottom - header_top

        for cell_index, (_bbox, field, label) in enumerate(cells):
            if field is None:
                continue
            column_left, column_right = boundaries[cell_index]
            rows = _collect_column_rows(
                lines[header_index + 1 :],
                column_left,
                column_right,
                first_column_range,
                last_column_range,
                header_height,
            )
            for cell_text, cell_bbox in rows:
                if cell_text is None:
                    # 값을 못 읽었지만 표 구조상 이 자리에 값이 있어야 한다고
                    # 판단해 방어적으로 잡은 자리다(`_collect_column_rows`
                    # 참고) — id_detector.py가 얼굴 영역을 값을 읽지 않고
                    # 좌표만으로 가리는 것과 같은 방식이라, 신뢰도도 실제로
                    # 읽은 값보다 낮게(0.6) 매긴다.
                    results.append(
                        {
                            "field": field,
                            "value": f"{label} 미확인 값",
                            "start": 0,
                            "end": 0,
                            "confidence": 0.6,
                            "bbox": cell_bbox,
                            "page": 1,
                            "reason": f'"{label}" 표 헤더 아래 칸인데 OCR이 값을 읽지 못해 자리만 방어적으로 가림',
                            "evidence": {
                                "ocr": True,
                                "structured_header": True,
                                "unread": True,
                            },
                            "source": "rule",
                        }
                    )
                    continue
                results.append(
                    {
                        "field": field,
                        "value": cell_text,
                        "start": 0,
                        "end": 0,
                        "confidence": 0.98,
                        "bbox": cell_bbox,
                        "page": 1,
                        "reason": f'"{label}" 표 헤더 아래 셀',
                        "evidence": {"ocr": True, "structured_header": True},
                        "source": "rule",
                    }
                )
    return results


def _find_weak_text_person_names(
    weak_text: str, weak_words: list[_Word], existing_bboxes: list[tuple]
) -> list[dict]:
    """확신도 낮은 `weak_text`에서 사람 이름만 따로 찾는다.

    실측(2026-09-18, 실제 지원서 사진): "지원동기" 자기소개서 문단이 줄 전체
    확신도 0.21로 잡혀 본문 `text`(0.3 문턱)에서 통째로 빠졌다. 그 문단 안의
    "홍길동"이라는 이름은 `_find_cross_referenced_values`로도 못 구한다 —
    그 방식은 표에서 "이미 확정된 값"을 다른 자리에서 또 찾는 것인데, 이름은
    애초에 표에서 확정된 적이 없어서(성명은 "직장명" 표가 아니라 문서 상단의
    별도 칸에서 이미 확정된, 다른 값 "이예지"다) 대조할 원본이 없다.

    그래서 `weak_text`에도 `scan.scan_text()`를 직접 돌리되, **person 판정만**
    받아들인다. person 이외의 타입, 특히 injection은 절대 받지 않는다 — 확신도
    낮은 텍스트는 OCR 잡음이 섞이기 쉽고, 그 잡음이 과거 실제로 인젝션
    분류기를 오탐시킨 적이 있다(`_CROSS_REFERENCE_MIN_CONFIDENCE` 주석의
    "ITQAAS AS — \\|" 사례). person 판정만 좁게 받으면 그 오탐 경로를 열지
    않으면서 이름 누락만 메울 수 있다.
    """
    if not weak_text.strip():
        return []

    from backend.scanner import scan   # 지연 임포트 — scan.py가 이 모듈을 불러오므로 순환을 피한다

    result = scan.scan_text(weak_text, meta={})
    results: list[dict] = []
    for finding in result.findings:
        if finding.type != "person":
            continue
        bbox = _bbox_for_range(weak_words, finding.start, finding.end)
        if bbox is None:
            continue
        if any(_bboxes_overlap(bbox, existing) for existing in existing_bboxes):
            continue
        results.append(
            {
                "field": "person",
                "value": finding.text,
                "start": 0,
                "end": 0,
                "confidence": finding.confidence,
                "bbox": bbox,
                "page": 1,
                "reason": finding.reason,
                "evidence": {**finding.evidence, "ocr": True, "weak_confidence_pass": True},
                "source": finding.source,
            }
        )
    return results


def _find_cross_referenced_values(
    text: str, words: list[_Word], table_cells: list[dict]
) -> list[dict]:
    """표에서 이미 확정된 값이 문서의 다른 자리(자기소개서 같은 자유 서술문)에도
    그대로 나오면 그 자리도 같이 찾는다.

    NER은 표 밖의 자연스러운 문장에서는 "A식품"처럼 짧고 "영문 한 글자 + 일반
    명사" 모양인 회사명을 거의 못 알아본다(실측: 2026-09-18, 지원서 사진 —
    "직장명" 표 안의 "A식품"/"B식품"/"C식품"은 표 구조로 정확히 잡히는데, 바로
    아래 "지원동기" 문단에 똑같이 적힌 "A식품, B식품, C식품"은 NER이 하나도
    못 잡았다. 같은 문장의 사람 이름("홍길동")은 정상적으로 잡히는 것과 대비된다
    — NER 모델 자체가 이 모양의 회사명에 약하다).

    표 헤더로 이미 확정된 값은 근거가 확실하다(사람이 직접 그 열의 헤더를
    보고 채운 실제 값이다). 같은 문서 안에서 똑같은 글자가 어떤 자리에서는
    개인정보고 다른 자리에서는 아니라고 볼 이유가 없으므로, 표에서 확정된
    값과 정확히 같은 문자열이 나오는 다른 위치도 전부 같은 유형으로 잡는다.
    """
    confirmed: dict[str, str] = {}
    for cell in table_cells:
        value = cell.get("value")
        # "unread"인 셀은 값 자체를 모른다("{라벨} 미확인 값" 같은 플레이스홀더
        # 문구다) — 그 문구를 문서에서 찾아봐야 아무 의미가 없다.
        if not value or cell.get("evidence", {}).get("unread"):
            continue
        confirmed.setdefault(value, cell["field"])

    existing_bboxes = [cell["bbox"] for cell in table_cells]

    def _new_hits(pattern: str) -> list[tuple[re.Match, tuple]]:
        hits = []
        for match in re.finditer(pattern, text):
            bbox = _bbox_for_range(words, match.start(), match.end())
            if bbox is None:
                continue
            # 표 셀 자기 자신의 자리는 다시 안 잡는다 — 그 값이 나온 표
            # 셀 자체(`table_cells`)가 이미 그 자리를 정확한 bbox로 갖고
            # 있으므로, 여기서 또 잡으면 같은 자리를 미세하게 다른(단어
            # bbox를 다시 합친) 사각형으로 덮어쓸 뿐이다.
            if any(_bboxes_overlap(bbox, existing) for existing in existing_bboxes):
                continue
            hits.append((match, bbox))
        return hits

    results: list[dict] = []
    for value, field in confirmed.items():
        hits = _new_hits(re.escape(value))
        if not hits:
            # 실측(2026-09-18, 지원서 사진): "C식품"의 "C"가 자유 서술문에서
            # "("로 오독됐다("(식품 공장에서..."). 표 셀 자기 자신의 자리 말고는
            # 정확히 일치하는 자리를 하나도 못 찾았을 때만 — "영문 한 글자 +
            # 한글 단어" 모양인 값의 그 한 글자를 흔한 OCR 오독 기호(괄호·숫자)로
            # 바꾼 형태도 찾아본다. 정확한 매칭이 이미 있는 값(A식품·B식품)까지
            # 이 느슨한 패턴으로 다시 훑으면 서로 다른 값이 같은 자리에 겹쳐
            # 잡힌다 — 표 셀 자기 자신의 자리만 걸렸던 값(exact match는 있지만
            # 새 자리는 없는 경우)에도 마찬가지로 넘어가야 하므로, "새로 찾은
            # 자리가 하나도 없을 때"를 기준으로 삼는다.
            letter_confusable = re.match(r"^[A-Za-z](.+)$", value)
            if letter_confusable:
                pattern = r"[(0-9]" + re.escape(letter_confusable.group(1))
                hits = _new_hits(pattern)
        for _match, bbox in hits:
            results.append(
                {
                    "field": field,
                    "value": value,
                    "start": 0,
                    "end": 0,
                    "confidence": 0.9,
                    "bbox": bbox,
                    "page": 1,
                    "reason": f'표 헤더 아래 셀에서 이미 확정된 값("{value}")이 문서의 다른 자리에도 그대로 나옴',
                    "evidence": {"ocr": True, "cross_referenced_from_table": True},
                    "source": "rule",
                }
            )
    return results


def _bboxes_overlap(a: tuple, b: tuple) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _merge_table_cells(findings: list[dict], table_cells: list[dict]) -> list[dict]:
    """표에서 뽑은 셀 값을 기존 findings에 합친다.

    bbox가 겹치면(단순 사각형 교차 판정) 겹치는 기존 finding을 지우고 표에서
    뽑은 값으로 교체한다(표 구조가 더 확실한 신호이므로 우선 — 하나만 지우면
    지저분한 finding이 같이 남는다). 안 겹치면 새 finding으로 그냥 추가한다 —
    NER이 아예 놓친 값("Fauget" 등)을 이렇게 새로 잡는다.

    이 제거 판정은 `findings`(기존 NER/정규식 결과)에만 적용한다 — `table_cells`
    끼리는 서로 지우지 않는다. 실측 버그(2026-09-18, 아르바이트 지원서): 자유
    서술문에 이어 붙은 "A식품 B식품"처럼 인접한 두 값의 보간된 sub-word bbox가
    서로 살짝 겹칠 수 있는데, 예전 코드는 셀을 순서대로 하나씩 append하며 겹침을
    검사해서 뒤에 처리된 셀이 먼저 넣은 셀을 지워버렸다(B식품이 A식품을 밀어냄).
    """
    covered = [f for f in findings if not any(_bboxes_overlap(f["bbox"], cell["bbox"]) for cell in table_cells)]
    return covered + list(table_cells)


def detect(path: str) -> list[dict]:
    """이미지 1장에서 OCR로 읽은 글자 중 개인정보를 찾는다.

    rules.py/id_detector.py와 같은 형식에 좌표를 더해 돌려준다:
        [{field, value, start, end, confidence, bbox, page, reason, evidence, source}, ...]

    scan.scan_text()를 그대로 불러 문서 텍스트와 동일한 판정(정규식·NER·인젝션·
    오탐 제거)을 받는다 — source도 그 판정이 실제로 어느 단계("rule"/"ner"/
    "classifier")에서 나왔는지 그대로 넘긴다. evidence에 "ocr": True만 얹어서
    이미지에서 OCR로 추출된 값이라는 사실을 남긴다.

    start/end는 0으로 둔다 — id_detector.detect()와 같은 이유다: 이미지에는
    문자 오프셋이라는 개념이 없고 마스킹은 bbox로 한다.

    제목 크기 글자(`_oversized_row_flags`가 표시한 줄) 안에서 나온 org(회사명)
    판정은 버린다 — 예전에 인보이스 제목 "INVOICE"가 회사명으로 오탐된 적이
    있어서다. 그 줄 자체는 raw_text에서 빠지지 않으므로, 이름처럼 큰 글자로
    인쇄된 진짜 개인정보(이력서 히어로 타이틀 등)는 org가 아닌 한 정상적으로
    잡힌다.
    """
    try:
        lines, oversized_flags, weak_lines, rotation = _ocr_lines(path)
        text, words, oversized_ranges = _words_from_lines(lines, oversized_flags)
        weak_text, weak_words, _weak_oversized = _words_from_lines(weak_lines)
        # `_find_career_list_entries`는 NER이 아니라 "연도 - 연도" 뒤 글자를
        # 기하학적으로만 뽑는 순수 구조 판정이라, 확신도 낮은 `weak_lines`에
        # 돌려도 `scan_text`(NER·인젝션)로 잡음이 들어가는 위험이 없다 — 그래서
        # `_EASYOCR_MIN_CONFIDENCE`에 걸려 `lines`에는 없는 항목까지 마저 본다
        # (실측: 2026-09-18, 확신도 0.23으로 잡힌 "(주) 리우나 주거디자인..."
        # 항목).
        table_cells = (
            _find_table_column_cells(lines)
            + _find_career_list_entries(lines)
            + _find_career_list_entries(weak_lines)
        )
    except Exception:      # noqa: BLE001 — 업로드 파일은 무엇이든 들어온다. OCR 모델이
        return []          # 없거나 이미지가 깨졌어도 이 검사만 건너뛰면 된다. 표 열
                            # 인식(`_find_table_column_cells`)은 순수 함수라 원래
                            # 실패할 일이 거의 없지만, OCR 자체는 성공했는데 이
                            # 검사만으로 전체가 죽는 일은 없게 같이 감싼다.

    if not text.strip():
        return []

    # 글자 수를 바꾸지 않으므로 words/table_cells가 쓰는 오프셋·bbox와 계속 맞는다
    # (`_normalize_digit_confusable_letters` 참고).
    text = _normalize_digit_confusable_letters(text)

    from backend.scanner import scan   # 지연 임포트 — scan.py가 이 모듈을 불러오므로 순환을 피한다

    result = scan.scan_text(text, meta={"filename": path})

    findings: list[dict] = []
    for finding in result.findings:
        if finding.type == "org" and _overlaps_any(finding.start, finding.end, oversized_ranges):
            continue
        bbox = _bbox_for_range(words, finding.start, finding.end)
        if bbox is None:
            continue
        findings.append(
            {
                "field": finding.type,
                "value": finding.text,
                "start": 0,
                "end": 0,
                "confidence": finding.confidence,
                "bbox": bbox,
                "page": 1,
                "reason": finding.reason,
                "evidence": {**finding.evidence, "ocr": True},
                "source": finding.source,
            }
        )
    # 표에서 확정된 값이 문서의 다른 자리(자기소개서 등 자유 서술문)에도 그대로
    # 나오면 그 자리도 같이 잡는다(`_find_cross_referenced_values` 참고) — NER이
    # 표 밖 문장에서는 놓치는 회사명 모양이 실제로 있다. 확신도를 낮춘 `weak_text`로
    # 찾는다 — 긴 문단 안 글자는 정상적으로 적혀 있어도 확신도가 낮게 나오는
    # 경우가 있어(`_CROSS_REFERENCE_MIN_CONFIDENCE` 참고), 본문 `text`만 보면
    # 그 문단 자체가 통째로 빠져 있어 못 찾는다.
    table_cells = table_cells + _find_cross_referenced_values(weak_text, weak_words, table_cells)

    # 표에서 확정된 값이 아닌 사람 이름은 위 교차 대조로도 못 찾는다 — 대조할
    # 원본 값이 없기 때문이다(`_find_weak_text_person_names` 참고). 그 문단
    # 자체에서 이름을 직접 다시 찾되, person 판정만 받아들여 인젝션 오탐 경로를
    # 막는다.
    findings = findings + _find_weak_text_person_names(
        weak_text, weak_words, [f["bbox"] for f in findings]
    )

    # 표에서 뽑은 값은 scan_text()가 끝난 뒤에 합친다 — XLSX의 구조화 탐지
    # (`scan.py`의 `_find_structured_xlsx_values`)와 다르게, 이 값들은 오탐
    # 제거 분류기(`_apply_classifier_filters`)나 인젝션 문장 분리를 거치지
    # 않는다. 의도적인 선택이다: 표 구조 자체가 이미 강한 신호이고(헤더가
    # 열의 의미를 확정해 준다), scan.py의 공유 파이프라인(PDF/DOCX/XLSX/TXT가
    # 다 같이 씀)을 건드리지 않고 이미지 전용으로 범위를 좁게 유지하려는
    # 목적도 있다 — 나중에 "왜 여기 분류기를 안 거치지?"하고 되돌리지 말 것.
    merged = _merge_table_cells(findings, table_cells)

    if rotation is not None:
        # 지금까지의 모든 bbox는 "바로 세운" 좌표계다 — 마스킹은 사용자가 올린
        # 원본 파일 위에 그리므로, 돌려주기 직전에 원본 좌표로 되돌린다.
        k, orig_w, orig_h = rotation
        for finding in merged:
            finding["bbox"] = _map_bbox_from_rotated(finding["bbox"], k, orig_w, orig_h)

    return merged
