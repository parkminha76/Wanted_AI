"""마스킹 사본 — 탐지가 끝난 findings를 받아 **원본 형식 그대로** 가린 사본을 만든다.

원본 파일은 절대 건드리지 않는다. 항상 새 파일을 쓰고 그 경로를 돌려준다.

이 파일이 하지 않는 일
----------------------
탐지를 하지 않는다. 좌표도 구하지 않는다. 들어온 `Finding`의 `start`/`end`와
`bbox`/`evidence["rects"]`를 **읽기만** 한다 (팀 분담: 좌표는 `parser/locate.py`가
구하고 `scan.py`가 채운다). 좌표를 두 군데서 따로 구하면 같은 값이 여러 번 나올 때
엉뚱한 자리를 지운다.

함수는 둘이다
-------------
    build(raw_text, findings) -> str            화면에 보여줄 텍스트. scan_text가 부른다.
    build_file(path, doc, findings) -> str|None 사본 파일 경로. scan_file이 부른다.

형식별로 가리는 방법이 다르다
-----------------------------
    TXT/MD/CSV  raw_text 문자열 치환                     offset만 있으면 된다
    DOCX        python-docx run 단위 치환 (서식 유지)     offset -> span.start로 되짚는다
    XLSX        zip 안 셀 XML만 교체                      span.origin이 셀 주소를 들고 있다
    PDF         PyMuPDF 리댁션                            좌표가 필요하다

PDF만 문자열 치환이 불가능하다. PDF 안의 글자는 "몇 번째 문자"로 들어있는 게 아니라
페이지 위 좌표에 하나씩 박혀 있어서, 바꿔치기가 아니라 좌표로 지우는 수밖에 없다.

치환 문자열은 손으로 쓰지 않는다
--------------------------------
`Finding.placeholder`(= `schema.mask_placeholder()`)만 쓴다. **유형을 남긴다**:
`홍길동` -> `[이름]`. `****`로 뭉개면 사본을 AI에 넣었을 때 문맥이 무너진다.

PDF 리댁션의 한글 폰트 (해결됨 — `_PDF_FONT`)
---------------------------------------------
`add_redact_annot(rect, text="[전화번호]")`를 그냥 쓰면 대체 문자열이 `[????]`로
나온다. PyMuPDF 기본 폰트에 한글 자형이 없어서다. 저장소의 NanumGothic.otf를
물리려 했지만 `add_redact_annot`에는 fontfile 인자가 아예 없고, `insert_font`로
심어 둔 이름을 넘기면 "Font 'ng' is unsupported"로 막힌다. 내장 CJK 폰트
`"korea"`를 쓰면 제대로 찍힌다. 자세한 실측은 `_PDF_FONT` 주석에 있다.

지원하지 않는 형식은 사본을 만들지 않는다
-----------------------------------------
"일단 원본을 복사해두고 나중에 가린다"를 하지 않는다. 안 가려진 사본은 마스킹
사본이라는 이름을 달고 개인정보를 그대로 내보내는 것이라 아무것도 안 하느니 나쁘다.
가릴 수 없으면 `None`을 돌려준다 = 사본 없음.
"""

from __future__ import annotations

import os
import tempfile

# 지금 문자열 치환으로 처리할 수 있는 형식. 나머지는 아직 사본을 만들지 않는다.
_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".log"}

# 사본 파일 이름에 붙이는 꼬리표. 원본과 헷갈리지 않게 한다.
_SUFFIX = "_masked"

# xml:space="preserve". 이게 없으면 워드가 run의 앞뒤 공백을 버린다.
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


# ---------------------------------------------------------------------------
# 치환 계획 — 모든 형식이 공유한다
# ---------------------------------------------------------------------------


