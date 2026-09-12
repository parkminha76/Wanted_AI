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
import io
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
        confidence=1.0, source="rule", reason="테스트용",
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


def _make_scanned_pdf(tmp: str, name: str, pages: int = 1):
    """텍스트 층이 없고 그림만 있는 PDF. 스캔해서 올린 신분증이 이 모양이다.

    그림 안에 붉은 덩어리를 한 군데만 넣는다. 그 부분만 지우게 해야 "덮은 게 아니라
    지웠는가"를 볼 수 있다 - 그림 전체를 덮으면 PyMuPDF가 그림 객체를 통째로
    빼버려서, 안에 뭐가 남았는지 확인할 대상 자체가 사라진다.
    """
    import pymupdf
    from PIL import Image, ImageDraw

    photo = os.path.join(tmp, "스캔면.png")
    if not os.path.exists(photo):
        image = Image.new("RGB", (400, 250), (240, 240, 240))
        ImageDraw.Draw(image).rectangle((40, 30, 200, 150), fill=(150, 20, 20))
        image.save(photo)

    src = os.path.join(tmp, name)
    document = pymupdf.open()
    placed = pymupdf.Rect(50, 50, 450, 300)          # 400x250pt = 그림 1px당 1pt
    for _ in range(pages):
        document.new_page().insert_image(placed, filename=photo)
    document.save(src)
    document.close()

    # 붉은 덩어리의 PDF 좌표
    target = pymupdf.Rect(placed.x0 + 40, placed.y0 + 30, placed.x0 + 200, placed.y0 + 150)
    return src, placed, target


def case_scanned_pdf(tmp: str) -> None:
    """스캔본 PDF - 글자가 없으니 그림 픽셀을 지운다."""
    print("\n[13] 스캔본 PDF")

    import pymupdf
    from PIL import Image

    src, placed, target = _make_scanned_pdf(tmp, "스캔본.pdf")
    before = _digest(src)

    doc = parse.load(src)
    check(doc.kind == "image", "스캔본으로 분류된다", f"kind={doc.kind}")
    check(len(doc.image_paths) == 1, "페이지를 그림으로 구웠다", f"{len(doc.image_paths)}장")
    check(doc.path.endswith(".png"), "CNN에 넘길 경로가 그림이다 (ultralytics는 PDF를 못 연다)",
          os.path.basename(doc.path))
    check(doc.image_scale == 2.0, "배율을 기록한다", str(doc.image_scale))

    with Image.open(doc.path) as baked:
        check(baked.size == (595 * 2, 842 * 2), "배율만큼 크게 구웠다", str(baked.size))

    # CNN이 내놓는 모양: 구워 낸 그림의 픽셀 좌표
    scale = doc.image_scale
    findings = [_box_finding("id_photo", (target.x0 * scale, target.y0 * scale,
                                          target.x1 * scale, target.y1 * scale))]

    out = mask.build_file(src, doc, findings, out_dir=os.path.join(tmp, "out"))
    check(bool(out) and os.path.isfile(out), "사본 파일이 생성됐다", os.path.basename(out or ""))
    if not out:
        return

    masked = pymupdf.open(out)
    page = masked[0]
    check(masked.page_count == 1, "페이지 수가 같다")

    # 1) 화면에 보이는 결과: 그 자리가 검다
    pixmap = page.get_pixmap(clip=target, dpi=72)
    samples = pixmap.samples
    dark = sum(1 for i in range(0, len(samples), pixmap.n) if samples[i] < 16)
    ratio = dark / (pixmap.width * pixmap.height)
    check(ratio > 0.95, "그 자리가 검게 덮였다", f"{ratio:.0%}")

    # 2) 덮은 게 아니라 지웠는가 - 파일에 박힌 그림을 꺼내서 직접 본다.
    #    덮기만 했다면 여기서 원래 붉은색이 그대로 나온다.
    images = page.get_images()
    check(len(images) == 1, "그림이 사본에 남아 있다", f"{len(images)}개")
    if images:
        blob = masked.extract_image(images[0][0])["image"]
        with Image.open(io.BytesIO(blob)) as embedded:
            rgb = embedded.convert("RGB")
            colors = {c for _, c in (rgb.getcolors(maxcolors=200000) or [])}
            reds = {c for c in colors if c[0] > c[1] + 40}
            check(not reds, "박힌 그림에서 원본 픽셀이 지워졌다", str(sorted(reds)[:3]))
            # 사본의 페이지는 "칠해진 페이지 그림" 한 장이다. 칠하지 않은 자리는
            # 원래 스캔면이 그대로 있어야 한다 - 그림 안이지만 상자 밖인 점을 본다.
            check(rgb.getpixel((800, 550)) == (240, 240, 240),
                  "지우지 않은 부분은 그림에 그대로 있다", str(rgb.getpixel((800, 550))))
    masked.close()

    check(_digest(src) == before, "원본 파일이 변하지 않았다")


