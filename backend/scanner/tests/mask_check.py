"""마스킹 사본 점검 (TXT/MD/CSV) - 값이 진짜 지워졌는지, 원본 모양이 남았는지 본다.

    uv run python backend/scanner/tests/mask_check.py

`scan.py`가 아직 다 완성되지 않아도 이 스크립트만으로 mask.py를 끝까지 검증할 수
있다. 필요한 건 findings 리스트 하나뿐이고, 그건 여기서 직접 만든다.

보는 것
-------
    1. 사본에 탐지된 값이 **문자열로 남아있지 않은가**  (가장 중요)
    2. 사본에 placeholder가 들어갔는가                  (`****`가 아니라 `[이름]`)
    3. 원본 파일이 그대로인가                            (바이트 단위 비교)
    4. 줄바꿈·BOM이 보존됐는가                           (윈도우 `\r\r\n` 사고 방지)
    5. 겹친 구간·범위 밖 offset을 흘리지 않는가

원문은 찍지 않는다. 유형과 길이만 나온다 (팀 규칙 2).
"""

from __future__ import annotations

import hashlib
import os
import zipfile
import shutil
import sys
import tempfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.scanner.masking import mask               # noqa: E402
from backend.scanner.parser import locate, parse       # noqa: E402
from backend.shared.schema import Finding              # noqa: E402

_failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  - ' + detail if detail else ''}")
    if not ok:
        _failures.append(label)


def _finding(risk_type: str, text: str, start: int, end: int) -> Finding:
    return Finding(
        id=f"f_{start:03d}", type=risk_type, text=text, start=start, end=end,
        confidence=1.0, source="rules", reason="테스트용",
    )