def _ordered(findings, text_len: int) -> list:
    """겹치지 않게 정리한 finding 목록. offset 순서다.

    겹침을 여기서 거르는 이유: `scan.py`가 dedupe를 하지만 `build()`는 훈련 모드(C)나
    테스트에서 직접 불리기도 한다. 겹친 채로 치환하면 앞 구간이 밀어낸 자리에 뒤
    구간을 덮어써서 글자가 잘린다.

    `_plan()`이 아니라 이쪽이 원본인 이유: PDF 리댁션은 치환 문자열만으로는 부족하고
    `evidence["rects"]`(좌표)까지 필요해서 finding 객체를 그대로 들고 가야 한다.
    정리 규칙이 둘로 갈라지면 형식마다 다른 구간을 가리게 된다.
    """
    items = []
    for finding in findings:
        start, end = getattr(finding, "start", None), getattr(finding, "end", None)
        if start is None or end is None:
            continue
        # 오프셋이 본문 밖이면 버린다. 다른 텍스트 기준으로 만들어진 finding이
        # 섞여 들어온 것이고, 그대로 치환하면 엉뚱한 글자를 가린다.
        if not (0 <= start < end <= text_len):
            continue
        items.append(finding)

    # 같은 자리에서 시작하면 긴 쪽을 남긴다 (짧은 쪽은 그 안에 들어있다).
    items.sort(key=lambda f: (f.start, -(f.end - f.start)))

    kept: list = []
    for finding in items:
        if kept and finding.start < kept[-1].end:
            continue                      # 앞 구간과 겹친다 -> 앞 것만 남긴다
        kept.append(finding)
    return kept


def _plan(findings, text_len: int) -> list[tuple[int, int, str]]:
    """가릴 구간을 (start, end, 치환문자열)로. 정렬돼 있고 겹치지 않는다."""
    return [(f.start, f.end, f.placeholder) for f in _ordered(findings, text_len)]


def build(raw_text: str, findings) -> str:
    """`ScanResult.masked_text` 용. 텍스트에서 탐지 구간을 placeholder로 바꾼다.

    하이라이트에는 쓸 수 없다 — 치환으로 길이가 달라져서 findings의 offset이
    이 문자열과는 맞지 않는다 (offset의 기준은 언제나 `raw_text`다).
    """
    if not raw_text or not findings:
        return raw_text or ""

    out: list[str] = []
    cursor = 0
    for start, end, placeholder in _plan(findings, len(raw_text)):
        out.append(raw_text[cursor:start])
        out.append(placeholder)
        cursor = end
    out.append(raw_text[cursor:])
    return "".join(out)


# ---------------------------------------------------------------------------
# 파일 사본
# ---------------------------------------------------------------------------


def _out_path(path: str, out_dir: str | None) -> str:
    """사본을 쓸 경로. 원본과 절대 같을 수 없게 만든다."""
    stem, ext = os.path.splitext(os.path.basename(path))
    # out_dir을 안 주면 매번 새 임시 폴더를 판다. 이름이 같은 파일을 여러 개
    # 올려도(부서별 `명단.xlsx` 같은 것) 서로 덮어쓰지 않는다.
    # schema.masked_path가 "응답 후 삭제되는 서버 임시 경로"라고 못박고 있다.
    target_dir = out_dir or tempfile.mkdtemp(prefix="infoguard_mask_")
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, f"{stem}{_SUFFIX}{ext}")


def _discard(out_path) -> None:
    """실패했을 때 쓰다 만 사본을 지운다.

    반쯤 가려진 파일이 임시 폴더에 남으면, 그게 언젠가 "마스킹 사본"으로 집어질 수
    있다. 실패는 파일이 없는 상태여야 한다.
    """
    try:
        if out_path and os.path.exists(out_path):
            os.remove(out_path)
    except OSError:
        pass


