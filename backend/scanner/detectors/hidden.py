"""서식과 보이지 않는 문자로 감춰진 텍스트를 찾는다.

AI 모델이 전혀 필요 없는 규칙 검사인데, 데모에서 가장 임팩트가 큰 부분이다.

반환 형식은 rules.py와 같다 (scan.py가 그대로 받아 Finding으로 바꾼다):
    [{"field": "hidden_text", "value": str, "start": int, "end": int,
      "confidence": float, "reason": str, "evidence": dict}, ...]

이 파일의 두 가지 원칙
----------------------
1. **span 하나에 finding 하나.** 흰 글씨이면서 1pt이면 근거를 evidence에 모아 담고
   finding은 하나만 낸다. 두 개를 내면 한 문장이 25점을 두 번 받는다.
2. **자리는 근거가 아니다.** 머리말·꼬리말·텍스트상자·주석은 "눈에 잘 안 띄는 자리"일
   뿐 숨겨진 것이 아니다. 모든 문서에 머리말이 있다. 신고하려면 그 자리에서 색·크기·
   서식 속성 같은 **실제 은닉 신호**가 나와야 한다.

임계값을 정한 방법
------------------
`backend/scanner/tests/`의 숨긴 문서 24개 + 정상 문서 9개를 돌려서 맞췄다.
놓치면 내리고, 정상 문서가 걸리면 올렸다. 확인은 아래 한 줄로 다시 돌릴 수 있다.

    uv run python backend/scanner/tests/check_thresholds.py

측정 근거와 회차 기록은 `backend/scanner/tests/README.md`에 있다.
"""

from __future__ import annotations

import re

from backend.scanner.detectors import models, rules


# ---------------------------------------------------------------------------
# 임계값 — 2026-09-12 7회차까지 돌려서 맞춘 값
# ---------------------------------------------------------------------------

# A급: 정상 문서에 나올 이유가 없는 문자 (Bidi **재정의**, 태그 문자).
#
# 3개 -> 1개로 내렸다. 글자 순서를 뒤집는 공격은 여는 문자와 닫는 문자 2개면 성립하고,
# 그 2개가 긴 문단에 들어가면 밀도까지 빠져나간다(100자 문단이면 정확히 2.0%).
# 대조군의 A급은 전부 0개라서, 1개로 내려도 오탐이 늘지 않는다.
INVISIBLE_A_MIN_COUNT = 1

# Bidi급: 글자 순서를 바꾸지만 **정상 문서에도 쓰이는** 제어 문자
# (임베딩 LRE/RLE/PDF, isolate LRI/RLI/FSI/PDI).
#
# 7회차(2026-09-12)에 A급에서 분리했다. 이 일곱 개는 아랍어·히브리어를 인용한 문서라면
# 워드·InDesign·웹 CMS가 그냥 내보내는 값이다. 특히 isolate 네 개는 유니코드가
# 임베딩 대신 쓰라고 **권장**하는 최신 표기라 앞으로 더 흔해진다.
# A급에 두면 아랍 거래처 상호를 인용한 정상 계약서가 확신도 0.9로 걸린다
# (실측: 위험점수 38.1 = 노란불).
#
# 그렇다고 빼면 임베딩으로 순서를 뒤집는 Trojan Source를 통째로 놓친다. 그래서
# **개수는 1개부터 보되(A급과 같다) 복원 검사를 통과해야 신고한다**(B급과 같다).
# 정상 인용문은 되돌려봐야 뒤집힌 글자만 나오고, 공격은 지시문이 통째로 나온다.
INVISIBLE_BIDI_MIN_COUNT = 1

# B급: 정상 문서에 흔한 문자 (제로폭, BOM, soft hyphen, 방향 표시).
# 개수·밀도를 넘겨도 여기서 바로 신고하지 않는다. 아래 복원 검사를 통과해야 한다.
INVISIBLE_B_MIN_COUNT = 3
INVISIBLE_B_MAX_DENSITY = 0.02

