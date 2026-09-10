"""offset 구간 -> PDF 페이지 좌표.

`rules.py`·`ner.py`가 만든 Finding에는 `start`/`end`(raw_text 기준 몇 번째 글자)만
있고 좌표가 없다. 그런데 PDF 마스킹은 **좌표로 지운다** — PyMuPDF 리댁션이
사각형을 받아서 그 안의 텍스트를 파일에서 실제로 제거한다(검은 박스로 덮기만 하면
복사·추출로 되살아난다). 그 사이를 잇는 것이 이 파일이다.

이 일이 `parser/`에 있는 이유 (팀 계획서에 정해진 분담)
------------------------------------------------------
    parser/ (B-1)   offset -> 좌표 매핑 함수를 제공한다. span 기하를 아는 쪽이다
    scan.py (B-2)   dedupe 직후 그 함수를 불러 Finding.bbox와 page를 채운다
    mask.py (B-1)   finding.bbox를 **읽기만** 한다. 좌표를 다시 찾지 않는다

좌표를 두 군데서 따로 구하면 같은 값이 여러 번 나올 때 엉뚱한 자리를 지운다.

왜 글자 수 비례로 짐작하면 안 되나
----------------------------------
줄 전체 사각형만 있으면 "10번째 글자"의 x를 (줄 너비 / 글자 수) x 10으로 짐작하게
된다. 한글은 약 10.3pt, ASCII는 약 6.7pt로 폭이 1.5배 차이라서 섞인 줄에서는
글자 한두 개분씩 밀린다. 실측으로 `담당자 연락처는 010-1234-5678 입니다`에서
11.4pt(글자 1.5개분) 어긋났다. 덜 덮이면 개인정보가 그대로 남고, 넓히면 옆 글자가
지워진다. `TextSpan.char_x`(글자별 가로 경계)를 쓰면 짐작할 필요가 없다.

줄바꿈 주의
-----------
값 하나가 두 줄에 걸치면 사각형이 둘 필요하다. 합집합 하나로 지우면 그 사이의
멀쩡한 글자까지 지워진다. 그래서 `rects_for()`는 **목록**을 돌려준다.
`Finding.bbox`는 사각형 하나짜리 공용 필드라 화면 하이라이트용 합집합을 넣고,
리댁션에 쓸 정밀 좌표는 `evidence["rects"]`에 담는다(evidence는 자유 형식이라
공용 계약을 건드리지 않는다).

    for rect in f.evidence.get("rects") or ([f.bbox] if f.bbox else []):
        page.add_redact_annot(rect, text=f.placeholder)
    page.apply_redactions()
"""

from __future__ import annotations

Rect = tuple[float, float, float, float]

# 같은 줄로 볼 세로 오차(pt). 이 안에 들어오면 붙어 있는 사각형끼리 합친다.
_SAME_LINE_TOLERANCE = 1.0
# 가로로 이만큼까지 떨어져 있으면 이어진 것으로 보고 합친다. 글자 사이 간격 정도다.
_MERGE_GAP = 1.5


def _rect_for_span(span, lo: int, hi: int) -> Rect | None:
    """span 안의 [lo, hi) 구간(raw_text 기준 offset)이 차지하는 사각형."""
    if span.bbox is None:
        return None                      # DOCX/XLSX는 좌표 자체가 없다

    top, bottom = float(span.bbox[1]), float(span.bbox[3])
    char_x = getattr(span, "char_x", None)

    if char_x and len(char_x) == len(span.text) + 1:
        first = lo - span.start
        last = hi - span.start
        x0, x1 = float(char_x[first]), float(char_x[last])
        if x1 > x0:
            return (x0, top, x1, bottom)

    # 글자별 좌표가 없다(세로쓰기·회전 텍스트 등). span 전체로 물러선다 —
    # 값보다 넓게 지우므로 개인정보가 남지는 않지만 옆 글자가 같이 지워질 수 있다.
    return (float(span.bbox[0]), top, float(span.bbox[2]), bottom)


def _merge(rects: list[Rect]) -> list[Rect]:
    """같은 줄에서 이어지는 사각형을 합친다.

    한 값이 texttrace span 두 개로 쪼개져 있는 일이 흔하다("010-1234-"와 "5678").
    그대로 두면 리댁션 사각형이 불필요하게 여러 개가 된다. 줄이 다르면 합치지 않는다.
    """
    if not rects:
        return []
    merged: list[Rect] = []
    for rect in sorted(rects, key=lambda r: (round(r[1], 1), r[0])):
        if merged:
            last = merged[-1]
            same_line = (abs(last[1] - rect[1]) <= _SAME_LINE_TOLERANCE
                         and abs(last[3] - rect[3]) <= _SAME_LINE_TOLERANCE)
            if same_line and rect[0] - last[2] <= _MERGE_GAP:
                merged[-1] = (last[0], min(last[1], rect[1]),
                              max(last[2], rect[2]), max(last[3], rect[3]))
                continue
        merged.append(rect)
    return merged


def rects_for(doc, start: int, end: int) -> list[Rect]:
    """offset 구간과 겹치는 span들의 좌표를 돌려준다.

    줄바꿈으로 갈라지면 여러 개다. 좌표가 없는 형식(DOCX/XLSX/TXT)이면 빈 목록이다.
    """
    if end <= start:
        return []
    rects: list[Rect] = []
    for span in doc.spans:
        if span.end <= start or end <= span.start:
            continue
        rect = _rect_for_span(span, max(start, span.start), min(end, span.end))
        if rect is not None:
            rects.append(rect)
    return _merge(rects)


def union(rects: list[Rect]) -> Rect | None:
    """사각형 여러 개를 감싸는 하나. 화면 하이라이트용이다 — 리댁션에 쓰지 말 것."""
    if not rects:
        return None
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


def page_of(doc, offset: int) -> int | None:
    """그 글자가 몇 페이지인지. page_map은 문자 1개당 페이지 번호 1개다."""
    if not doc.page_map:
        return None
    return doc.page_map[min(max(offset, 0), len(doc.page_map) - 1)]


def fill_coords(doc, findings) -> int:
    """Finding 목록에 bbox와 page를 채운다. 채운 개수를 돌려준다.

    `scan.py`가 dedupe 직후에 부른다. 여기서 채우지 않으면 `Finding.bbox`가 영원히
    null로 남고, 화면이 PDF 미리보기 위에 하이라이트 박스를 그릴 방법이 사라진다.
    """
    filled = 0
    for finding in findings:
        if finding.page is None:
            finding.page = page_of(doc, finding.start)

        rects = rects_for(doc, finding.start, finding.end)
        if not rects:
            continue
        finding.bbox = union(rects)                       # 화면용 — 합집합 하나
        finding.evidence = {**(finding.evidence or {}), "rects": rects}   # 리댁션용
        filled += 1
    return filled