def _mask_text_file(path: str, doc, findings, out_dir: str | None) -> str:
    """TXT/MD/CSV — raw_text를 치환해서 그대로 다시 쓴다.

    `parse.py`의 텍스트 로더는 BOM도 줄바꿈도 지우지 않고 raw_text에 그대로
    담는다. 그래서 이 형식은 raw_text가 곧 파일 내용이고, 치환 결과를 쓰기만
    하면 원본 모양이 유지된다.
    """
    masked = build(doc.raw_text, findings)
    out_path = _out_path(path, out_dir)

    # newline=""가 없으면 파이썬이 "\n"을 OS 줄바꿈으로 바꿔버린다. 윈도우에서
    # 원본의 "\r\n"이 "\r\r\n"이 되어 줄이 하나씩 벌어진다. raw_text에 이미
    # 원본 줄바꿈이 들어있으므로 손대지 말고 그대로 내보낸다.
    #
    # 인코딩은 UTF-8로 통일한다. 원본이 cp949였어도 마찬가지다 — doc.raw_text는
    # 이미 디코드된 문자열이라 원래 인코딩을 알 수 없고, 사본의 주 용도가
    # "AI에 넣기"라서 UTF-8이 맞다. BOM은 raw_text에 그대로 남아 있어 보존된다.
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(masked)
    return out_path


def _mask_span_text(span, plan, emitted: set[int]) -> str:
    """span 하나의 텍스트를 가린 결과를 돌려준다.

    값 하나가 run 여러 개에 쪼개져 있는 경우(워드가 맞춤법 검사나 편집 이력 때문에
    "010-1234-"와 "5678"을 따로 저장하는 일이 흔하다) **placeholder는 처음 걸린
    run에만 넣고 나머지 run에서는 그 부분을 지운다.** 그러지 않으면 사본에
    "[전화번호][전화번호]"가 찍힌다. spans가 offset 순서라서 "처음 걸린 것"이
    곧 문서에서 앞선 조각이다.
    """
    pieces: list[str] = []
    cursor = span.start

    for index, (start, end, placeholder) in enumerate(plan):
        if end <= span.start:
            continue                      # 이 span보다 앞
        if start >= span.end:
            break                         # plan이 정렬돼 있으니 여기서 끝
        lo, hi = max(start, span.start), min(end, span.end)
        pieces.append(span.text[cursor - span.start:lo - span.start])
        if index not in emitted:
            pieces.append(placeholder)
            emitted.add(index)
        cursor = hi

    pieces.append(span.text[cursor - span.start:])
    return "".join(pieces)


def _mask_docx(path: str, doc, findings, out_dir: str | None) -> str | None:
    """DOCX — run 단위로 글자만 바꾼다. 글꼴·색·표·머리말은 그대로 남는다.

    `doc.spans`의 i번째와 문서 텍스트 노드의 i번째가 같은 조각이라는 약속 위에서
    돈다 (`parse.docx_text_nodes()` 참고). 짝이 하나라도 어긋나면 엉뚱한 run을
    가리게 되므로, 그때는 사본을 만들지 않고 `None`을 돌려준다.
    """
    import docx

    from backend.scanner.parser import parse

    try:
        document = docx.Document(path)
    except Exception:      # noqa: BLE001 — 업로드 파일은 무엇이든 들어온다
        return None

    nodes = parse.docx_text_nodes(document)
    spans = doc.spans

    # 짝이 맞는지 먼저 확인한다. 개수와 글자가 모두 같아야 같은 조각이다.
    if len(nodes) != len(spans):
        return None
    for node, span in zip(nodes, spans):
        if node.text != span.text:
            return None

    plan = _plan(findings, len(doc.raw_text))
    emitted: set[int] = set()

    for node, span in zip(nodes, spans):
        masked = _mask_span_text(span, plan, emitted)
        if masked == span.text:
            continue
        node.text = masked
        # 가리고 남은 글자가 공백으로 시작하거나 끝나면 워드가 그 공백을 버린다.
        # "홍길동 님" -> "[이름] 님"에서 placeholder 뒤 공백이 사라지는 식이다.
        if masked != masked.strip():
            node.set(_XML_SPACE, "preserve")

    # 숨겨진 텍스트(흰 글씨·1pt 등)를 가린 자리는 placeholder도 똑같이 안 보인다.
    # 값은 파일에서 사라졌으니 유출은 막았고, 서식까지 되돌리는 것은 "사본을 읽을 수
    # 있게 만드는" 다른 문제라 여기서 하지 않는다.

    out_path = _out_path(path, out_dir)
    document.save(out_path)

    if _leaks(out_path, doc.raw_text, plan):
        _discard(out_path)              # 새는 사본은 남기지 않는다
        return None
    return out_path