# 복원 검사를 통과하지 못해도 이 밀도를 넘으면 그것만으로 신고한다.
#
# 복원 검사는 오탐을 막는 좋은 장치지만 `models.is_injection()`에 전적으로 기댄다.
# 지금 그 함수는 한국어 키워드 6개짜리 임시 구현이라, 글자마다 제로폭을 끼운
# 영어 지시문이 **위험점수 0점(초록불)**으로 통과한다(실측 2026-09-12).
# 판정 근거를 한 군데에만 걸어두면 그 한 군데가 비어 있을 때 통째로 새는 셈이다.
#
# 그래서 "어떤 정상 문서도 이만큼은 아니다"라는 선을 하나 더 둔다. 대조군 9개의
# span별 최대 밀도는 13.8%(clean/05 아랍어)이고, 글자마다 제로폭을 끼운 공격은
# 49.6%다. 25%는 그 사이에서 양쪽 모두에 넉넉한 자리다.
INVISIBLE_B_EXTREME_DENSITY = 0.25

# 밀도의 분모는 span 하나(문단·줄·셀 하나)다. 문서 전체로 잡으면 5만 자짜리 계약서에
# 200개를 심어도 0.4%로 통과한다.
#
# 반대로 짧은 span에서는 밀도가 의미가 없다. 15자짜리 채팅에 이모지 하나면 20%다.
# 그래서 짧으면 밀도를 아예 보지 않고 개수만 본다.
INVISIBLE_DENSITY_MIN_LENGTH = 50

# 글자색과 배경색의 RGB 거리가 이보다 가까우면 안 보이는 것으로 본다.
# 정확히 같은 값만 보면 #fffffe 같은 회피를 놓친다.
COLOR_DISTANCE_THRESHOLD = 30

# 이보다 작은 글자는 사람이 읽을 수 없다.
MIN_READABLE_FONT_SIZE = 2.0


# ---------------------------------------------------------------------------
# 보이지 않는 문자 목록
# ---------------------------------------------------------------------------

# A급 — 정상 문서에 나올 이유가 없다.
#
# **재정의(override) 둘만 남겼다.** 유니코드는 LRO/RLO를 쓰지 말라고 못박았고, 지금
# 이 둘을 내보내는 정상 편집기는 없다. Trojan Source 논문이 예제로 쓰는 것도 이 둘이다.
# 임베딩·isolate는 겉모습이 비슷하지만 정상 문서에 쓰이므로 아래 INVISIBLE_BIDI로
# 뺐다 (7회차, 2026-09-12).
INVISIBLE_A = re.compile(
    "[\u202d\u202e"           # LRO, RLO — Bidi 재정의 (Trojan Source)
    "\U000e0000-\U000e007f"   # 태그 문자 (ASCII smuggling)
    "]"
)

# Bidi급 — 글자 순서를 바꾸지만 정상 문서에도 쓰인다. 복원 검사를 통과해야 신고한다.
INVISIBLE_BIDI = re.compile(
    "[\u202a-\u202c"          # LRE, RLE, PDF — 임베딩 (구식이지만 아직 현역)
    "\u2066-\u2069"           # LRI, RLI, FSI, PDI — isolate (유니코드 권장 표기)
    "]"
)

# B급 — 정상 문서에 흔하다.
INVISIBLE_B = re.compile(
    "[\u200b-\u200f"          # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "\u2060-\u2064"           # word joiner, invisible operators
    "\ufeff\u00ad\u034f"      # BOM, soft hyphen, CGJ
    "]"
)

# 이모지. ZWJ가 이모지를 잇는 용도면 세지 않기 위해 필요하다.
# 변형 선택자(\ufe0f)와 피부색 수정자도 이모지 쪽에 포함시킨다 —
# 하트+불꽃 이모지처럼 ZWJ 바로 앞이 \ufe0f인 조합이 있기 때문이다.
EMOJI = re.compile(
    "[\U0001f000-\U0001faff"          # 그림 이모지 대부분
    "\u2600-\u27bf\u2b00-\u2bff"      # 기호·화살표류
    "\ufe0f\U0001f3fb-\U0001f3ff"     # 변형 선택자, 피부색 수정자
    "]"
)

ZWJ = "\u200d"
BOM = "\ufeff"
TAG_BLOCK_START = 0xE0000

# Bidi 제어 문자 — 복원할 때 걷어낸다.
_BIDI_CONTROLS = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"