def _check_multipage_scanned(tmp: str, out_dir: str) -> None:
    """여러 쪽짜리 스캔본 — **모든 쪽이 제대로 가려지는가.**

    2026-09-12까지 여기에는 "여러 쪽짜리는 None"을 확인하는 테스트가 있었다.
    `scan.py`의 `_scan_image`가 첫 장만 CNN에 넘기던 시절의 빗장을 지키는
    테스트였는데, 그쪽이 `doc.image_paths`를 전부 돌게 되면서 빗장을 풀었다
    (`mask._mask_scanned_pdf` 주석 참고).

    빗장을 풀면서 이 테스트를 **지우지 않고 뒤집었다.** 지우면 여러 쪽 경로가
    통째로 시험되지 않는 채로 남는다 — 지금은 그쪽이 실제로 쓰이는 길이라
    오히려 더 봐야 한다. 특히 쪽 번호 짝짓기(`finding.page` -> 몇 번째 그림)가
    어긋나면 **2쪽의 주민번호를 1쪽에 칠하고 2쪽은 그대로 내보낸다.**
    """
    import pymupdf
    from PIL import Image

    two, placed, target = _make_scanned_pdf(tmp, "두장.pdf", pages=2)
    doc = parse.load(two)
    check(len(doc.image_paths) == 2, "두 장 모두 구웠다", f"{len(doc.image_paths)}장")

    box = (target.x0 * 2, target.y0 * 2, target.x1 * 2, target.y1 * 2)
    first = _box_finding("id_photo", box)
    second = _box_finding("rrn", box)
    second.page = 2                       # 2쪽에서 찾은 항목
    out = mask.build_file(two, doc, [first, second], out_dir=out_dir)
    check(bool(out) and os.path.isfile(out), "여러 쪽짜리도 사본을 만든다",
          os.path.basename(out or ""))
    if not out:
        return

    masked = pymupdf.open(out)
    check(masked.page_count == 2, "쪽 수가 같다", f"{masked.page_count}쪽")

    # 두 쪽 **모두** 붉은 덩어리가 지워졌어야 한다. 쪽 번호 짝짓기가 어긋나면
    # 한 쪽만 지워지고 다른 쪽에 원본이 그대로 남는다.
    for index in range(masked.page_count):
        images = masked[index].get_images()
        if len(images) != 1:
            check(False, f"{index + 1}쪽에 그림이 하나다", f"{len(images)}개")
            continue
        blob = masked.extract_image(images[0][0])["image"]
        with Image.open(io.BytesIO(blob)) as embedded:
            rgb = embedded.convert("RGB")
            colors = {c for _, c in (rgb.getcolors(maxcolors=200000) or [])}
            reds = {c for c in colors if c[0] > c[1] + 40}
            check(not reds, f"{index + 1}쪽의 원본 픽셀이 지워졌다", str(sorted(reds)[:3]))
            check(rgb.getpixel((800, 550)) == (240, 240, 240),
                  f"{index + 1}쪽의 가리지 않은 부분은 그대로다", str(rgb.getpixel((800, 550))))
    masked.close()