# XLSX는 파일을 다시 써내지 않는다 — 아래 _mask_xlsx의 주석 참고.
_SML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _q(namespace: str, tag: str) -> str:
    """lxml이 쓰는 정규화된 태그 이름."""
    return "{" + namespace + "}" + tag


def _resolve(base_dir: str, target: str) -> str:
    """관계(rels)의 Target을 zip 안 경로로 바꾼다."""
    import posixpath

    if target.startswith("/"):
        return target[1:]
    return posixpath.normpath(posixpath.join(base_dir, target))


def _rels_name(part: str) -> str:
    import posixpath

    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def _xlsx_sheet_parts(archive) -> dict:
    """시트 이름 -> 워크시트 파트 경로 ("xl/worksheets/sheet1.xml")."""
    from lxml import etree

    book = etree.fromstring(archive.read("xl/workbook.xml"))
    rels = etree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target_by_id = {node.get("Id"): node.get("Target") for node in rels}

    parts = {}
    for sheet in book.iter(_q(_SML, "sheet")):
        target = target_by_id.get(sheet.get(_q(_REL, "id")))
        if target:
            parts[sheet.get("name")] = _resolve("xl/", target)
    return parts


def _xlsx_comments_part(archive, sheet_part: str, names: set):
    """그 시트의 셀 주석이 들어 있는 파트."""
    import posixpath

    from lxml import etree

    rels_name = _rels_name(sheet_part)
    if rels_name not in names:
        return None
    for node in etree.fromstring(archive.read(rels_name)):
        if (node.get("Type") or "").endswith("/comments"):
            return _resolve(posixpath.dirname(sheet_part) + "/", node.get("Target"))
    return None


def _set_inline_string(cell, text: str) -> None:
    """셀을 "글자를 그대로 들고 있는 셀"로 바꾼다.

    수식(<f>)과 값(<v>)을 지우고 inlineStr로 바꾸는 이유: 수식을 남기면 사본을 열 때
    엑셀이 다시 계산해서 가린 값을 되살려 놓는다. 공유 문자열(t="s")로 두면 원래
    글자가 sharedStrings.xml에 남는다. 스타일(s=)은 건드리지 않아서 글꼴·색·테두리는
    그대로다.
    """
    from lxml import etree

    for child in list(cell):
        cell.remove(child)
    cell.set("t", "inlineStr")
    text_node = etree.SubElement(etree.SubElement(cell, _q(_SML, "is")), _q(_SML, "t"))
    text_node.text = text
    if text != text.strip():
        text_node.set(_XML_SPACE, "preserve")


def _serialize(root) -> bytes:
    from lxml import etree

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _xlsx_find_cell(root, coordinate: str):
    for cell in root.iter(_q(_SML, "c")):
        if cell.get("r") == coordinate:
            return cell
    return None


def _xlsx_find_comment(root, coordinate: str):
    for comment in root.iter(_q(_SML, "comment")):
        if comment.get("ref") == coordinate:
            return comment
    return None


def _set_comment_text(comment, text: str) -> None:
    """셀 주석의 글자를 통째로 바꾼다. 주석 안쪽 서식(굵게 등)은 잃는다."""
    from lxml import etree

    for child in list(comment):
        comment.remove(child)
    run = etree.SubElement(etree.SubElement(comment, _q(_SML, "text")), _q(_SML, "r"))
    etree.SubElement(run, _q(_SML, "t")).text = text