# 화면에 보여줄 근거 문구.
_REASONS = {
    "render_mode": "PDF 렌더 모드 3 — 글자를 배치하되 화면에 그리지 않는다",
    "opacity": "투명도 0 — 색·크기 검사를 통과하면서 화면에는 안 보인다",
    "font_size": "사람이 읽을 수 없는 글자 크기",
    "color": "글자색이 배경색과 구분되지 않는다",
    "color_unknown_bg": "흰 글씨 — 배경색을 알 수 없어 흰 배경으로 가정했다",
    "vanish": "워드의 숨김 서식(w:vanish)",
    "web_hidden": "워드의 웹 보기 숨김 서식",
    "blank_format": "엑셀 사용자 지정 서식 ';;;' — 값이 있어도 화면에 안 나온다",
    "sheet_very_hidden": "veryHidden 시트 — 엑셀의 '숨기기 취소' 목록에도 없다",
    "sheet_hidden": "숨긴 시트",
    "row_hidden": "숨긴 행",
    "col_hidden": "숨긴 열",
    "outside_page": "페이지 경계 밖에 배치된 글자 — 화면에도 인쇄물에도 안 나온다",
    "covered_by_image": "글자를 그린 뒤 그 위에 이미지를 덮었다",
    "outside_used_range": "엑셀이 기록한 사용 범위 밖의 셀 — Ctrl+End로도 찾을 수 없다",
    "deleted_command": "변경내용 추적으로 지운 자리에 AI를 향한 명령이 남아 있다",
    "invisible_a": "보이지 않는 제어 문자 — 정상 문서에 쓰일 이유가 없다",
    "invisible_bidi": "글자 순서를 뒤집는 Bidi 제어 문자 — 되돌리자 숨은 문장이 드러났다",
    "invisible_b": "보이지 않는 문자를 걷어내자 숨어 있던 문장이 드러났다",
    "invisible_density": "한 문단의 4분의 1 이상이 보이지 않는 문자다 — 정상 문서에 없는 밀도",
}

# 근거별 의도성 점수 (0.0 ~ 1.0) — "이게 얼마나 일부러 숨긴 것으로 보이나".
#
# 0에 가까우면 서식 잔재나 정상적인 사용이고, 1에 가까우면 실수로 그렇게 될 수 없는
# 것이다. 숨긴 행·열을 낮게 잡은 이유: 보조 계산용으로 접어두는 일이 정상 문서에
# 흔하다. 반대로 `;;;` 서식과 veryHidden 시트는 실수로 만들어지지 않는다 —
# 만들려면 서식 대화상자를 열거나 VBA를 건드려야 한다.
_INTENT = {
    "render_mode": 0.95,
    "opacity": 0.95,
    "font_size": 0.9,
    "color": 0.95,
    "color_unknown_bg": 0.9,
    "vanish": 0.9,
    "web_hidden": 0.7,
    "blank_format": 0.9,
    "sheet_very_hidden": 0.9,
    "sheet_hidden": 0.5,
    "row_hidden": 0.5,
    "col_hidden": 0.5,
    # 아래 셋은 문서를 손으로 편집해서는 나오기 어렵다. 페이지 밖으로 글자를 밀거나,
    # 글자 위에 이미지를 덮거나, 파일에 적힌 사용 범위를 좁히려면 도구를 써야 한다.
    "outside_page": 0.9,
    "covered_by_image": 0.85,
    "outside_used_range": 0.85,
    "deleted_command": 0.9,
    "invisible_a": 0.9,
    # 임베딩·isolate 자체는 정상 표기다. 신고까지 왔다는 것은 복원 검사를 통과했다는
    # 뜻이라, 그 시점에는 의도성을 A급과 같게 본다.
    "invisible_bidi": 0.9,
    "invisible_b": 0.8,
    # 복원 검사를 통과하지 못했다 = 안에 무엇이 들었는지는 아직 모른다. 밀도만으로
    # "일부러 심었다"까지는 말할 수 있어도 내용은 모르므로 B급보다 낮게 둔다.
    "invisible_density": 0.7,
}

# 서식 값을 **제대로 읽었는지**에 대한 확신도. 의도성과는 다른 축이다.
#
# 흰 글씨를 찾았는데 배경색을 알아내지 못했다면(bg_known=False), "숨기려 했다"는
# 판단은 그대로 강하지만 "정말 흰 배경 위였나"는 확실하지 않다. 두 불확실성을 한
# 숫자에 섞으면 화면에 근거를 설명할 수 없다. 나눠서 곱한다.
_READ_CERTAINTY = {
    "color_unknown_bg": 0.8,
}