def case_scanned_pdf_guard(tmp: str) -> None:
    """검사되지 않은 페이지가 있으면 사본을 만들지 않는다."""
    print("\n[18] 스캔본 PDF 안전장치")

    out_dir = os.path.join(tmp, "out")

    _check_multipage_scanned(tmp, out_dir)

    src, placed, target = _make_scanned_pdf(tmp, "스캔본.pdf")
    doc = parse.load(src)
    no_box = Finding(id="f_x", type="rrn", text="x", start=0, end=0,
                     confidence=0.9, source="cnn", reason="테스트용", page=1)
    check(mask.build_file(src, doc, [no_box], out_dir=out_dir) is None,
          "좌표 없는 항목이 섞이면 None")

    check(bool(mask.build_file(src, doc, [], out_dir=out_dir)),
          "findings가 0건이어도 사본은 만든다")


# ---------------------------------------------------------------------------
# 이미지 - CNN이 준 bbox를 칠한다
# ---------------------------------------------------------------------------
#
# 이미지에는 문자 오프셋이 없다. id_detector.py가 start/end를 0으로 두고 bbox만
# 채우므로, offset을 쓰는 경로(_plan)로는 한 건도 처리되지 않는다. 그래서 여기서도
# 오프셋이 아니라 좌표로만 만든 finding을 넣는다.


def _box_finding(risk_type: str, box) -> Finding:
    """CNN이 내놓는 모양의 finding. start/end는 0이고 bbox만 있다."""
    return Finding(
        id="f_img", type=risk_type, text="얼굴 사진", start=0, end=0,
        confidence=0.95, source="cnn", reason="테스트용", page=1, bbox=tuple(box),
    )


def _make_photo(path: str, mode: str = "RGB", size=(400, 300)):
    """자리마다 색이 다른 사진. 칠한 뒤 원래 색이 남았는지 보기 쉽다."""
    from PIL import Image, ImageDraw

    image = Image.new(mode, size, 255 if mode == "L" else (240, 240, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 140, 160), fill=64 if mode == "L" else (220, 30, 30))
    draw.rectangle((200, 40, 380, 80), fill=32 if mode == "L" else (30, 120, 220))
    image.save(path)
    return image.size


def case_image(tmp: str) -> None:
    print("\n[14] 이미지 사본 - bbox 칠하기")

    from PIL import Image

    src = os.path.join(tmp, "신분증.png")
    _make_photo(src)
    before = _digest(src)

    doc = parse.load(src)
    check(doc.kind == "image", "이미지로 분류된다", f"kind={doc.kind}")

    findings = [_box_finding("id_photo", (20, 20, 140, 160)),
                _box_finding("rrn", (200, 40, 380, 80))]

    out = mask.build_file(src, doc, findings, out_dir=os.path.join(tmp, "out"))
    check(bool(out) and os.path.isfile(out), "사본 파일이 생성됐다", os.path.basename(out or ""))
    if not out:
        return

    with Image.open(out) as masked:
        masked.load()
        check(masked.size == (400, 300), "크기가 같다", str(masked.size))
        check(masked.format == "PNG", "형식이 같다", str(masked.format))

        # 원본 색은 빨강·파랑처럼 채도가 있다. 상자 안에 남아도 되는 것은 검정과,
        # 유형 이름을 적으면서 생기는 회색 경계(r=g=b)뿐이다.
        for label, box in [("얼굴", (20, 20, 140, 160)), ("주민번호", (200, 40, 380, 80))]:
            patch = masked.crop(box).convert("RGB")
            colors = {color for _, color in (patch.getcolors(maxcolors=100000) or [])}
            leftover = {c for c in colors if len(set(c)) != 1}
            check(not leftover, f"{label} 자리에 원본 색이 남지 않았다", str(sorted(leftover)[:3]))

        check(masked.getpixel((390, 290))[:3] == (240, 240, 240), "가리지 않은 자리는 그대로다")

        # 유형 이름을 흰 글자로 적는다 (****로 뭉개지 않는다).
        # 얼굴 상자는 세로로 길어서 "[얼굴 사진]"이 가로로 안 들어가고, 그때는
        # 글자를 생략하고 검정만 남긴다 - 그 동작도 여기서 같이 본다.
        narrow = masked.crop((20, 20, 140, 160)).convert("L")
        wide = masked.crop((200, 40, 380, 80)).convert("L")
        check(wide.getextrema()[1] > 200, "상자 안에 유형 이름이 적힌다",
              f"가장 밝은 값 {wide.getextrema()[1]}")
        check(narrow.getextrema() == (0, 0), "글자가 안 들어가는 상자는 검정만 남는다")

    check(_digest(src) == before, "원본 파일이 변하지 않았다")