def _xlsx_clear_shared_strings(archive, names, sheet_parts, rewritten, replaced) -> None:
    """아무 셀도 더는 가리키지 않는 공유 문자열의 글자를 비운다.

    엑셀은 문자열 셀의 글자를 셀이 아니라 sharedStrings.xml에 모아 둔다. 셀만 바꾸고
    말면 원래 글자가 그 표에 그대로 남아서, 화면에는 안 보여도 파일을 열면 나온다.

    항목 자체는 지우지 않고 글자만 비운다 — 지우면 뒤 항목의 번호가 하나씩 밀려서
    다른 셀이 엉뚱한 글자를 가리키게 된다.
    """
    from lxml import etree

    part = "xl/sharedStrings.xml"
    if part not in names or not replaced:
        return

    referenced: set[int] = set()
    for sheet_part in sheet_parts.values():
        if sheet_part not in names:
            continue
        root = etree.fromstring(rewritten.get(sheet_part) or archive.read(sheet_part))
        for cell in root.iter(_q(_SML, "c")):
            if cell.get("t") != "s":
                continue
            value = cell.find(_q(_SML, "v"))
            if value is not None and (value.text or "").strip().isdigit():
                referenced.add(int(value.text.strip()))

    root = etree.fromstring(archive.read(part))
    changed = False
    for index, entry in enumerate(root.iter(_q(_SML, "si"))):
        if index in referenced:
            continue
        text = "".join(node.text or "" for node in entry.iter(_q(_SML, "t")))
        if text not in replaced:
            continue
        for child in list(entry):
            entry.remove(child)
        etree.SubElement(entry, _q(_SML, "t")).text = ""
        changed = True

    if changed:
        rewritten[part] = _serialize(root)


def _leaks(out_path: str, raw_text: str, plan) -> bool:
    """사본 안에 가려야 할 글자가 아직 남아 있는가.

    마지막 안전망이다. 여기 걸리면 내가 처리하지 못한 자리(스레드 주석, 차트가 들고
    있는 값 사본 등)에 원문이 남았다는 뜻이고, 그때는 사본을 만들지 않는다. 새는
    사본을 "마스킹 사본"이라는 이름으로 내보내는 것이 가장 나쁘다.

    완전한 증명은 아니다 — 값이 XML 조각 여러 개로 쪼개져 있으면 못 잡고, 바이너리
    파트는 보지 않는다. 문서 속성(docProps의 작성자·제목)은 본문 마스킹이 다루는
    범위가 아니라서 제외한다.
    """
    import zipfile
    from xml.sax.saxutils import escape

    values = {raw_text[start:end] for start, end, _ in plan}
    values = {value for value in values if value}
    if not values:
        return False
    values |= {escape(value) for value in values}

    try:
        with zipfile.ZipFile(out_path) as archive:
            for name in archive.namelist():
                if name.startswith("docProps/"):
                    continue
                if not (name.endswith(".xml") or name.endswith(".rels")):
                    continue
                text = archive.read(name).decode("utf-8", "replace")
                if any(value in text for value in values):
                    return True
    except Exception:      # noqa: BLE001
        return True        # 확인하지 못한 사본은 내보내지 않는다
    return False