def _confidence(reason: str) -> float:
    """위험 점수에 곱해질 확신도 = 의도성 x 판독 확신도.

    schema.compute_risk_score()가 (가중치 x 타입별 평균 확신도 x (1 + ln(개수)))로
    계산하므로, 의도가 약한 근거는 여기서 자동으로 점수를 덜 흔든다.
    """
    return round(_INTENT.get(reason, 0.5) * _READ_CERTAINTY.get(reason, 1.0), 2)

# 조건을 하나 더 봐야 신고할 수 있는 사유.
#
# "deleted"(변경내용 추적으로 지워진 글자)가 그렇다. 검토 중인 계약서에는 삭제 표시가
# 수십~수백 개 들어 있는 게 정상이라, 그 자체를 신고하면 문서가 통째로 빨간불이 된다.
# 2026-09-11에 대조군 두 개로 실제로 재봤다.
#
#     전부 신고    -> clean/07 8건, clean/08 1건 오탐   (문서가 도배된다)
#     신고 안 함   -> hidden/22 놓침                    (지운 자리의 숨은 명령을 놓친다)
#     명령일 때만  -> 놓침 0, 오탐 0                     <- 채택
#
# "지웠다"는 사실이 아니라 **지운 자리에 무엇이 남아 있는가**로 가른다. B급 보이지
# 않는 문자를 복원 검사로 거르는 것과 같은 구조다.
_CONDITIONAL_HIDDEN_REASONS = {"deleted"}

# 복원한 문장이 AI 지시문이라고 판정됐을 때 evidence["restored_kind"]에 넣는 값.
#
# **상수로 빼 둔 이유**: scan.py의 `_promote_hidden_injections`가 이 문자열과
# 정확히 같은지 비교해서 hidden_text(25점)를 injection(50점)으로 올린다. 그런데
# 지금 scan.py는 같은 글자를 자기 파일에 한 번 더 적어 두고 있다. 문구를 다듬는
# 순간 승격이 조용히 멈추고, 숨겨진 지시문이 25점짜리로만 나간다 — 예외도 경고도
# 없이 점수만 절반이 된다. scan.py가 `hidden.INJECTION_KIND`를 import하도록
# 바꾸면 그 사고가 구조적으로 불가능해진다 (scan.py는 B-2 담당이라 합의 후 수정).
INJECTION_KIND = "AI에게 내리는 지시문"


# ---------------------------------------------------------------------------
# 색 비교
# ---------------------------------------------------------------------------


def _rgb(hex_color: str) -> tuple[int, int, int] | None:
    if not isinstance(hex_color, str) or len(hex_color) != 7:
        return None
    try:
        return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
    except ValueError:
        return None


def is_invisible_color(foreground: str, background: str,
                       threshold: int = COLOR_DISTANCE_THRESHOLD) -> bool:
    """두 색의 RGB 거리가 threshold 미만이면 안 보이는 것으로 본다."""
    a, b = _rgb(foreground), _rgb(background)
    if a is None or b is None:
        return False
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 < threshold


# ---------------------------------------------------------------------------
# 보이지 않는 문자 세기
# ---------------------------------------------------------------------------


def is_emoji_zwj(text: str, index: int) -> bool:
    """이모지를 잇는 ZWJ면 True — 세지 않는다.

    가족 이모지 하나가 ZWJ 3개다. 전체 7자 중 3자니까 밀도 43%다. 이모지 하나만으로
    개수와 밀도를 동시에 통과한다. 훈련 모드의 실시간 답장 스캔이 짧은 채팅을
    검사하므로, 이 예외가 없으면 이모지 쓴 메시지마다 경고가 뜬다.
    """
    return (
        text[index] == ZWJ
        and 0 < index < len(text) - 1
        and EMOJI.match(text[index - 1]) is not None
        and EMOJI.match(text[index + 1]) is not None
    )


