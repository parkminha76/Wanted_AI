"""신분증이 아닌 일반 이미지(인보이스, 스크린샷 등) 안의 글자를 OCR로 읽어
텍스트 파이프라인(rules.py/ner.py/models.py)을 그대로 돌린다.

왜 필요한가
-----------
id_detector.py(CNN)는 신분증 사진에 고정된 12개 영역(얼굴·주민번호·서명 등)만
찾도록 학습됐다. 얼굴도 신분증도 없는 일반 문서 사진(인보이스, 채팅 스크린샷,
영수증)을 올리면 CNN이 찾을 게 하나도 없어서 findings가 비고, 위험점수 0(안전)으로
나간다 — 그런데 그 안에 전화번호·계좌번호 같은 진짜 개인정보가 그대로 있을 수 있다
(실측: 2026-09-17, 인보이스 PNG에 전화번호·계좌번호가 있었는데 마스킹이 전혀 안 됨).

접근
----
Tesseract로 이미지 속 글자를 읽어 raw_text를 다시 만들고(각 단어가 raw_text의 어느
구간에서 왔는지도 같이 기록한다), scan.scan_text()를 그대로 불러 문서 텍스트와
똑같은 정확도(정규식+체크섬, NER, 인젝션, 오탐 제거)로 판정한다. 새 판정 로직을
따로 만들지 않는다 — 같은 값이라도 이미지에서 왔다고 다르게 판단할 이유가 없고,
로직을 둘로 쪼개면 한쪽만 개선되고 다른 쪽은 뒤처진다.

찾은 값의 offset(raw_text 기준)을 다시 그 단어(들)의 픽셀 bbox로 되짚어 돌려준다.
masking/mask.py의 `_mask_image`는 출처와 무관하게 bbox만 있으면 칠하므로, 여기서
새로 만질 코드가 없다.

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

import os
import re
import shutil
import statistics
from dataclasses import dataclass

# Windows 개발 환경은 Tesseract가 PATH에 없어서 실행 파일 경로를 직접 지정해야
# 한다. Docker(Linux)는 apt로 설치하면 PATH에 잡히므로 shutil.which로 먼저
# 확인하고, 없을 때만 이 후보 경로를 시도한다.
_TESSERACT_CMD_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)

# 한국어 문서이므로 한국어를 기본으로 하되 영어 라벨(Invoice, Villa 등)도 같이 읽는다.
_LANG = "kor+eng"

# 라벨처럼 작은 글자(14~16px)는 원본 해상도 그대로 돌리면 자모가 뭉개져 인식률이
# 뚝 떨어진다(실측: 2026-09-17, 업스케일 없이 "청구번호 01234"가 "ob uy a ou 42"로
# 깨짐). 2배로 키우고 흑백으로 바꾸면 라벨까지 대부분 정확히 읽힌다.
_UPSCALE = 2

# 카메라로 찍은 사진은 스캐너와 달리 몇 도씩 기울어 있는 게 보통이다. --psm 6은
# 글자가 수평이라고 가정하므로, 8도만 기울어도 글자를 통째로 못 읽는다(실측:
# 2026-09-17, 8도 기울인 청구서에서 "국민 6127-02-384915" 계좌번호 줄 전체가
# 사라지고 "입금 계좌"가 "Bes 계좌"로 깨짐). OCR 직전에 이 각도만큼 되돌린다.
#
# 각도가 이 미만이면 보정 자체가 인식률에 도움이 안 돼 건드리지 않는다. 이 초과면
# 보정하지 않는다 — 신분증처럼 얼굴·그림이 글자보다 넓은 사진에서는 잉크 마스크
# 기반 각도 추정이 글자 각도가 아니라 엉뚱한 값을 낼 수 있어(실측: 얼굴 실루엣이
# 있는 신분증 사진에서는 0도로 나와 무해했지만, 항상 그렇다는 보장은 없다),
# 과도한 보정치는 버리고 원본 그대로 돌리는 쪽이 안전하다.
_MIN_DESKEW_ANGLE = 0.3
_MAX_DESKEW_ANGLE = 20.0

# 표가 있는 서식(지원서 등)에서 한 줄 전체가 raw_text에 통째로 안 나타나는
# 경우가 있다(실측: 2026-09-17, 아르바이트 지원서 사진에서 "성 명 이예지",
# "생 년 월 일" 줄이 --psm 3/4/6/11/12 전부에서 사라짐). hOCR로 원인을 보면
# Tesseract의 레이아웃 분석이 표 테두리 선 때문에 그 영역을 `ocr_photo`(사진)로
# 오분류해서 생기는 문제지만, 실제 인식에 쓰는 --psm 6은 이 분류 단계 자체를
# 건너뛰어 하나로 짚어 고칠 오분류 영역이 없다 — 원인 위치를 안다고 바로
# 고칠 수 있는 게 아니다.
#
# 그래서 원인이 아니라 **결과**로 접근한다: 정상 인식된 두 줄 사이에 글자
# 한 줄 높이 이상 비어 보이는 구간이 있으면, 그 구간만 따로 잘라 표 테두리
# 선을 지우고 다시 OCR을 돌려 본다(`_recover_gap_lines` 참고). 이렇게 좁게
# 잘라내면 그 구간 안에서 표 전체가 아니라 그 한 줄만 보이므로 앞서 말한
# `ocr_photo` 오분류가 애초에 일어나지 않는다.
#
# 문서 전체에 선 지우기를 무조건 적용하는 방법도 시도해봤지만, 실측(다른
# 이력서 사진)에서 이미 정상 인식되던 줄까지 건드려 오히려 깨졌다("성"이
# "a"로, "Liceria & Co."가 "Co."로 잘림) — 글자가 테두리 선에 바로 붙어 있으면
# 선을 지우면서 글자 일부도 같이 지워지기 때문이다. 이미 뭔가 읽힌 구간은
# 절대 건드리지 않고, **아무것도 못 읽은 구간에서만** 다시 시도하면 이 위험이
# 사라진다 — 이미 비어 있던 자리이므로 다시 시도해서 나빠질 게 없다.
_GAP_RECHECK_MIN_HEIGHT = 20.0

# 구간을 위아래로 넓혀 잡으면(여유를 주면) 그만큼 이미 인식된 이웃 줄의
# 글자 일부가 다시 크롭 안에 들어온다 — 실측(합성 테스트 이미지)으로 확인:
# 여유 8px만 줘도 "받는 분"/"김하늘"의 위아래 획 일부가 다시 잡혀 "ㄴㄴ", "9",
# "Ce" 같은 잡음 줄이 생기고, 그 잡음 줄이 "입금 계좌"와 "국민 ..." 사이에
# 끼어들어 라벨-값 이어붙이기(`_looks_like_label`)가 깨져 계좌번호 탐지가
# 통째로 실패했다. 그래서 여유를 주지 않는다 — 구간 경계에 걸친 글자 일부를
# 놓칠 수는 있지만, 이미 잘 읽히던 줄을 다시 건드려 깨뜨리는 쪽보다 안전하다.
_GAP_RECHECK_PADDING = 0.0

# 긴 직선(길이 40px 이상)만 후보로 보고, 그중에서도 두께 5px 미만인 것만 진짜
# 테두리 선으로 본다. 어두운 헤더 박스처럼 두꺼운 사각형은 긴 직선 후보에도
# 걸리지만(가로/세로 어느 방향으로 열어도 살아남음) 5px 두께로 다시 열었을 때도
# 살아남으므로 걸러지고, 진짜 테두리 선(실측 1~3px)만 두께 필터에서 사라져
# 지워진다.
_LINE_MIN_LENGTH = 40
_LINE_MAX_THICKNESS = 5

# --psm 6: "균일한 텍스트 블록 하나"로 가정한다. 기본값(3, 자동 레이아웃 분석)은
# 어두운 헤더 박스와 밝은 본문이 섞인 이 레이아웃에서 순서를 잘못 추정해 라벨
# 여러 개를 통째로 놓쳤다(실측: 같은 이미지에서 "결제 내역", "받는 분" 자체가
# 안 잡힘). 6으로 바꾸니 모두 잡혔다.
_TESSERACT_CONFIG = "--psm 6"

# 이 신뢰도 아래는 잡음으로 보고 raw_text에서 뺀다. 장식체 로고("Villa")나 필기체
# 서명("Signature")이 30번대 확신도의 알파벳 잡음으로 잡히는 것을 실측으로 확인했다
# (개인정보 판정에는 안 쓰이는 자리라 걸러도 손해가 없다).
_MIN_WORD_CONFIDENCE = 40.0

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

# 실제 개인정보 값(전화번호·계좌번호·이름)은 항상 본문 크기로 적힌다 — 제목이나
# 로고를 개인정보 크기로 인쇄하는 문서는 없다. 실측(2026-09-17): 이 인보이스에서
# 제목 "INVOICE"는 83px, 본문 라벨/값은 20~26px로 3~4배 차이가 났고, 그 제목이
# NER에 "회사명"으로 오탐되어 마스킹 상자가 머리말 절반을 뒤덮었다. 그래서 이미지
# 전체의 본문 글자 높이(중앙값)보다 이 배수 이상 큰 글자는 장식 제목·로고로 보고
# OCR 결과에서 아예 뺀다 — 애초에 못 읽은 것과 같아지므로 뒤 단계가 오판할 일이
# 없어진다.
_OVERSIZED_HEIGHT_RATIO = 1.8

# Tesseract가 이름 같은 한 단어를 한글 음절 하나씩 따로 뱉는 경우가 있다(실측:
# 서명란의 "정수연"이 "정"/"수"/"연" 세 단어로 쪼개져 NER이 이름으로 인식하지
# 못함). 정상적인 단어 사이 공백(이 이미지에서 실측 27~2090px, 서로 다른 열이
# 한 줄로 묶인 경우까지 포함)보다 훨씬 좁게 붙어 있을 때만(실측 11~28px) 다시
# 이어 붙인다 — 글자 높이의 이 비율보다 가까우면 "붙어 있다"로 본다.
_SYLLABLE_GAP_RATIO = 0.9
_SINGLE_HANGUL = re.compile(r"^[가-힣]$")

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
# 넘으면 표를 벗어난 것으로 본다 — `_recover_gap_lines`가 이미 "비정상적으로
# 큰 세로 간격 = 구조적 경계"로 판단하는 것과 같은 방식이다. 가로 겹침만으로는
# 표가 폭이 넓을 때(다음 섹션 제목도 왼쪽 정렬이면 겹쳐 보임) 잘 안 걸려서
# 보조 신호로만 같이 쓴다.
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


_configured = False


def _configure_tesseract_cmd() -> None:
    """pytesseract가 부를 tesseract 실행 파일 경로를 한 번만 찾아 둔다."""
    global _configured
    if _configured:
        return
    _configured = True
    if shutil.which("tesseract"):
        return
    import pytesseract

    for candidate in _TESSERACT_CMD_CANDIDATES:
        if os.path.isfile(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


@dataclass
class _Word:
    start: int          # 이 모듈이 다시 만든 raw_text 기준 offset
    end: int
    bbox: tuple[float, float, float, float]   # 원본 이미지 픽셀 좌표 (업스케일 되돌림)


def _drop_oversized(
    entries: list[tuple[tuple[int, int, int], str, tuple, float]],
) -> list[tuple[tuple[int, int, int], str, tuple, float]]:
    """제목·로고처럼 줄 전체가 본문보다 훨씬 큰 글자를 뺀다. `_OVERSIZED_HEIGHT_RATIO` 참고.

    토큰 하나하나의 높이가 아니라 **그 토큰이 속한 줄의 대표 높이**로 판단한다.
    Tesseract가 매기는 bbox 높이는 한글 음절과 영문·숫자 글리시프가 같은 폰트
    크기에서도 서로 다르게 나온다(실측: 2026-09-17, 이력서 사진에서 "생년월일"은
    9px인데 바로 옆 "1996.05.24"는 17px로 잡혀, 토큰 단위로 비교하면 생년월일
    본문이 제목급 오탐 없이도 통째로 걸러짐 — 실제 생년월일이 마스킹에서 빠졌다).
    줄 단위 대표값(그 줄 토큰들의 중앙값)으로 비교하면 한 줄 안에서의 이런 편차는
    묻히고, 줄 전체가 진짜로 큰 제목만 걸러진다.
    """
    if not entries:
        return entries
    heights_by_line: dict[tuple[int, int, int], list[float]] = {}
    for key, _text, _bbox, height in entries:
        heights_by_line.setdefault(key, []).append(height)
    line_height = {key: statistics.median(hs) for key, hs in heights_by_line.items()}

    doc_median = statistics.median(line_height.values())
    max_height = doc_median * _OVERSIZED_HEIGHT_RATIO
    return [item for item in entries if line_height[item[0]] <= max_height]


def _touching(a: tuple, b: tuple) -> bool:
    """b가 a 바로 옆에 거의 붙어 있는가(같은 단어의 다음 음절일 가능성)."""
    gap = b[0] - a[2]
    height = max(a[3] - a[1], b[3] - b[1])
    if height <= 0:
        return False
    return gap <= height * _SYLLABLE_GAP_RATIO


def _union(a: tuple, b: tuple) -> tuple:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _merge_adjacent_syllables(
    line_words: list[tuple[str, tuple]],
) -> list[tuple[str, tuple]]:
    """한 줄 안에서 붙어 있는 한글 음절 하나짜리 토큰들을 원래 단어로 되붙인다."""
    merged: list[tuple[str, tuple]] = []
    previous_bbox: tuple | None = None
    previous_was_single = False

    for text, bbox in line_words:
        is_single = bool(_SINGLE_HANGUL.match(text))
        if merged and previous_was_single and is_single and _touching(previous_bbox, bbox):
            prev_text, prev_bbox = merged[-1]
            merged[-1] = (prev_text + text, _union(prev_bbox, bbox))
        else:
            merged.append((text, bbox))
        previous_bbox = bbox
        previous_was_single = is_single

    return merged


def _deskew(gray_image) -> tuple:
    """기울어진 사진을 OCR 전에 수평으로 되돌린다. `_MIN/_MAX_DESKEW_ANGLE` 참고.

    (되돌린 PIL 이미지, 원본 좌표로 되짚을 역행렬) 튜플을 돌려준다. 보정하지
    않았으면 역행렬 자리는 None이다 — 호출부가 그러면 좌표를 그대로 쓴다.
    """
    import cv2
    import numpy as np
    from PIL import Image

    array = np.array(gray_image)
    _, thresh = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(thresh > 0))
    if coords.size == 0:
        return gray_image, None

    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if not (_MIN_DESKEW_ANGLE <= abs(angle) <= _MAX_DESKEW_ANGLE):
        return gray_image, None

    height, width = array.shape
    center = (width / 2, height / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        array, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return Image.fromarray(rotated), cv2.invertAffineTransform(matrix)


def _remove_table_lines(gray_image):
    """표 테두리로 쓰인 가늘고 긴 직선을 지운다. `_LINE_MIN_LENGTH/_LINE_MAX_THICKNESS` 참고.

    선을 지우고 남은 자리는 흰색으로 채운다 — 실제 글자는 이렇게 길고 곧은 직선
    성분을 만들지 않으므로(자모는 짧고 굽어 있다) 지워질 위험이 없다.
    """
    import cv2
    import numpy as np
    from PIL import Image

    array = np.array(gray_image)
    _, thresh = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    def _thin_lines(thin_size: tuple, thick_size: tuple):
        thin_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, thin_size)
        thick_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, thick_size)
        candidates = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, thin_kernel)
        thick = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, thick_kernel)
        return cv2.bitwise_and(candidates, cv2.bitwise_not(thick))

    horizontal = _thin_lines(
        (_LINE_MIN_LENGTH, 1), (_LINE_MIN_LENGTH, _LINE_MAX_THICKNESS)
    )
    vertical = _thin_lines(
        (1, _LINE_MIN_LENGTH), (_LINE_MAX_THICKNESS, _LINE_MIN_LENGTH)
    )
    lines_mask = cv2.dilate(
        cv2.bitwise_or(horizontal, vertical),
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
    )

    cleaned = array.copy()
    cleaned[lines_mask > 0] = 255
    return Image.fromarray(cleaned)


def _words_from_tesseract_data(data: dict, y_offset: float = 0.0) -> list[tuple]:
    """pytesseract의 raw dict 출력에서 신뢰도 필터를 거친 (key, text, bbox, height) 목록을 뽑는다.

    `_ocr_lines`의 본 OCR과 `_recover_gap_lines`의 보충 OCR이 같은 추출 규칙을
    쓰도록 공통화한 것 — 규칙이 갈리면(예: 신뢰도 기준이 서로 달라짐) 한쪽만
    고치고 잊는 실수가 난다.

    `y_offset`은 보충 OCR이 원본 전체가 아니라 잘라낸 구간만 돌렸을 때, 그
    구간의 y 시작 위치를 다시 더해 전체 이미지 좌표로 되돌리는 용도다.
    """
    entries: list[tuple] = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        try:
            confidence = float(data["conf"][i])
        except (TypeError, ValueError):
            confidence = -1.0
        if not text or confidence < _MIN_WORD_CONFIDENCE:
            continue

        left, top = data["left"][i], data["top"][i]
        w, h = data["width"][i], data["height"][i]
        bbox = (
            left / _UPSCALE,
            y_offset + top / _UPSCALE,
            (left + w) / _UPSCALE,
            y_offset + (top + h) / _UPSCALE,
        )
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        entries.append((key, text, bbox, h / _UPSCALE))
    return entries


def _group_into_lines(
    entries: list[tuple],
) -> list[list[tuple[str, tuple]]]:
    """`_drop_oversized`를 거친 (key, text, bbox, height) 목록을 같은 key끼리 묶어 줄로 만든다."""
    lines: list[list[tuple[str, tuple]]] = []
    line_keys: list[tuple] = []
    for key, text, bbox, _height in entries:
        if lines and line_keys[-1] == key:
            lines[-1].append((text, bbox))
        else:
            lines.append([(text, bbox)])
            line_keys.append(key)
    return [_merge_adjacent_syllables(line) for line in lines]


def _recover_gap_band(deskewed_image, top: float, bottom: float) -> list[list[tuple[str, tuple]]]:
    """[top, bottom) 구간만 잘라 표 테두리 선을 지우고 다시 OCR한다. 짧으면(`_GAP_RECHECK_MIN_HEIGHT` 미만) 건너뛴다."""
    if bottom - top < _GAP_RECHECK_MIN_HEIGHT:
        return []

    import pytesseract
    from PIL import Image

    width, height = deskewed_image.size
    top = max(0, int(top - _GAP_RECHECK_PADDING))
    bottom = min(height, int(bottom + _GAP_RECHECK_PADDING))
    if bottom <= top:
        return []

    crop = _remove_table_lines(deskewed_image.crop((0, top, width, bottom)))
    crop_width, crop_height = crop.size
    scaled = crop.resize((crop_width * _UPSCALE, crop_height * _UPSCALE), Image.LANCZOS)
    data = pytesseract.image_to_data(
        scaled, lang=_LANG, config=_TESSERACT_CONFIG, output_type=pytesseract.Output.DICT
    )
    entries = _drop_oversized(_words_from_tesseract_data(data, y_offset=top))
    return _group_into_lines(entries)


def _recover_gap_lines(
    deskewed_image, lines: list[list[tuple[str, tuple]]]
) -> list[list[tuple[str, tuple]]]:
    """글자가 통째로 비어 보이는 구간이 있으면 그 구간만 잘라 다시 OCR한다.

    이미 읽힌 두 줄 사이뿐 아니라 문서 맨 앞(첫 줄 위)과 맨 뒤(마지막 줄 아래)도
    본다 — 실측(합성 표 이미지)으로 확인: 표 전체가 통째로 안 읽히면 표 위
    제목줄 하나만 인식되고 그 아래로는 "다음 줄"이 아예 없어, 두 줄 사이만
    보는 방식으로는 표 전체를 영영 되찾을 수 없었다.
    문서 맨 앞/맨 뒤가 원래 빈 여백인 경우도 있지만, 그런 곳은 다시 시도해도
    아무것도 안 나올 뿐이라 손해가 없다(`_GAP_RECHECK_MIN_HEIGHT` 주석 참고).

    이미 읽힌 줄 자체는 절대 다시 건드리지 않는다 — 구간을 그 줄들의 경계
    밖으로 자르므로, 여기서 표 테두리 선을 지우다가 이미 정상 인식된 글자를
    깎아내는 일이 없다.
    """
    if not lines:
        return lines

    width, height = deskewed_image.size
    spans = [
        (min(b[1] for _, b in line), max(b[3] for _, b in line)) for line in lines
    ]

    result: list[list[tuple[str, tuple]]] = []
    result.extend(_recover_gap_band(deskewed_image, 0, spans[0][0]))
    result.append(lines[0])
    for index in range(1, len(lines)):
        result.extend(
            _recover_gap_band(deskewed_image, spans[index - 1][1], spans[index][0])
        )
        result.append(lines[index])
    result.extend(_recover_gap_band(deskewed_image, spans[-1][1], height))
    return result


def _map_bbox_to_original(bbox: tuple, inverse_matrix) -> tuple:
    """되돌리기 전(원본) 이미지 좌표로 bbox를 되짚는다.

    되돌린 이미지에서 축에 나란한 사각형은 원본에서는 기울어진 사각형이 된다.
    거기에 딱 맞는 사각형(bbox)을 다시 만들면 실제 글자보다 넓어지지만, 마스킹이
    덜 가리는 쪽보다는 넓게 가리는 쪽이 안전하다.
    """
    if inverse_matrix is None:
        return bbox
    import numpy as np

    left, top, right, bottom = bbox
    corners = np.array(
        [[left, top, 1.0], [right, top, 1.0], [right, bottom, 1.0], [left, bottom, 1.0]]
    )
    mapped = corners @ inverse_matrix.T
    return (
        float(mapped[:, 0].min()),
        float(mapped[:, 1].min()),
        float(mapped[:, 0].max()),
        float(mapped[:, 1].max()),
    )


def _ocr_lines(path: str) -> list[list[tuple[str, tuple[float, float, float, float]]]]:
    """이미지 1장을 OCR해서 줄 단위로 묶는다. 각 줄은 (글자, 원본 픽셀 bbox) 목록이다."""
    _configure_tesseract_cmd()
    import pytesseract
    from PIL import Image

    with Image.open(path) as source:
        gray = source.convert("L")
        deskewed, inverse_matrix = _deskew(gray)
        width, height = deskewed.size
        scaled = deskewed.resize((width * _UPSCALE, height * _UPSCALE), Image.LANCZOS)
        data = pytesseract.image_to_data(
            scaled, lang=_LANG, config=_TESSERACT_CONFIG, output_type=pytesseract.Output.DICT
        )

        # 되돌리기 전(deskew) 좌표계로 줄을 다 묶은 다음에 원본 좌표로 옮긴다 —
        # `_recover_gap_lines`가 여기서 자르고 다시 붙이는 `deskewed` 이미지와
        # 같은 좌표계를 써야 구간이 어긋나지 않는다.
        entries = _drop_oversized(_words_from_tesseract_data(data))
        lines = _group_into_lines(entries)
        lines = _recover_gap_lines(deskewed, lines)

    return [
        [(text, _map_bbox_to_original(bbox, inverse_matrix)) for text, bbox in line]
        for line in lines
    ]


def _ocr_words(path: str) -> tuple[str, list[_Word]]:
    """이미지 1장을 OCR해서 (다시 만든 raw_text, 단어별 offset+bbox 목록)을 돌려준다."""
    return _words_from_lines(_ocr_lines(path))


def _words_from_lines(
    lines: list[list[tuple[str, tuple[float, float, float, float]]]],
) -> tuple[str, list[_Word]]:
    """`_ocr_lines`가 만든 줄 목록을 raw_text 하나로 이어붙인다.

    같은 줄의 단어는 공백으로 잇는다. 줄과 줄 사이는 원칙적으로 줄바꿈이지만,
    앞 줄이 라벨처럼 보이면(_looks_like_label) 공백으로 이어 붙인다 — 그래야
    "입금 계좌"(라벨 줄) 다음의 "국민 6127-02-384915"(값 줄)이 오탐 제거
    분류기에게 "계좌"라는 문맥을 잃지 않고 전달된다.

    `detect()`가 이 `lines`를 표 열 인식(`_find_table_column_cells`)에도 같이
    쓴다 — OCR을 두 번 돌리지 않으려고 `_ocr_words(path)`에서 분리했다.
    """
    parts: list[str] = []
    words: list[_Word] = []
    cursor = 0

    for line_index, line_words in enumerate(lines):
        if line_index > 0:
            previous_text = "".join(text for text, _ in lines[line_index - 1])
            separator = " " if _looks_like_label(previous_text) else "\n"
            parts.append(separator)
            cursor += len(separator)

        for word_index, (text, bbox) in enumerate(line_words):
            if word_index > 0:
                parts.append(" ")
                cursor += 1
            start = cursor
            parts.append(text)
            cursor += len(text)
            words.append(_Word(start=start, end=cursor, bbox=bbox))

    return "".join(parts), words


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


def _match_header_labels(
    line: list[tuple[str, tuple]],
) -> list[tuple[int, int, str, str]]:
    """줄에서 `_COLUMN_FIELD_LABELS`의 라벨을 찾아 (시작 단어 인덱스, 끝 단어 인덱스, 라벨, 필드유형) 목록을 돌려준다.

    라벨과 정확히 같은 단어 하나만 찾지 않는다 — Tesseract가 "회사명"을
    "회사"+"명"처럼 단어 경계와 다르게 쪼개는 경우가 있다(`_merge_adjacent_syllables`는
    한 글자짜리 음절끼리만 다시 붙이므로 이런 분할은 안 고쳐진다). 그래서
    `_looks_like_label`처럼 줄 전체를 이어붙인 문자열에서 라벨을 찾은 뒤, 그
    위치가 원래 몇 번째 단어(들)에 걸쳐 있었는지 역으로 찾는다.
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
    return cells


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
) -> list[tuple[str, tuple]]:
    """헤더 다음 줄들을 훑어 대상 열의 셀 값들을 모은다. `_TABLE_ROW_GAP_RATIO`/`_MAX_TABLE_ROWS` 참고.

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
        if not cell_words:
            centers = [(b[0] + b[2]) / 2 for _, b in line]
            touches_first = any(
                first_column_range[0] <= c < first_column_range[1] for c in centers
            )
            touches_last = any(
                last_column_range[0] <= c < last_column_range[1] for c in centers
            )
            if not (touches_first and touches_last):
                break

        if cell_words:
            cell_text = " ".join(text for text, _ in cell_words)
            cell_bbox = cell_words[0][1]
            for _text, bbox in cell_words[1:]:
                cell_bbox = _union(cell_bbox, bbox)
            rows.append((cell_text, cell_bbox))

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
        # 글자를 통째로 삼켜버린다. 표 테두리 선 때문에 Tesseract가 "회사명"
        # 하나만 다른 헤더들과 분리된 줄로 뽑아내는 경우가 실제로 있어서
        # (`_GAP_RECHECK_MIN_HEIGHT` 주석 참고), 이럴 땐 아무것도 안 잡는 쪽이
        # 안전하다 — 지금과 같은 "탐지 안 됨"이지, 다른 정상 결과까지 덮어쓰는
        # "잘못된 거대한 셀"보다 훨씬 낫다.
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
    """
    try:
        lines = _ocr_lines(path)
        text, words = _words_from_lines(lines)
        table_cells = _find_table_column_cells(lines)
    except Exception:      # noqa: BLE001 — 업로드 파일은 무엇이든 들어온다. tesseract가
        return []          # 없거나 이미지가 깨졌어도 이 검사만 건너뛰면 된다. 표 열
                            # 인식(`_find_table_column_cells`)은 순수 함수라 원래
                            # 실패할 일이 거의 없지만, OCR 자체는 성공했는데 이
                            # 검사만으로 전체가 죽는 일은 없게 같이 감싼다.

    if not text.strip():
        return []

    from backend.scanner import scan   # 지연 임포트 — scan.py가 이 모듈을 불러오므로 순환을 피한다

    result = scan.scan_text(text, meta={"filename": path})

    findings: list[dict] = []
    for finding in result.findings:
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