def _mask_xlsx(path: str, doc, findings, out_dir):
    """XLSX — zip 안에서 **글자가 든 파트만** 고치고 나머지는 바이트 그대로 복사한다.

    왜 openpyxl로 저장하지 않나
    ---------------------------
    openpyxl은 워크북을 자기가 이해한 만큼 다시 써낸다. 그래서 매크로
    (vbaProject.bin), 피벗 캐시, 폼 컨트롤, customXml처럼 openpyxl이 모델링하지 않는
    부분이 사본에서 통째로 빠진다 — 관계(rels)에 제대로 걸려 있어도 빠진다(실측
    확인). 사본의 목적이 "값만 가린 원본"이라 그건 사본이라고 할 수 없다.

    그래서 xlsx를 zip으로 직접 열어, 고쳐야 할 XML 파트만 바꿔 쓰고 나머지 파트는
    읽은 바이트를 그대로 넘긴다. 손대지 않은 것은 정의상 그대로 남는다.
    (DOCX는 python-docx가 관계에 걸린 파트를 모두 보존해서 이 작업이 필요 없다.)

    XML은 lxml로 다룬다. 표준 라이브러리 ElementTree는 네임스페이스 접두사를 새로
    붙여버려서 mc:Ignorable="x14ac xr" 같은 속성이 없는 접두사를 가리키게 되고,
    엑셀이 "복구해야 할 파일"로 취급한다.
    """
    import zipfile

    from lxml import etree

    plan = _plan(findings, len(doc.raw_text))
    emitted: set[int] = set()

    # (시트 이름, 셀 주소, 종류) -> 가린 글자
    edits: dict = {}
    replaced: set[str] = set()          # 원래 글자. 공유 문자열 청소에 쓴다.
    for span in doc.spans:
        masked = _mask_span_text(span, plan, emitted)
        if masked == span.text:
            continue
        origin = getattr(span, "origin", "")
        if not origin:
            return None                 # 주소를 모르면 어느 셀인지 알 수 없다
        target, _, kind = origin.partition("#")
        sheet_title, _, coordinate = target.rpartition("!")
        edits[(sheet_title, coordinate, kind or "cell")] = masked
        replaced.add(span.text)

    out_path = _out_path(path, out_dir)

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            sheet_parts = _xlsx_sheet_parts(archive)
            rewritten: dict = {}

            for (sheet_title, coordinate, kind), masked in edits.items():
                sheet_part = sheet_parts.get(sheet_title)
                if sheet_part is None:
                    return None

                if kind == "comment":
                    part = _xlsx_comments_part(archive, sheet_part, names)
                    if part is None:
                        return None
                    root = etree.fromstring(rewritten.get(part) or archive.read(part))
                    node = _xlsx_find_comment(root, coordinate)
                    if node is None:
                        return None
                    _set_comment_text(node, masked)
                    rewritten[part] = _serialize(root)
                    continue

                root = etree.fromstring(rewritten.get(sheet_part) or archive.read(sheet_part))
                cell = _xlsx_find_cell(root, coordinate)
                if cell is None:
                    return None
                _set_inline_string(cell, masked)
                rewritten[sheet_part] = _serialize(root)

            _xlsx_clear_shared_strings(archive, names, sheet_parts, rewritten, replaced)

            with zipfile.ZipFile(out_path, "w") as out_archive:
                for item in archive.infolist():
                    data = rewritten.get(item.filename)
                    if data is None:
                        data = archive.read(item.filename)
                    out_archive.writestr(item, data)
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError, OSError):
        _discard(out_path)              # 쓰다 만 zip을 남기지 않는다
        return None

    if _leaks(out_path, doc.raw_text, plan):
        _discard(out_path)              # 새는 사본은 남기지 않는다
        return None
    return out_path


# 리댁션 대체 문자열에 쓰는 폰트.
#
# PyMuPDF 기본 폰트에는 한글 자형이 없어서 `[전화번호]`가 `[????]`로 찍힌다.
# placeholder가 전부 한글이라(schema.mask_placeholder) 그냥 두면 사본이 물음표
# 투성이가 된다. 저장소의 NanumGothic.otf를 물리려 했지만 `add_redact_annot`에는
# fontfile 인자가 없고, `insert_font`로 심어 둔 이름을 넘기면
# "Font 'ng' is unsupported"로 막힌다(PyMuPDF 1.28.2에서 확인).
#
# 내장 CJK 폰트 "korea"가 한글을 제대로 찍는다. 실측:
#     기본/helv -> [????]      korea -> [전화번호]
_PDF_FONT = "korea"
_PDF_FONT_SIZE = 11.0
_PDF_MIN_FONT_SIZE = 4.0