def count_invisible(text: str, is_document_start: bool = False) -> tuple[int, int, int]:
    """(A급 개수, Bidi급 개수, B급 개수). 이모지 ZWJ와 맨 앞 BOM 1개는 세지 않는다."""
    a_count = len(INVISIBLE_A.findall(text))
    bidi_count = len(INVISIBLE_BIDI.findall(text))

    b_count = 0
    for index, char in enumerate(text):
        if not INVISIBLE_B.match(char):
            continue
        if is_emoji_zwj(text, index):
            continue
        # UTF-8 파일 맨 앞의 BOM은 아주 흔하다. 맨 앞 1개만 봐준다.
        if char == BOM and is_document_start and index == 0:
            continue
        b_count += 1
    return a_count, bidi_count, b_count


def strip_invisible(text: str) -> str:
    """보이지 않는 문자를 걷어낸다. 이모지 ZWJ는 남긴다(이모지가 깨진다)."""
    kept = []
    for index, char in enumerate(text):
        if INVISIBLE_A.match(char) or INVISIBLE_BIDI.match(char):
            continue
        if INVISIBLE_B.match(char) and not is_emoji_zwj(text, index):
            continue
        kept.append(char)
    return "".join(kept)


def decode_tag_chars(text: str) -> str:
    """태그 문자를 원래 ASCII로 되돌린다. 0xE0000을 빼면 그대로 나온다."""
    decoded = []
    for char in text:
        code = ord(char)
        if TAG_BLOCK_START <= code <= TAG_BLOCK_START + 0x7F:
            decoded.append(chr(code - TAG_BLOCK_START))
    return "".join(decoded).strip()


def restore(text: str) -> tuple[str, str]:
    """숨겨진 문장을 복원한다. (복원한 문장, 복원 방법)을 돌려준다.

    세 가지를 순서대로 시도한다.
      1) "tag"   — 태그 문자를 ASCII로 디코드 (ASCII smuggling)
      2) "bidi"  — Bidi 제어 문자를 걷어내고 뒤집힌 구간을 되돌린다 (Trojan Source)
      3) "strip" — 그냥 보이지 않는 문자를 제거 (제로폭으로 단어를 쪼개 놓은 경우)

    **방법을 같이 돌려주는 이유**가 중요하다. 1·2번은 숨겨진 문장을 통째로 꺼낸
    것이라 "읽을 수 있는 문장이 나왔다"는 사실 자체가 근거가 된다. 반면 3번은
    원문에서 문자 몇 개를 뺀 것뿐이라, 어떤 정상 문서를 넣어도 읽을 수 있는 문장이
    나온다. 같은 기준을 적용하면 자동 하이픈이 든 멀쩡한 워드 문서가 걸린다
    (실제로 1회차에서 그렇게 걸렸다).
    """
    tagged = decode_tag_chars(text)
    if tagged:
        return tagged, "tag"

    if any(control in text for control in _BIDI_CONTROLS):
        # 재정의 구간은 화면에 거꾸로 보인다. 걷어낸 뒤 뒤집어야 원문이 나온다.
        segments = re.split(f"[{_BIDI_CONTROLS}]", text)
        restored = max(segments[1:], key=len) if len(segments) > 1 else ""
        if restored.strip():
            return restored[::-1].strip(), "bidi"

    return strip_invisible(text).strip(), "strip"


def _looks_dangerous(text: str, method: str) -> tuple[bool, str]:
    """복원한 문장이 "의미 있는 문장"인가.

    막연히 "말이 되는가"는 판정할 수 없다. 우리가 실제로 물어야 하는 것은
    **복원했더니 위험한 것이 새로 드러났는가**이므로, 그것만 본다.
      - AI에게 내리는 지시인가 (models.is_injection)
      - 정규식 탐지가 새로 걸리는가 (주민번호·API 키 등)

    이 검사가 자동 하이픈이 든 정상 문서와 제로폭으로 쪼갠 명령문을 가른다.
    하이픈을 걷어내도 "contract agreement"일 뿐이라 아무것도 새로 안 나온다.
    """
    if not text or len(text) < 4:
        return False, ""
    is_command, _ = models.is_injection(text)
    if is_command:
        return True, INJECTION_KIND
    if rules.find_all(text):
        return True, "규칙 탐지 대상 값"
    # 디코드로 문장이 통째로 나온 경우에만 "읽을 수 있다"를 근거로 친다.
    #
    # "tag"만 인정하는 이유: 태그 문자는 디코드할 것이 없으면 빈 문자열이 나온다.
    # 뭔가 나왔다는 것 자체가 누군가 심었다는 뜻이라 오탐이 날 자리가 없다.
    #
    # "bidi"를 뺐다 (7회차, 2026-09-12). 되돌리기는 **어떤 글자든** 뒤집어 놓기
    # 때문에, 아랍어 상호를 인용한 정상 문서도 "hdayiR ,dR dhaF gniK" 같은 5단어짜리
    # 출력이 나와서 이 조건을 그냥 통과했다. 뒤집힌 글자가 말이 되는지는 판정할 수
    # 없으므로, Bidi는 위의 두 검사(지시문·규칙 탐지)만으로 가른다.
    # hidden/14·16의 숨은 문장은 둘 다 is_injection에 걸리므로 놓치지 않는다.
    #
    # "strip"에 이 기준을 쓰면 모든 정상 문서가 통과해 버린다(1회차에서 확인).
    if method == "tag" and text.isprintable() and len(text.split()) >= 2:
        return True, "복원하자 드러난 문장"
    return False, ""


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------