def case_image_exif(tmp: str) -> None:
    """EXIF를 옮기지 않는다 - 썸네일에 가린 자리가 그대로 남는다."""
    print("\n[15] 이미지 EXIF")

    from PIL import Image

    src = os.path.join(tmp, "사진.jpg")
    image = Image.new("RGB", (300, 200), (240, 240, 240))
    exif = image.getexif()
    exif[271] = "TestCam"                        # Make
    exif[305] = "InfoGuard"                      # Software
    image.save(src, exif=exif)

    with Image.open(src) as original:
        check(bool(original.getexif()), "원본에는 EXIF가 있다")

    doc = parse.load(src)
    out = mask.build_file(src, doc, [_box_finding("id_photo", (10, 10, 120, 120))],
                          out_dir=os.path.join(tmp, "out"))
    check(bool(out), "사본 파일이 생성됐다")
    if not out:
        return
    with Image.open(out) as masked:
        check(not masked.getexif(), "사본에는 EXIF가 없다 (썸네일·GPS까지 같이 사라진다)")
        check(masked.format == "JPEG", "JPEG로 저장된다", str(masked.format))


def case_image_modes(tmp: str) -> None:
    """흑백·팔레트 이미지에서도 칠해진다."""
    print("\n[16] 이미지 모드")

    from PIL import Image

    grey = os.path.join(tmp, "스캔.png")
    _make_photo(grey, mode="L")
    doc = parse.load(grey)
    out = mask.build_file(grey, doc, [_box_finding("rrn", (20, 20, 140, 160))],
                          out_dir=os.path.join(tmp, "out"))
    check(bool(out), "흑백 사본이 생성됐다")
    if out:
        with Image.open(out) as masked:
            check(masked.mode == "L", "흑백 그대로 저장된다 (RGB로 부풀리지 않는다)",
                  masked.mode)
            check(masked.crop((20, 20, 140, 160)).getextrema() == (0, 0), "자리가 검게 칠해졌다")

    palette = os.path.join(tmp, "팔레트.png")
    image = Image.new("P", (200, 150))
    image.putpalette([0, 0, 0] + [200, 40, 40] * 255)
    image.paste(1, (10, 10, 100, 100))
    image.save(palette)
    doc = parse.load(palette)
    out = mask.build_file(palette, doc, [_box_finding("signature", (10, 10, 100, 100))],
                          out_dir=os.path.join(tmp, "out"))
    check(bool(out), "팔레트 사본이 생성됐다")
    if out:
        with Image.open(out) as masked:
            check(masked.crop((10, 10, 100, 100)).convert("L").getextrema()[0] == 0,
                  "팔레트 이미지도 칠해진다")