def _pdf_rects(finding) -> list:
    """이 finding을 지울 사각형들. **좌표를 새로 구하지 않는다.**

    한 값이 두 줄에 걸치면 사각형이 여러 개다. `bbox`(합집합 하나)로 지우면 그 사이의
    멀쩡한 글자까지 지워지므로 `evidence["rects"]`가 있으면 그쪽을 쓴다.
    """
    rects = (getattr(finding, "evidence", None) or {}).get("rects")
    if rects:
        return [tuple(rect) for rect in rects]
    if getattr(finding, "bbox", None):
        return [tuple(finding.bbox)]
    return []


def _pdf_font_size(text: str, width: float) -> float:
    """사각형 너비에 들어가는 글자 크기.

    한글 placeholder는 원래 값보다 넓어지기 쉽다("880101-1234567" -> "[주민등록번호]").
    넘치면 PyMuPDF가 대체 문자열을 아예 안 그려서, 값은 지워졌는데 무엇을 지웠는지
    알 수 없는 사본이 된다.
    """
    import pymupdf

    if width <= 0:
        return _PDF_FONT_SIZE
    try:
        needed = pymupdf.get_text_length(text, fontname=_PDF_FONT, fontsize=_PDF_FONT_SIZE)
    except Exception:      # noqa: BLE001
        return _PDF_FONT_SIZE
    if needed <= width or needed <= 0:
        return _PDF_FONT_SIZE
    return max(_PDF_MIN_FONT_SIZE, _PDF_FONT_SIZE * width / needed)


def _mask_pdf(path: str, doc, findings, out_dir: str | None) -> str | None:
    """PDF - 좌표로 지운다. 덮는 게 아니라 파일에서 글자를 **실제로 없앤다**.

    검은 사각형을 그려 덮기만 하면 복사·추출로 되살아난다. `apply_redactions()`는
    사각형 안의 텍스트를 콘텐츠 스트림에서 제거한다.

    좌표는 여기서 구하지 않는다
    ---------------------------
    `finding.evidence["rects"]`를 **읽기만** 한다. 그 값은 `parser/locate.py`가 구해서
    `scan.py`가 dedupe 직후에 채운다(팀 분담). 마스킹이 좌표를 따로 구하면 같은 값이
    여러 번 나올 때 화면 하이라이트와 다른 자리를 지운다.

    ⚠️ 그래서 `scan.py`가 `locate.fill_coords()`를 부르지 않으면 좌표가 비어 있고,
    이 함수는 사본을 만들지 않는다(`None`). 가릴 곳을 모르는 채로 사본을 내보내면
    "마스킹 사본"이라는 이름의 원본이 된다.
    """
    import pymupdf

    ordered = _ordered(findings, len(doc.raw_text))
    out_path = None

    try:
        document = pymupdf.open(path)
    except Exception:      # noqa: BLE001 - 업로드 파일은 무엇이든 들어온다
        return None

    try:
        for finding in ordered:
            rects = _pdf_rects(finding)
            if not rects:
                return None            # 가릴 곳을 모른다 -> 사본을 만들지 않는다

            index = (finding.page or 1) - 1
            if not (0 <= index < document.page_count):
                return None
            page = document[index]

            for order, rect in enumerate(rects):
                box = pymupdf.Rect(*rect)
                if order == 0:
                    # 대체 문자열은 첫 사각형에만 넣는다. 두 줄에 걸친 값에 줄마다
                    # 넣으면 사본에 "[전화번호][전화번호]"가 찍힌다.
                    page.add_redact_annot(
                        box,
                        text=finding.placeholder,
                        fontname=_PDF_FONT,
                        fontsize=_pdf_font_size(finding.placeholder, box.width),
                        cross_out=False,      # 기본값은 사각형에 X를 그린다
                    )
                else:
                    page.add_redact_annot(box, cross_out=False)

        for page in document:
            # 이미지와 선 그림은 건드리지 않는다. 기본값(IMAGE_PIXELS)은 사각형에
            # 닿은 그림의 픽셀을 지워서, 글자 뒤에 있던 로고에 구멍이 뚫린다.
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_NONE,
                graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )

        out_path = _out_path(path, out_dir)
        # 증분 저장(incremental)을 쓰지 않는다. 증분 저장은 원본 바이트를 남겨 두고
        # 뒤에 변경분만 붙이는 방식이라, 지운 글자가 이전 판본으로 파일에 그대로 남는다.
        document.save(out_path, garbage=3, deflate=True)
    except Exception:      # noqa: BLE001
        _discard(out_path)              # 쓰다 만 PDF를 남기지 않는다
        return None
    finally:
        document.close()

    if _leaks_pdf(out_path, doc.raw_text, _plan(ordered, len(doc.raw_text))):
        _discard(out_path)
        return None
    return out_path