def _format_signals(span) -> list[tuple[str, dict]]:
    """서식으로 감춰졌는지 본다. (사유, 근거값) 목록을 돌려준다."""
    signals: list[tuple[str, dict]] = []

    if getattr(span, "render_mode", 0) == 3:
        signals.append(("render_mode", {"render_mode": 3}))
    if getattr(span, "opacity", 1.0) == 0.0:
        signals.append(("opacity", {"opacity": 0.0}))
    if 0 < getattr(span, "font_size", 11.0) < MIN_READABLE_FONT_SIZE:
        signals.append(("font_size", {"font_size": span.font_size}))

    if is_invisible_color(span.color, span.bg_color):
        # 배경색을 실제로 뽑아낸 경우와 몰라서 흰색으로 가정한 경우를 나눈다.
        # 파란 칸에 파란 글씨는 전자이고, 확신도가 다르다.
        key = "color" if getattr(span, "bg_known", False) else "color_unknown_bg"
        signals.append((key, {"color": span.color, "bg": span.bg_color,
                              "bg_known": getattr(span, "bg_known", False)}))

    if getattr(span, "hidden_attr", False):
        for reason in (getattr(span, "hidden_reason", "") or "other").split("+"):
            if not reason:
                continue
            if reason in _CONDITIONAL_HIDDEN_REASONS:
                # 지운 자리에 AI를 향한 명령이 남아 있을 때만 신고한다.
                # 정상적인 문구 수정("계약 기간은 6개월로 한다")은 여기서 걸러진다.
                if models.is_injection(span.text)[0]:
                    signals.append(("deleted_command", {"hidden_reason": reason}))
                continue
            signals.append((reason, {"hidden_reason": reason}))
    return signals


def _invisible_signals(span, is_document_start: bool) -> list[tuple[str, dict]]:
    """보이지 않는 문자로 감춰졌는지 본다."""
    a_count, bidi_count, b_count = count_invisible(span.text, is_document_start)
    if not (a_count or bidi_count or b_count):
        return []

    restored, method = restore(span.text)
    dangerous, restored_kind = _looks_dangerous(restored, method)
    evidence = {"invisible_a": a_count, "invisible_bidi": bidi_count,
                "invisible_b": b_count}
    if dangerous:
        evidence["restored"] = restored[:200]
        evidence["restored_kind"] = restored_kind
        evidence["restore_method"] = method

    length = len(span.text)
    density = b_count / max(length, 1)

    # A급은 개수 하나로 충분하다. 대조군에서 한 번도 나오지 않는 문자다.
    if a_count >= INVISIBLE_A_MIN_COUNT:
        return [("invisible_a", evidence)]

    # Bidi급은 1개부터 보되 복원 검사를 통과해야 신고한다. 아랍어를 인용한 정상
    # 문서와 임베딩으로 순서를 뒤집은 공격을 가르는 것이 이 한 줄이다.
    if bidi_count >= INVISIBLE_BIDI_MIN_COUNT and dangerous:
        return [("invisible_bidi", evidence)]

    # B급은 개수·밀도를 넘겨도 복원까지 통과해야 신고한다. 넘지 못하면 서식 잡음이다.
    over_count = b_count >= INVISIBLE_B_MIN_COUNT
    over_density = (
        length >= INVISIBLE_DENSITY_MIN_LENGTH
        and density > INVISIBLE_B_MAX_DENSITY
    )
    if (over_count or over_density) and dangerous:
        evidence["density"] = round(density, 4)
        return [("invisible_b", evidence)]

    # 복원 검사를 통과하지 못했더라도 밀도가 이 정도면 그것만으로 신고한다.
    # 복원 검사는 models.is_injection에 기대는데 그쪽이 아직 한국어 키워드 6개짜리
    # 임시 구현이라, 영어 지시문을 숨긴 문서가 통째로 빠져나간다. 그 구멍을 막는
    # 마지막 그물이다 — 정상 문서의 최대 밀도(13.8%)보다 한참 위에 선을 둔다.
    if length >= INVISIBLE_DENSITY_MIN_LENGTH and density > INVISIBLE_B_EXTREME_DENSITY:
        evidence["density"] = round(density, 4)
        return [("invisible_density", evidence)]
    return []


