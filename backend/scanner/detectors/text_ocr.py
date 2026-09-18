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

# 서식류(인보이스·명세서)는 "라벨 줄" 다음에 "값 줄"이 따로 오는 경우가 흔하다
# ("입금 계좌" 다음 줄에 "국민 6127-02-384915"). 줄마다 무조건 줄바꿈으로 끊으면
# 값 줄에는 "계좌"라는 단어가 없어서, 오탐 제거 분류기가 문맥만 보고 진짜
# 계좌번호를 주문번호 같은 하드 네거티브로 착각한다(실측: 2026-09-17, 이
# 인보이스에서 계좌번호가 통째로 걸러짐 — prob_positive 0.444). 숫자도 문장부호도
# 없는 짧은 줄은 "라벨"로 보고 다음 줄과 공백으로 이어 붙여, 분류기가 라벨과 값을
# 한 문맥으로 보게 한다.
_LABEL_MAX_LEN = 12
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
) -> tuple[list[list[tuple[str, tuple[float, float, float, float]]]], list[bool]]:
    """이미지 1장을 OCR해서 줄 단위로 묶는다. 각 줄은 (글자, 원본 픽셀 bbox) 목록이다.

    두 번째 반환값은 각 줄이 제목 크기(`_oversized_row_flags` 참고)였는지를 같은
    순서로 나열한 목록이다.
    """
    reader = _get_reader()
    results = reader.readtext(path)

    detections: list[tuple[str, tuple]] = []
    for polygon, text, confidence in results:
        text = text.strip()
        if not text or confidence < _EASYOCR_MIN_CONFIDENCE:
            continue
        detections.append((text, _polygon_to_bbox(polygon)))

    rows = _group_into_rows(detections)
    flags = _oversized_row_flags(rows)
    return rows, flags


def _ocr_words(path: str) -> tuple[str, list[_Word]]:
    """이미지 1장을 OCR해서 (다시 만든 raw_text, 단어별 offset+bbox 목록)을 돌려준다."""
    lines, flags = _ocr_lines(path)
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
    """
    boxes = [w.bbox for w in words if w.start < end and start < w.end]
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


def _bboxes_overlap(a: tuple, b: tuple) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _merge_table_cells(findings: list[dict], table_cells: list[dict]) -> list[dict]:
    """표에서 뽑은 셀 값을 기존 findings에 합친다.

    bbox가 겹치면(단순 사각형 교차 판정) 겹치는 기존 finding **전부**를
    지우고 표에서 뽑은 값으로 교체한다(표 구조가 더 확실한 신호이므로 우선—
    하나만 지우면 지저분한 finding이 같이 남는다). 안 겹치면 새 finding으로
    그냥 추가한다 — NER이 아예 놓친 값("Fauget" 등)을 이렇게 새로 잡는다.
    """
    merged = list(findings)
    for cell in table_cells:
        merged = [f for f in merged if not _bboxes_overlap(f["bbox"], cell["bbox"])]
        merged.append(cell)
    return merged


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
        lines, oversized_flags = _ocr_lines(path)
        text, words, oversized_ranges = _words_from_lines(lines, oversized_flags)
        table_cells = _find_table_column_cells(lines)
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
    # 표에서 뽑은 값은 scan_text()가 끝난 뒤에 합친다 — XLSX의 구조화 탐지
    # (`scan.py`의 `_find_structured_xlsx_values`)와 다르게, 이 값들은 오탐
    # 제거 분류기(`_apply_classifier_filters`)나 인젝션 문장 분리를 거치지
    # 않는다. 의도적인 선택이다: 표 구조 자체가 이미 강한 신호이고(헤더가
    # 열의 의미를 확정해 준다), scan.py의 공유 파이프라인(PDF/DOCX/XLSX/TXT가
    # 다 같이 씀)을 건드리지 않고 이미지 전용으로 범위를 좁게 유지하려는
    # 목적도 있다 — 나중에 "왜 여기 분류기를 안 거치지?"하고 되돌리지 말 것.
    return _merge_table_cells(findings, table_cells)