def _leaks_pdf(out_path: str, raw_text: str, plan) -> bool:
    """사본에서 글자를 뽑았을 때 가려야 할 값이 나오는가.

    "덮기만 하면 복사·추출로 되살아난다"는 바로 이 검사로 확인한다. 값이 줄바꿈으로
    갈라져 뽑히는 경우까지 보려고 공백을 없앤 문자열로도 한 번 더 본다.
    """
    import pymupdf

    values = {raw_text[start:end] for start, end, _ in plan}
    values = {value for value in values if value}
    if not values:
        return False
    squeezed = {"".join(value.split()) for value in values}

    try:
        document = pymupdf.open(out_path)
    except Exception:      # noqa: BLE001
        return True        # 확인하지 못한 사본은 내보내지 않는다

    try:
        for page in document:
            text = page.get_text()
            if any(value in text for value in values):
                return True
            tight = "".join(text.split())
            if any(value in tight for value in squeezed):
                return True
    except Exception:      # noqa: BLE001
        return True
    finally:
        document.close()
    return False


def build_file(path: str, doc, findings, out_dir: str | None = None) -> str | None:
    """마스킹 사본 파일을 만들고 그 경로를 돌려준다. `ScanResult.masked_path`에 들어간다.

    `doc`은 `parse.load()`가 준 ParsedDoc이다. findings의 offset이 `doc.raw_text`
    기준이라 doc 없이는 어디를 가려야 하는지 알 수 없다.

    아직 못 가리는 형식이면 `None`을 돌려준다 (사본 없음). 안 가려진 사본을
    만들지 않는다.
    """
    if doc is None:
        return None

    # 이미지 파이프라인으로 간 파일(사진, 텍스트 층이 없는 스캔본 PDF)은 값이 글자가
    # 아니라 그림 안에 있다. 텍스트 치환도 좌표 리댁션도 닿지 않으므로 사본을 만들지
    # 않는다 - 만들면 "마스킹 사본"이라는 이름의 원본이 된다.
    if getattr(doc, "kind", "text") != "text":
        return None

    ext = os.path.splitext(path)[1].lower()

    try:
        if ext in _TEXT_EXTENSIONS:
            return _mask_text_file(path, doc, findings, out_dir)
        if ext == ".docx":
            return _mask_docx(path, doc, findings, out_dir)
        if ext in (".xlsx", ".xlsm"):
            return _mask_xlsx(path, doc, findings, out_dir)
        if ext == ".pdf":
            return _mask_pdf(path, doc, findings, out_dir)
    except Exception:      # noqa: BLE001
        # 업로드된 파일은 무엇이든 들어오는 시스템 경계다. 여기서 예외를 위로 던지면
        # scan_files가 통째로 죽어서, 같이 올린 멀쩡한 파일들의 결과까지 날아간다
        # (scan.py가 scan_file에서 같은 이유로 예외를 잡는다). 사본을 못 만든 것은
        # masked_path=None으로 충분히 표현된다.
        return None

    return None