def detect(spans) -> list[dict]:
    """span 목록에서 숨겨진 텍스트를 찾는다. scan.py가 부르는 진입점이다."""
    findings: list[dict] = []
    for index, span in enumerate(spans):
        if not span.text.strip():
            continue

        signals = _format_signals(span) + _invisible_signals(span, is_document_start=index == 0)
        if not signals:
            continue

        # span 하나에 finding 하나. 확신도는 가장 강한 근거를 따르고 나머지는
        # evidence에 모아 담는다. 두 개를 내면 한 문장이 25점을 두 번 받는다.
        signals.sort(key=lambda item: _confidence(item[0]), reverse=True)
        top_reason = signals[0][0]
        evidence: dict = {"signals": [name for name, _ in signals]}
        for _, values in signals:
            evidence.update(values)
        if getattr(span, "where", "body") not in ("body", "cell"):
            evidence["where"] = span.where

        # hidden_reason(수법 분류)과 intent_score(의도성)는 DB에도 남는 값이다.
        # confidence를 왜 이 값으로 잡았는지의 근거이자, "어떤 수법이 제일 많았나"
        # 통계의 재료다. 화면은 이 둘을 XAI 설명으로 그대로 보여준다.
        evidence["hidden_reason"] = top_reason
        evidence["intent_score"] = _INTENT.get(top_reason, 0.5)

        findings.append({
            "field": "hidden_text",
            "value": span.text,
            "start": span.start,
            "end": span.end,
            "confidence": _confidence(top_reason),
            "reason": _REASONS.get(top_reason, "서식으로 감춰진 텍스트"),
            "evidence": evidence,
        })
    return findings


def detect_text(text: str) -> list[dict]:
    """서식 정보 없이 문자열만 검사한다.

    훈련 모드(C)의 실시간 답장 스캔에는 span이 없다. 그쪽에서도 제로폭·Bidi·태그
    문자는 잡아야 하므로, 문자열 하나를 span 한 개처럼 다뤄 문자 검사만 돌린다.
    """
    findings: list[dict] = []
    for match in re.finditer(r"[^\n]+", text):
        line = match.group()
        span = _PlainSpan(text=line, start=match.start(), end=match.end())
        for reason, evidence in _invisible_signals(span, is_document_start=match.start() == 0):
            evidence["hidden_reason"] = reason
            evidence["intent_score"] = _INTENT.get(reason, 0.5)
            findings.append({
                "field": "hidden_text",
                "value": line,
                "start": match.start(),
                "end": match.end(),
                "confidence": _confidence(reason),
                "reason": _REASONS.get(reason, "보이지 않는 문자"),
                "evidence": evidence,
            })
    return findings


class _PlainSpan:
    """detect_text 전용. 서식 값이 없는 자리표시자다.

    색·크기 값을 "탐지가 안 되는 쪽"의 기본값으로 채워 둔다. detect_text는
    _invisible_signals만 부르므로 지금은 쓰이지 않지만, 이 객체가 _format_signals로
    넘어가면 span.color를 getattr 없이 바로 읽는 자리에서 AttributeError가 난다.
    (parse.TextSpan의 기본값과 같은 값이다 — 모르면 놓치는 게 낫지, 모른다고
    신고하면 안 된다.)
    """

    def __init__(self, text: str, start: int, end: int) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.color = "#000000"
        self.bg_color = "#ffffff"