def _digest(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# 1. 파일 사본 - 실제 파일을 만들어 끝까지 돌린다
# ---------------------------------------------------------------------------


def case_text_file(tmp: str) -> None:
    """UTF-8 BOM + CRLF 줄바꿈. 윈도우에서 흔한 조합이라 기본값으로 잡는다."""
    print("\n[1] TXT 사본 - BOM + CRLF")

    value = "010-1234-5678"
    body = f"﻿담당자 연락처는 {value} 입니다.\r\n두 번째 줄.\r\n"
    src = os.path.join(tmp, "연락처.txt")
    with open(src, "wb") as fh:
        fh.write(body.encode("utf-8"))

    before = _digest(src)
    doc = parse.load(src)
    start = doc.raw_text.index(value)
    findings = [_finding("phone", value, start, start + len(value))]

    out = mask.build_file(src, doc, findings, out_dir=os.path.join(tmp, "out"))
    check(bool(out) and os.path.isfile(out), "사본 파일이 생성됐다", os.path.basename(out or ""))

    with open(out, "rb") as fh:
        raw = fh.read()
    masked = raw.decode("utf-8")

    check(value not in masked, "탐지된 값이 사본에 남아있지 않다", f"phone(len={len(value)})")
    check("[전화번호]" in masked, "placeholder가 유형을 남긴다", "[전화번호]")
    check(_digest(src) == before, "원본 파일이 변하지 않았다")
    check(masked.startswith("﻿"), "BOM이 보존됐다")
    check(b"\r\r\n" not in raw, "줄바꿈이 부풀지 않았다 (\r\r\n 없음)")
    check(raw.count(b"\r\n") == 2, "CRLF 개수가 원본과 같다", f"{raw.count(b'\r\n')}개")
    check(os.path.abspath(out) != os.path.abspath(src), "사본 경로가 원본과 다르다")


def case_cp949(tmp: str) -> None:
    """cp949로 저장된 파일. 사본은 UTF-8로 나간다 (mask.py의 결정)."""
    print("\n[2] TXT 사본 - cp949 원본")

    value = "880101-1234567"
    src = os.path.join(tmp, "주민.txt")
    with open(src, "wb") as fh:
        fh.write(f"사번 A-12\n주민번호 {value}\n".encode("cp949"))

    doc = parse.load(src)
    start = doc.raw_text.index(value)
    out = mask.build_file(src, doc, [_finding("rrn", value, start, start + len(value))],
                          out_dir=os.path.join(tmp, "out"))
    masked = open(out, encoding="utf-8").read()

    check(value not in masked, "탐지된 값이 사본에 남아있지 않다", f"rrn(len={len(value)})")
    check("[주민등록번호]" in masked, "placeholder가 유형을 남긴다", "[주민등록번호]")
    check("사번 A-12" in masked, "가리지 않은 글자는 그대로다")


def case_unsupported(tmp: str) -> None:
    """아직 못 가리는 형식은 사본을 만들지 않는다 (안 가려진 사본 금지)."""
    print("\n[3] 미지원 형식")

    src = os.path.join(tmp, "무엇.pdf")
    shutil.copyfile(os.path.join(tmp, "주민.txt"), src)   # 내용은 상관없다
    doc = parse.load(os.path.join(tmp, "주민.txt"))

    out = mask.build_file(src, doc, [], out_dir=os.path.join(tmp, "out"))
    check(out is None, "PDF는 아직 None을 돌려준다 (사본 없음)")
    check(mask.build_file(src, None, []) is None, "doc이 없으면 None을 돌려준다")


# ---------------------------------------------------------------------------
# 2. 치환 규칙 - 파일 없이 문자열만으로 본다
# ---------------------------------------------------------------------------


def case_rules() -> None:
    print("\n[4] 치환 규칙")

    text = "이름 홍길동 전화 010-1234-5678 끝"

    # 여러 건
    out = mask.build(text, [
        _finding("person", "홍길동", 3, 6),
        _finding("phone", "010-1234-5678", 10, 23),
    ])
    check(out == "이름 [이름] 전화 [전화번호] 끝", "여러 건을 앞뒤 순서대로 바꾼다", out)

    # 겹침 - 긴 쪽만 남는다
    out = mask.build(text, [
        _finding("phone", "010-1234-5678", 10, 23),
        _finding("account", "1234-5678", 14, 23),
    ])
    check(out.count("[") == 1, "겹친 구간은 긴 쪽 하나만 바꾼다", out)

    # 범위 밖 offset - 버린다
    out = mask.build(text, [_finding("person", "없음", 900, 903)])
    check(out == text, "본문 밖 offset은 버린다")

    # 뒤집힌 구간 / 빈 구간
    out = mask.build(text, [_finding("person", "", 6, 6), _finding("person", "x", 9, 4)])
    check(out == text, "빈 구간과 뒤집힌 구간은 버린다")

    # 모르는 유형은 [민감정보]로 물러선다 (schema.TYPE_LABELS의 기본값)
    out = mask.build(text, [_finding("made_up_type", "홍길동", 3, 6)])
    check("[민감정보]" in out, "모르는 유형도 가리기는 한다", out)

    # findings 없음
    check(mask.build(text, []) == text, "findings가 없으면 원문 그대로")
    check(mask.build("", []) == "", "빈 문자열도 터지지 않는다")

    # 오프셋 기준 - 치환 후 길이가 달라지므로 masked_text로 하이라이트하면 안 된다
    masked = mask.build(text, [_finding("person", "홍길동", 3, 6)])
    check(len(masked) != len(text), "치환으로 길이가 달라진다 (하이라이트에 쓰면 안 되는 이유)",
          f"{len(text)} -> {len(masked)}")


# ---------------------------------------------------------------------------
# DOCX - run 단위 치환
# ---------------------------------------------------------------------------


def _make_docx(path: str) -> None:
    """검사용 문서. 서식·표·머리말·쪼개진 run을 한 파일에 모았다."""
    import docx

    document = docx.Document()
    para = document.add_paragraph("담당자 ")
    bold_run = para.add_run("홍길동")
    bold_run.bold = True
    para.add_run(" 님 연락처 ")
    para.add_run("010-1234-")   # 값 하나가 run 둘로 쪼개진 경우 (워드가 흔히 이렇게 저장한다)
    para.add_run("5678")
    para.add_run(" 입니다.")

    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "이메일"
    table.cell(0, 1).text = "hong@example.com"

    document.sections[0].header.paragraphs[0].text = "사번 A-12"
    document.save(path)


def case_docx(tmp: str) -> None:
    print("\n[5] DOCX 사본 - run 쪼개짐 / 표 / 서식")

    src = os.path.join(tmp, "보고서.docx")
    _make_docx(src)
    before = _digest(src)

    doc = parse.load(src)
    values = [("person", "홍길동"), ("phone", "010-1234-5678"), ("email", "hong@example.com")]
    findings = []
    for risk_type, value in values:
        start = doc.raw_text.index(value)
        findings.append(_finding(risk_type, value, start, start + len(value)))

    out = mask.build_file(src, doc, findings, out_dir=os.path.join(tmp, "out"))
    check(bool(out) and os.path.isfile(out), "사본 파일이 생성됐다", os.path.basename(out or ""))
    if not out:
        return

    # 파일 안 XML 전체를 뒤진다. 화면에 안 보이는 자리(표·머리말·주석)에 남아도 유출이다.
    with zipfile.ZipFile(out) as zf:
        blob = b"".join(zf.read(name) for name in zf.namelist() if name.endswith(".xml"))
    xml = blob.decode("utf-8", "replace")

    check("홍길동" not in xml, "이름이 파일 어디에도 없다", "person(len=3)")
    check("010-1234-" not in xml and "5678" not in xml,
          "쪼개진 run 양쪽 모두 지워졌다", "phone(len=13)")
    check("hong@example.com" not in xml, "표 안의 값도 지워졌다", "email(len=16)")
    check(xml.count("[전화번호]") == 1, "쪼개진 값에 placeholder가 한 번만 들어간다",
          f"{xml.count('[전화번호]')}회")

    text = parse.load(out).raw_text
    check("[이름] 님 연락처 [전화번호] 입니다." in text, "앞뒤 공백이 보존됐다",
          text.split(chr(10))[0] if text else "")
    check("[이메일]" in text, "표 셀이 placeholder로 바뀌었다")
    check("사번 A-12" in text, "가리지 않은 글자는 그대로다 (머리말)")

    import docx
    reopened = docx.Document(out)
    bold = [r.text for para in reopened.paragraphs for r in para.runs if r.bold]
    check(bold == ["[이름]"], "굵게 서식이 유지됐다", str(bold))
    check(_digest(src) == before, "원본 파일이 변하지 않았다")


def case_docx_guard(tmp: str) -> None:
    """짝이 어긋나면 가리지 않고 물러선다 - 엉뚱한 run을 지우느니 사본을 안 만든다."""
    print("\n[6] DOCX 안전장치")

    src = os.path.join(tmp, "보고서.docx")
    out_dir = os.path.join(tmp, "out")

    broken = parse.load(src)
    broken.spans = broken.spans[:-1]                    # 개수를 일부러 깨뜨린다
    check(mask.build_file(src, broken, [], out_dir=out_dir) is None, "span 개수가 다르면 None")

    broken = parse.load(src)
    broken.spans[0].text = broken.spans[0].text + "달라짐"   # 글자를 일부러 깨뜨린다
    check(mask.build_file(src, broken, [], out_dir=out_dir) is None, "span 글자가 다르면 None")

    out = mask.build_file(src, parse.load(src), [], out_dir=out_dir)
    check(bool(out), "findings가 0건이어도 사본은 만든다")


# ---------------------------------------------------------------------------
# XLSX - 셀 단위 치환
# ---------------------------------------------------------------------------


def _make_xlsx(path: str) -> None:
    """검사용 통합 문서. 숫자 셀·수식·셀 주석·숨긴 시트를 한 파일에 모았다."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "명단"
    sheet["A1"] = "이름"
    sheet["A1"].font = Font(bold=True)
    sheet["B1"] = "연락처"
    sheet["A2"] = "홍길동"
    sheet["B2"] = 1012345678          # 숫자로 입력된 전화번호 (문자열이 아니다)
    sheet["C1"] = "=A1"               # 수식. 가릴 대상이 아니므로 살아 있어야 한다
    sheet["A3"] = "비고"
    sheet["A3"].comment = Comment("담당 minha@corp.co.kr", "작성자")

    hidden = workbook.create_sheet("백업")
    hidden["A1"] = "계좌 110-234-567890"
    hidden.sheet_state = "hidden"     # 숨긴 시트도 파일에는 그대로 들어 있다

    workbook.save(path)


def case_xlsx(tmp: str) -> None:
    print("\n[7] XLSX 사본 - 숫자 셀 / 주석 / 숨긴 시트")

    src = os.path.join(tmp, "명단.xlsx")
    _make_xlsx(src)
    before = _digest(src)

    doc = parse.load(src)
    values = [("person", "홍길동"), ("phone", "1012345678"),
              ("email", "minha@corp.co.kr"), ("account", "110-234-567890")]
    findings = []
    for risk_type, value in values:
        start = doc.raw_text.index(value)
        findings.append(_finding(risk_type, value, start, start + len(value)))

    out = mask.build_file(src, doc, findings, out_dir=os.path.join(tmp, "out"))
    check(bool(out) and os.path.isfile(out), "사본 파일이 생성됐다", os.path.basename(out or ""))
    if not out:
        return

    with zipfile.ZipFile(out) as zf:
        blob = b"".join(zf.read(name) for name in zf.namelist() if name.endswith(".xml"))
    xml = blob.decode("utf-8", "replace")

    check("홍길동" not in xml, "이름이 파일 어디에도 없다", "person(len=3)")
    check("1012345678" not in xml, "숫자로 입력된 값도 지워졌다", "phone(len=10)")
    check("minha@corp.co.kr" not in xml, "셀 주석 안의 값도 지워졌다", "email(len=16)")
    check("110-234-567890" not in xml, "숨긴 시트의 값도 지워졌다", "account(len=14)")

    from openpyxl import load_workbook
    book = load_workbook(out, data_only=False)
    sheet = book["명단"]
    check(sheet["A2"].value == "[이름]", "셀 값이 placeholder로 바뀌었다", str(sheet["A2"].value))
    check(sheet["B2"].value == "[전화번호]", "숫자 셀도 placeholder로 바뀌었다",
          str(sheet["B2"].value))
    check(sheet["A1"].value == "이름", "가리지 않은 셀은 그대로다")
    check(sheet["C1"].value == "=A1", "가리지 않은 수식은 살아 있다", str(sheet["C1"].value))
    check(sheet["A1"].font.bold is True, "글꼴 서식이 유지됐다")
    check(sheet["A3"].comment is not None and "[이메일]" in sheet["A3"].comment.text,
          "주석이 placeholder로 바뀌었다")
    check(book["백업"].sheet_state == "hidden", "숨긴 시트가 숨긴 채로 남았다")
    check(book["백업"]["A1"].value == "계좌 [계좌번호]", "숨긴 시트 셀이 바뀌었다",
          str(book["백업"]["A1"].value))
    book.close()

    check(_digest(src) == before, "원본 파일이 변하지 않았다")


def case_xlsx_guard(tmp: str) -> None:
    """짝이 어긋나면 사본을 만들지 않는다."""
    print("\n[8] XLSX 안전장치")

    src = os.path.join(tmp, "명단.xlsx")
    out_dir = os.path.join(tmp, "out")

    doc = parse.load(src)
    start = doc.raw_text.index("홍길동")
    findings = [_finding("person", "홍길동", start, start + 3)]

    broken = parse.load(src)
    for span in broken.spans:
        span.origin = ""                      # 주소를 잃어버린 경우
    check(mask.build_file(src, broken, findings, out_dir=out_dir) is None,
          "셀 주소가 없으면 None")

    broken = parse.load(src)
    for span in broken.spans:
        if span.text == "홍길동":
            span.origin = "없는시트!A2"
    check(mask.build_file(src, broken, findings, out_dir=out_dir) is None,
          "없는 시트를 가리키면 None")

    check(bool(mask.build_file(src, doc, [], out_dir=out_dir)), "findings가 0건이어도 사본은 만든다")


# ---------------------------------------------------------------------------
# 원본 보존 - 사본이 "값만 가린 원본"인가
# ---------------------------------------------------------------------------


def _make_rich_xlsm(path: str, png: str) -> None:
    """차트·그림에 더해, 라이브러리가 모델링하지 않는 파트까지 넣은 파일.

    매크로·피벗 캐시·폼 컨트롤·customXml은 엑셀이 만든 실제 파일에 흔하지만
    openpyxl은 이들을 이해하지 못한다. 관계(rels)와 콘텐츠 타입까지 제대로 걸어야
    "고아 파트라서 빠졌다"는 착각을 피할 수 있다.
    """
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.drawing.image import Image as XLImage

    plain = path + ".tmp.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "명단"
    for row, value in enumerate([3, 7, 5, 9], start=1):
        sheet.cell(row=row, column=1, value=value)
    chart = BarChart()
    chart.add_data(Reference(sheet, min_col=1, min_row=1, max_row=4))
    sheet.add_chart(chart, "C1")
    sheet.add_image(XLImage(png), "E1")
    sheet["A6"] = "홍길동"
    workbook.save(plain)

    with zipfile.ZipFile(plain) as archive:
        items = {item.filename: archive.read(item.filename) for item in archive.infolist()}
    os.remove(plain)

    rels = items["xl/_rels/workbook.xml.rels"].decode()
    items["xl/_rels/workbook.xml.rels"] = rels.replace(
        "</Relationships>",
        '<Relationship Id="rIdVba"'
        ' Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject"'
        ' Target="vbaProject.bin"/></Relationships>',
    ).encode()
    items["[Content_Types].xml"] = items["[Content_Types].xml"].decode().replace(
        "</Types>",
        '<Override PartName="/xl/vbaProject.bin"'
        ' ContentType="application/vnd.ms-office.vbaProject"/></Types>',
    ).encode()
    items["xl/vbaProject.bin"] = b"fake-macro-bytes"
    items["customXml/item1.xml"] = b"<root>custom</root>"
    items["xl/ctrlProps/ctrlProp1.xml"] = b"<formControlPr/>"
    items["xl/pivotCache/pivotCacheDefinition1.xml"] = b"<pivotCacheDefinition/>"

    with zipfile.ZipFile(path, "w") as archive:
        for name, data in items.items():
            archive.writestr(name, data)


def case_preserve(tmp: str) -> None:
    print("\n[9] 원본 보존 - 차트·그림·매크로·피벗")

    from PIL import Image

    png = os.path.join(tmp, "dot.png")
    Image.new("RGB", (40, 40), (200, 30, 30)).save(png)

    src = os.path.join(tmp, "보존.xlsm")
    _make_rich_xlsm(src, png)

    doc = parse.load(src)
    start = doc.raw_text.index("홍길동")
    findings = [_finding("person", "홍길동", start, start + 3)]

    out = mask.build_file(src, doc, findings, out_dir=os.path.join(tmp, "out"))
    check(bool(out), "사본 파일이 생성됐다", os.path.basename(out or ""))
    if not out:
        return

    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
        before = {item.filename: a.read(item.filename) for item in a.infolist()}
        after = {item.filename: b.read(item.filename) for item in b.infolist()}

    missing = sorted(set(before) - set(after))
    check(not missing, "사라진 파트가 없다", ", ".join(missing) or "없음")

    for part in ("xl/vbaProject.bin", "xl/charts/chart1.xml", "xl/media/image1.png",
                 "xl/pivotCache/pivotCacheDefinition1.xml", "customXml/item1.xml",
                 "xl/ctrlProps/ctrlProp1.xml"):
        check(part in after and after[part] == before.get(part),
              f"{part.rsplit('/', 1)[-1]}가 바이트까지 동일하다")

    changed = sorted(name for name in after if after[name] != before.get(name))
    check(all(name.endswith(".xml") for name in changed),
          "바뀐 파트는 XML뿐이다", ", ".join(changed))

    with zipfile.ZipFile(out) as archive:
        blob = b"".join(archive.read(n) for n in archive.namelist() if n.endswith(".xml"))
    check("홍길동" not in blob.decode("utf-8", "replace"), "값은 지워졌다", "person(len=3)")

    from openpyxl import load_workbook
    try:
        book = load_workbook(out)
        opened = book["명단"]["A6"].value
        book.close()
    except Exception as exc:                       # noqa: BLE001
        opened = f"열지 못함: {type(exc).__name__}"
    check(opened == "[이름]", "엑셀 라이브러리가 사본을 다시 열 수 있다", str(opened))


# ---------------------------------------------------------------------------
# PDF - 좌표로 지운다
# ---------------------------------------------------------------------------
#
# scan.py가 아직 locate.fill_coords()를 부르지 않아서, 여기서는 그 자리를 대신
# 채워 준다. mask.py는 좌표를 절대 스스로 구하지 않는다(팀 분담) - 채워 주지
# 않으면 사본을 만들지 않는 것이 정상 동작이고, 그것도 아래에서 확인한다.

_FONT = os.path.join(REPO_ROOT, "ml", "data_generation", "assets", "fonts", "NanumGothic.otf")


def _make_pdf(path: str, png: str) -> None:
    """한글 본문 + 두 줄에 걸친 값 + 그림 + 선 그림을 한 파일에."""
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname="NG", fontfile=_FONT)
    page.insert_text((72, 100), "담당자 홍길동 주민번호 900101-1234563", fontname="NG", fontsize=12)
    # 값 하나가 두 줄로 갈라진 경우. 사각형이 둘 필요하다.
    page.insert_text((72, 130), "연락처 010-1234-", fontname="NG", fontsize=12)
    page.insert_text((72, 150), "5678 입니다", fontname="NG", fontsize=12)
    page.draw_rect(pymupdf.Rect(60, 170, 300, 220), color=(0, 0, 1))
    page.insert_image(pymupdf.Rect(320, 90, 360, 130), filename=png)

    second = document.new_page()
    second.insert_font(fontname="NG", fontfile=_FONT)
    second.insert_text((72, 100), "예비 연락처 010-9999-8888", fontname="NG", fontsize=12)
    document.save(path)
    document.close()


def _pdf_findings(doc):
    """탐지 결과를 손으로 만든다. 두 줄에 걸친 값은 줄바꿈을 품는다."""
    text = doc.raw_text
    findings = []

    for risk_type, value in [("person", "홍길동"), ("rrn", "900101-1234563"),
                             ("phone", "010-9999-8888")]:
        start = text.index(value)
        findings.append(_finding(risk_type, value, start, start + len(value)))

    start = text.index("010-1234-")
    end = text.index("5678", start) + 4
    findings.append(_finding("phone", text[start:end], start, end))
    return findings


def case_pdf(tmp: str) -> None:
    print("\n[10] PDF 사본 - 좌표 리댁션 / 한글 폰트 / 줄바꿈")

    import pymupdf
    from PIL import Image

    png = os.path.join(tmp, "dot.png")
    if not os.path.exists(png):
        Image.new("RGB", (40, 40), (200, 30, 30)).save(png)

    src = os.path.join(tmp, "공문.pdf")
    _make_pdf(src, png)
    before = _digest(src)

    doc = parse.load(src)
    findings = _pdf_findings(doc)

    filled = locate.fill_coords(doc, findings)          # scan.py가 해야 할 일
    check(filled == len(findings), "좌표가 모두 채워졌다", f"{filled}/{len(findings)}건")

    split = [f for f in findings if chr(10) in f.text]
    check(bool(split) and len(split[0].evidence.get("rects", [])) == 2,
          "두 줄에 걸친 값은 사각형이 둘이다",
          str(len(split[0].evidence.get("rects", []))) + "개")

    out = mask.build_file(src, doc, findings, out_dir=os.path.join(tmp, "out"))
    check(bool(out) and os.path.isfile(out), "사본 파일이 생성됐다", os.path.basename(out or ""))
    if not out:
        return

    masked = pymupdf.open(out)
    pages = [page.get_text() for page in masked]
    joined = chr(10).join(pages)

    check("홍길동" not in joined, "이름이 추출되지 않는다", "person(len=3)")
    check("900101-1234563" not in joined, "주민번호가 추출되지 않는다", "rrn(len=14)")
    check("010-9999-8888" not in joined, "2페이지 값도 지워졌다", "phone(len=13)")
    check("010-1234-" not in joined and "5678" not in joined,
          "두 줄에 걸친 값이 양쪽 다 지워졌다")

    check("[이름]" in joined, "placeholder가 한글로 찍힌다", "[이름]")
    check("????" not in joined, "물음표로 깨지지 않는다")
    check(joined.count("[전화번호]") == 2, "줄이 갈라져도 placeholder는 값마다 하나",
          f"{joined.count('[전화번호]')}회")
    check("담당자" in joined and "입니다" in joined, "가리지 않은 글자는 그대로다")

    check(len(masked[0].get_images()) == 1, "그림이 사본에 남아 있다",
          f"{len(masked[0].get_images())}개")
    check(len(masked[0].get_drawings()) >= 1, "선 그림이 남아 있다",
          f"{len(masked[0].get_drawings())}개")
    check(masked.page_count == 2, "페이지 수가 같다")
    masked.close()

    check(_digest(src) == before, "원본 파일이 변하지 않았다")


def case_pdf_guard(tmp: str) -> None:
    """좌표가 없으면 사본을 만들지 않는다 - 가릴 곳을 모르는 채로 내보내지 않는다."""
    print("\n[11] PDF 안전장치")

    src = os.path.join(tmp, "공문.pdf")
    out_dir = os.path.join(tmp, "out")

    doc = parse.load(src)
    bare = _pdf_findings(doc)                       # fill_coords를 부르지 않았다
    check(mask.build_file(src, doc, bare, out_dir=out_dir) is None,
          "좌표가 비어 있으면 None (scan.py가 fill_coords를 안 부른 상태)")

    doc = parse.load(src)
    findings = _pdf_findings(doc)
    locate.fill_coords(doc, findings)
    findings[0].page = 99                           # 없는 페이지
    check(mask.build_file(src, doc, findings, out_dir=out_dir) is None,
          "없는 페이지를 가리키면 None")

    out = mask.build_file(src, parse.load(src), [], out_dir=out_dir)
    check(bool(out), "findings가 0건이어도 사본은 만든다")


def case_pdf_long_placeholder(tmp: str) -> None:
    """짧은 값을 긴 한글 placeholder로 바꿔도 글자가 찍히는가."""
    print("\n[12] PDF 좁은 칸")

    import pymupdf

    src = os.path.join(tmp, "좁은칸.pdf")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname="NG", fontfile=_FONT)
    page.insert_text((72, 90), "아래는 사내 시스템에서 내려받은 식별번호 목록입니다",
                     fontname="NG", fontsize=9)
    page.insert_text((72, 110), "번호 1234567890123", fontname="NG", fontsize=7)
    document.save(src)
    document.close()

    doc = parse.load(src)
    start = doc.raw_text.index("1234567890123")
    findings = [_finding("rrn", "1234567890123", start, start + 13)]
    locate.fill_coords(doc, findings)

    out = mask.build_file(src, doc, findings, out_dir=os.path.join(tmp, "out"))
    check(bool(out), "사본 파일이 생성됐다")
    if not out:
        return
    masked = pymupdf.open(out)
    text = masked[0].get_text()
    masked.close()
    check("1234567890123" not in text, "값이 지워졌다")
    check("[주민등록번호]" in text, "긴 placeholder도 찍힌다 (글자 크기를 줄인다)",
          text.strip().replace(chr(10), " | "))


def case_scanned_pdf(tmp: str) -> None:
    """텍스트 층이 거의 없는 PDF는 이미지 파이프라인으로 간다 - 사본을 만들지 않는다."""
    print("\n[13] 스캔본 PDF")

    import pymupdf

    src = os.path.join(tmp, "스캔본.pdf")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(pymupdf.Rect(50, 50, 300, 300), filename=os.path.join(tmp, "dot.png"))
    document.save(src)
    document.close()

    doc = parse.load(src)
    check(doc.kind == "image", "스캔본으로 분류된다", f"kind={doc.kind}")
    check(mask.build_file(src, doc, [], out_dir=os.path.join(tmp, "out")) is None,
          "사본을 만들지 않는다 (그림 속 값은 가릴 수 없다)")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="mask_check_")
    try:
        case_text_file(tmp)
        case_cp949(tmp)
        case_unsupported(tmp)
        case_rules()
        case_docx(tmp)
        case_docx_guard(tmp)
        case_xlsx(tmp)
        case_xlsx_guard(tmp)
        case_preserve(tmp)
        case_pdf(tmp)
        case_pdf_guard(tmp)
        case_pdf_long_placeholder(tmp)
        case_scanned_pdf(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: " + ", ".join(_failures))
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
