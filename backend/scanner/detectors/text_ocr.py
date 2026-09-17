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
    """본문 글자 높이의 중앙값보다 훨씬 큰 글자(제목·로고)를 뺀다. `_OVERSIZED_HEIGHT_RATIO` 참고."""
    if not entries:
        return entries
    median_height = statistics.median(item[3] for item in entries)
    max_height = median_height * _OVERSIZED_HEIGHT_RATIO
    return [item for item in entries if item[3] <= max_height]


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


def _ocr_lines(path: str) -> list[list[tuple[str, tuple[float, float, float, float]]]]:
    """이미지 1장을 OCR해서 줄 단위로 묶는다. 각 줄은 (글자, 원본 픽셀 bbox) 목록이다."""
    _configure_tesseract_cmd()
    import pytesseract
    from PIL import Image

    with Image.open(path) as source:
        gray = source.convert("L")
        width, height = gray.size
        scaled = gray.resize((width * _UPSCALE, height * _UPSCALE), Image.LANCZOS)
        data = pytesseract.image_to_data(
            scaled, lang=_LANG, config=_TESSERACT_CONFIG, output_type=pytesseract.Output.DICT
        )

    entries: list[tuple[tuple[int, int, int], str, tuple, float]] = []
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
        bbox = (left / _UPSCALE, top / _UPSCALE, (left + w) / _UPSCALE, (top + h) / _UPSCALE)
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        entries.append((key, text, bbox, h / _UPSCALE))

    entries = _drop_oversized(entries)

    lines: list[list[tuple[str, tuple[float, float, float, float]]]] = []
    line_keys: list[tuple[int, int, int]] = []

    for key, text, bbox, _height in entries:
        if lines and line_keys[-1] == key:
            lines[-1].append((text, bbox))
        else:
            lines.append([(text, bbox)])
            line_keys.append(key)

    return [_merge_adjacent_syllables(line) for line in lines]


def _ocr_words(path: str) -> tuple[str, list[_Word]]:
    """이미지 1장을 OCR해서 (다시 만든 raw_text, 단어별 offset+bbox 목록)을 돌려준다.

    같은 줄의 단어는 공백으로 잇는다. 줄과 줄 사이는 원칙적으로 줄바꿈이지만,
    앞 줄이 라벨처럼 보이면(_looks_like_label) 공백으로 이어 붙인다 — 그래야
    "입금 계좌"(라벨 줄) 다음의 "국민 6127-02-384915"(값 줄)이 오탐 제거
    분류기에게 "계좌"라는 문맥을 잃지 않고 전달된다.
    """
    lines = _ocr_lines(path)

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
        text, words = _ocr_words(path)
    except Exception:      # noqa: BLE001 — 업로드 파일은 무엇이든 들어온다. tesseract가
        return []          # 없거나 이미지가 깨졌어도 이 검사만 건너뛰면 된다.

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
    return findings