def case_image_guard(tmp: str) -> None:
    """가릴 곳을 모르면 사본을 만들지 않는다."""
    print("\n[17] 이미지 안전장치")

    from PIL import Image

    src = os.path.join(tmp, "신분증.png")
    doc = parse.load(src)
    out_dir = os.path.join(tmp, "out")

    no_box = Finding(id="f_x", type="rrn", text="x", start=0, end=0,
                     confidence=0.9, source="cnn", reason="테스트용", page=1)
    check(mask.build_file(src, doc, [_box_finding("id_photo", (20, 20, 140, 160)), no_box],
                          out_dir=out_dir) is None,
          "좌표 없는 항목이 섞이면 None (반만 가린 사본을 만들지 않는다)")

    check(mask.build_file(src, doc, [_box_finding("rrn", (900, 900, 950, 950))],
                          out_dir=out_dir) is None,
          "좌표가 이미지 밖이면 None")

    check(bool(mask.build_file(src, doc, [], out_dir=out_dir)),
          "findings가 0건이어도 사본은 만든다")

    animated = os.path.join(tmp, "움직임.gif")
    first = Image.new("RGB", (120, 90), (240, 240, 240))
    second = Image.new("RGB", (120, 90), (30, 30, 200))
    first.save(animated, save_all=True, append_images=[second], duration=100, loop=0)
    doc = parse.load(animated)
    check(mask.build_file(animated, doc, [_box_finding("id_photo", (10, 10, 60, 60))],
                          out_dir=out_dir) is None,
          "여러 장짜리 이미지는 None (뒷장에 원본이 남는다)")


# ---------------------------------------------------------------------------
# 임시 파일 정리
# ---------------------------------------------------------------------------


def case_cleanup(tmp: str) -> None:
    """구워 낸 페이지 그림은 scan_file이 끝나면 지운다 - 마스킹 전 원본이 남으면 안 된다."""
    print("\n[19] 임시 파일 정리")

    src, placed, target = _make_scanned_pdf(tmp, "정리.pdf")
    doc = parse.load(src)

    baked_dir = os.path.dirname(doc.image_paths[0])
    check(os.path.isdir(baked_dir), "구운 그림 폴더가 생겼다", os.path.basename(baked_dir))
    check(os.path.basename(baked_dir).startswith("infoguard_pdfimg_"),
          "이름으로 우리 폴더임을 알 수 있다")

    # 사본을 만든 뒤에 지운다 - 사본은 그림을 다 쓰고 난 결과물이라 영향이 없어야 한다
    findings = [_box_finding("id_photo", (target.x0 * 2, target.y0 * 2,
                                          target.x1 * 2, target.y1 * 2))]
    out = mask.build_file(src, doc, findings, out_dir=os.path.join(tmp, "out"))
    check(bool(out), "사본이 먼저 만들어진다")

    removed = parse.cleanup(doc)
    check(removed == 1, "폴더 1개를 지웠다", f"{removed}개")
    check(not os.path.isdir(baked_dir), "구운 그림이 사라졌다")
    check(doc.image_paths == [], "경로 목록도 비웠다")
    check(bool(out) and os.path.isfile(out), "마스킹 사본은 그대로 남아 있다 (사용자가 받을 파일)")

    check(parse.cleanup(doc) == 0, "두 번 불러도 안전하다")

    # 구운 그림이 없는 형식에서도 안전해야 한다
    plain = os.path.join(tmp, "연락처.txt")
    check(parse.cleanup(parse.load(plain)) == 0, "TXT처럼 구운 그림이 없으면 할 일이 없다")

    # 우리가 만들지 않은 폴더는 건드리지 않는다
    outsider = os.path.join(tmp, "남의폴더")
    os.makedirs(outsider, exist_ok=True)
    open(os.path.join(outsider, "소중한파일.txt"), "w").close()
    fake = parse.load(src)
    fake.image_paths = [os.path.join(outsider, "page001.png")]
    check(parse.cleanup(fake) == 0, "이름이 다른 폴더는 지우지 않는다")
    check(os.path.isdir(outsider), "남의 폴더는 그대로다")
    parse.cleanup(parse.load(src))      # 방금 다시 구운 것 정리


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
        case_image(tmp)
        case_image_exif(tmp)
        case_image_modes(tmp)
        case_image_guard(tmp)
        case_scanned_pdf_guard(tmp)
        case_cleanup(tmp)
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
