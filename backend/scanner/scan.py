"""탐지 파이프라인 진입점: parse -> rules -> ner -> hidden -> 오탐제거/인젝션 -> dedupe -> 점수.

backend/shared/schema.py가 정의한 공용 계약(Finding, ScanResult, scan_text/scan_file/
scan_files)의 실제 구현이다.

ner(detectors/ner.py), hidden(detectors/hidden.py), parser(parser/parse.py)는 아직
팀원 작업이 끝나지 않아 비어 있거나 아예 없을 수 있다. "모델이 없어도 엔진 전체가
돌아가야 한다" 원칙에 따라, 그 모듈이 없거나 detect/load 함수가 없으면 그 단계만
건너뛰고 나머지 파이프라인은 그대로 돈다.

ner.py / hidden.py가 새로 구현할 때 지켜야 할 반환 형식(rules.py와 동일):
    [{"field": <schema.RiskType 문자열>, "value": str, "start": int, "end": int,
      "confidence": float}, ...]

mask.py는 함수가 둘 필요하다:
    build(raw_text, findings) -> str        # 텍스트용. scan_text가 부른다.
    build_file(path, doc, findings) -> str  # 파일 사본용. scan_file이 부른다.

오프셋 -> 페이지 좌표(bbox) 변환은 **scan.py가 한다**(_attach_bboxes). mask.py가
계산해서 쓰고 버리면 Finding.bbox 칸이 빈 채로 화면에 나가서, D가 PDF 미리보기에
형광펜을 칠할 수 없다(좌표를 모르니까). 계산은 한 번, 읽는 곳은 둘 — mask.py도
읽고 화면도 읽는다.

좌표는 parse.py의 TextSpan(dataclass, dict 아님)에서 온다. 그 조각이 탐지값보다
넓으면 그 bbox를 그대로 쓰는 순간 멀쩡한 글자까지 리댁션 대상이 되므로, 조각은
글자 단위처럼 촘촘해야 한다(PyMuPDF get_texttrace()가 주는 수준).

단계별 계획: "rules.py만 연결한 최소 버전을 먼저 완성해서 C(훈련 모드)에 넘긴다"는
원칙에 따라, models.py(오탐 제거 + 인젝션) 연결은 지금 단계에서는 꺼둔다
(_ENABLE_CLASSIFIER_STAGE). 로직은 이미 구현돼 있으니 다음 단계에서 플래그만
켜면 된다.
"""

from __future__ import annotations

import os
import re

from backend.scanner.detectors import models, rules
from backend.shared import schema
from backend.shared.schema import Finding, ScanBatch, ScanResult

try:
    from backend.scanner.detectors import ner
except ImportError:
    ner = None

try:
    from backend.scanner.detectors import hidden
except ImportError:
    hidden = None

try:
    from backend.scanner.parser import parse
except ImportError:
    parse = None

try:
    from backend.scanner.masking import mask
except ImportError:
    mask = None

# 파일을 못 읽는 것은 "예상되는 실패"라 ScanResult.error로 바꿔 돌려준다.
# 반대로 AttributeError 같은 엔진 버그를 여기서 함께 삼키면, 코드 오류가
# "파일을 읽지 못했습니다"로 위장돼 원인 찾는 데만 한참 걸린다(실제로 겪었다).
# 예상 못 한 예외는 그냥 올려보내고, 배치가 죽지 않게 막는 것은 scan_files가 한다.
_ParseError = getattr(parse, "ParseError", None) if parse is not None else None
_FILE_ERRORS: tuple[type[BaseException], ...] = (OSError, UnicodeDecodeError)
if _ParseError is not None:
    _FILE_ERRORS += (_ParseError,)


_REASONS: dict[str, str] = {
    "rrn": "생년월일 유효성과 체크섬을 통과한 주민등록번호 형식",
    "foreign_reg": "외국인등록번호 형식 (뒷자리 첫 숫자 5~8)",
    "biz_reg": "체크섬을 통과한 사업자등록번호 형식",
    "corp_reg": "체크섬을 통과한 법인등록번호 형식",
    "driver_license": "지역코드가 유효 범위인 운전면허번호 형식",
    "passport": "여권번호 형식",
    "card": "Luhn 체크섬을 통과한 카드번호 형식",
    "account": "계좌번호로 보이는 숫자 패턴 (체크섬 검증 불가 — 분류기가 최종 판정)",
    "phone": "휴대폰 번호 형식",
    "email": "이메일 형식",
    "ip": "IP 주소 형식",
    "api_key": "알려진 API 키/토큰 접두어 패턴",
    "db_credential": "DB 접속 문자열(URI) 패턴",
    "injection": "AI에게 내리는 지시로 보이는 문장 (키워드 기반 판정)",
    # hidden.py는 판정 근거별로 훨씬 구체적인 reason을 직접 담아 보낸다.
    # 이건 그게 없을 때만 쓰는 최후 문구다.
    "hidden_text": "서식으로 감춰진 텍스트",
}

# 체크섬까지 검증된 타입은 evidence에 그 사실을 남긴다 (화면이 근거로 보여준다).
_CHECKSUM_VERIFIED_TYPES = {"rrn", "biz_reg", "corp_reg", "card"}

# 문장 단위로 잘라 인젝션 여부를 검사한다. 마침표/느낌표/물음표/줄바꿈 기준.
_SENTENCE_SPLIT_PATTERN = re.compile(r"[^.!?\n]+[.!?]?")

# 오탐 제거 분류기에 넘길 context: 탐지된 값 앞쪽 문장(대략 50자).
_CLASSIFIER_CONTEXT_RADIUS = 50

# models.py(오탐 제거 + 인젝션) 연결은 다음 단계로 미룬다. 지금은 rules.py만 연결한
# 최소 버전을 C에 넘기는 게 목표라 꺼둔다. True로 바꾸면 바로 붙는다.
_ENABLE_CLASSIFIER_STAGE = False

# 확장자 -> schema.ScanResult.file_type. 화면(D)이 "PDF 사본 받기"인지 "텍스트 사본
# 받기"인지 구분하는 데 쓰고, mask.build_file도 이 값으로 리댁션 방식을 고른다.
_FILE_TYPE_BY_EXTENSION: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".txt": "txt",
    ".md": "md",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
}


def _raw_to_finding(raw: dict, source: str) -> Finding:
    """rules.py/ner.py/hidden.py 공통 반환 형식({field, value, start, end, confidence})을
    Finding으로 바꾼다. field는 이미 schema.RiskType 문자열이라 번역이 필요 없다.

    탐지기가 reason/evidence를 직접 담아 보내면 그것을 그대로 쓴다. hidden.py는
    무엇을 근거로 숨은 텍스트라고 판정했는지(글자색·폰트 크기·제로폭 문자 개수)를
    evidence에, 사람이 읽을 설명을 reason에 담아 보내고 화면 05가 그걸 그린다.
    여기서 일괄로 덮어쓰면 그 정보가 사라진다.
    """
    risk_type = raw["field"]
    evidence = raw.get("evidence")
    if evidence is None:
        evidence = {"checksum": "pass"} if risk_type in _CHECKSUM_VERIFIED_TYPES else {}
    return Finding(
        id="",  # 최종 목록이 정해진 뒤 _reassign_ids에서 한 번에 부여한다.
        type=risk_type,
        text=raw["value"],
        start=raw["start"],
        end=raw["end"],
        confidence=raw["confidence"],
        source=source,
        reason=raw.get("reason") or _REASONS.get(risk_type, "탐지 규칙 일치"),
        evidence=dict(evidence),
    )


def _iter_sentences(text: str):
    """문장 단위로 나누되 raw_text 기준 시작/끝 오프셋을 같이 돌려준다."""
    for m in _SENTENCE_SPLIT_PATTERN.finditer(text):
        chunk = m.group()
        stripped = chunk.strip()
        if not stripped:
            continue
        start = m.start() + chunk.index(stripped)
        yield stripped, start, start + len(stripped)


def _find_injections(text: str) -> list[Finding]:
    """문장마다 models.is_injection을 돌려 인젝션 후보를 findings로 만든다."""
    findings = []
    for sentence, start, end in _iter_sentences(text):
        is_command, confidence = models.is_injection(sentence)
        if not is_command:
            continue
        findings.append(
            Finding(
                id="",
                type="injection",
                text=sentence,
                start=start,
                end=end,
                confidence=confidence,
                source="classifier",
                reason=_REASONS["injection"],
            )
        )
    return findings


def _apply_classifier_filters(
    findings: list[Finding], raw_text: str
) -> tuple[list[Finding], list[Finding]]:
    """오탐 제거 분류기로 걸러낸다. injection은 이미 분류기 결과라 그대로 통과시킨다."""
    kept: list[Finding] = []
    filtered_out: list[Finding] = []
    for f in findings:
        if f.type == "injection":
            kept.append(f)
            continue
        context = raw_text[max(0, f.start - _CLASSIFIER_CONTEXT_RADIUS) : f.start]
        is_real, verdict_confidence = models.filter_false_positive(f.text, context, f.type)
        # 분류기가 주는 확신도는 "판정에 대한 확신"이지 "개인정보일 확률"이 아니다.
        # 통과시킬 때만 곱한다 — 걸러낸 항목에도 곱하면 "0.9 확신으로 개인정보가
        # 아니다"가 "0.54 확신으로 개인정보다"로 뒤집혀 화면에 나간다.
        if is_real:
            f.confidence = round(f.confidence * verdict_confidence, 3)
            f.evidence = {**f.evidence, "prob_positive": verdict_confidence}
            kept.append(f)
        else:
            f.evidence = {**f.evidence, "prob_positive": round(1.0 - verdict_confidence, 3)}
            filtered_out.append(f)
    return kept, filtered_out


def _merge_hidden_evidence(survivor: Finding, dropped: Finding) -> None:
    """밀려난 hidden_text의 판정 근거를 살아남은 Finding의 evidence로 옮긴다."""
    survivor.evidence = {
        **survivor.evidence,
        "hidden": {"reason": dropped.reason, **dropped.evidence},
    }


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """구간이 겹치면 위험 가중치(schema.RISK_WEIGHTS)가 높은 쪽만 남긴다.
    안 그러면 같은 값을 여러 탐지기가 동시에 잡을 때(예: 이메일을 NER이 조직명으로도
    잡는 경우) 점수가 부풀려진다.

    단, 밀려나는 쪽이 hidden_text면 그 사실을 살아남은 쪽의 evidence["hidden"]으로
    옮겨 담는다. 숨겨진 자리에서 API 키가 나오면 가중치가 높은 api_key(40점)만 남고
    hidden_text(25점)가 통째로 지워지는데, 그러면 **"이 API 키는 투명 텍스트로
    숨겨져 있었다"는 사실이 화면까지 가지 못한다** — 데모에서 가장 임팩트 있는
    부분이 바로 그거다. 그렇다고 둘 다 Finding으로 남기면 한 문장이 65점(40+25)을
    받아 점수가 부풀려진다. 그래서 타입은 하나만 남기고 근거만 옮긴다
    (schema.py가 hidden_text -> injection 승격에서 쓰는 방식과 같다).
    """
    by_weight = sorted(findings, key=lambda f: f.weight, reverse=True)
    kept: list[Finding] = []
    for f in by_weight:
        overlapping = [k for k in kept if f.start < k.end and k.start < f.end]
        if overlapping:
            if f.type == "hidden_text":
                _merge_hidden_evidence(overlapping[0], f)
            continue
        kept.append(f)
    return sorted(kept, key=lambda f: f.start)


def _reassign_ids(findings: list[Finding], offset: int = 0) -> None:
    for i, f in enumerate(findings, start=offset):
        f.id = schema.make_finding_id(i)


def _guess_file_type(path: str) -> str:
    return _FILE_TYPE_BY_EXTENSION.get(os.path.splitext(path)[1].lower(), "txt")


def _union_bbox(boxes: list[tuple]) -> tuple[float, float, float, float]:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _clip_span_bbox(span, start: int, end: int) -> tuple[float, float, float, float]:
    """줄 단위 조각의 bbox를 탐지값이 차지하는 부분만큼 가로로 잘라낸다.

    parse.py의 TextSpan은 한 줄이 조각 하나다("Contact: 010-1234-5678" 전체가
    조각 1개). 그 bbox를 그대로 리댁션에 쓰면 전화번호만 지우려 해도
    "Contact: "까지 삭제 대상이 된다.

    글자별 좌표가 없어서 글자 수 비례로 자른다 — 한글과 ASCII의 폭이 달라
    정확하지 않다. 값이 덜 덮이면 개인정보가 그대로 남는 쪽이 더 위험하므로
    양옆으로 글자 하나 폭만큼 넓혀 둔다. 정확한 좌표는 parse.py가 글자별
    bbox를 넘겨줘야 나온다(get_texttrace()의 chars에 이미 들어 있다).
    """
    x0, y0, x1, y1 = span.bbox
    length = span.end - span.start
    if length <= 0:
        return (x0, y0, x1, y1)
    width = x1 - x0
    lead = max(start - span.start, 0) / length
    trail = (min(end, span.end) - span.start) / length
    pad = width / length
    return (
        max(x0, x0 + width * lead - pad),
        y0,
        min(x1, x0 + width * trail + pad),
        y1,
    )


def _group_rects_by_line(rects: list[dict]) -> list[dict]:
    """같은 페이지에서 y구간이 겹치는 네모들을 한 줄로 묶어 하나로 합친다.
    한 줄이 조각 여러 개로 쪼개져 오는 경우(글꼴이 섞인 줄)를 위한 것이다."""
    ordered = sorted(rects, key=lambda r: (r["page"] or 0, r["bbox"][1], r["bbox"][0]))
    lines: list[dict] = []
    for rect in ordered:
        page, box = rect["page"], rect["bbox"]
        if lines:
            last = lines[-1]
            same_line = (
                last["page"] == page and box[1] < last["bbox"][3] and last["bbox"][1] < box[3]
            )
            if same_line:
                last["bbox"] = _union_bbox([last["bbox"], box])
                continue
        lines.append({"page": page, "bbox": box})
    return lines


def _attach_bboxes(findings: list[Finding], spans) -> None:
    """findings의 오프셋을 페이지 좌표로 되짚어 bbox와 evidence["rects"]를 채운다.

    주소처럼 긴 값은 줄 끝에서 잘려 두 줄에 걸치는데, 그러면 네모가 2개 필요하다.
    그런데 Finding.bbox는 네모 하나짜리 칸이다. 둘을 하나로 합친 네모로 리댁션하면
    그 줄의 멀쩡한 글자까지 같이 지워진다("계약자 주소:"와 "입니다. 연락처는"까지
    삭제된다). 그래서 용도를 나눈다:
      - bbox: 합집합 네모 1개 — 화면 하이라이트용
      - evidence["rects"]: 줄별 정밀 네모 여러 개 — 실제로 지울 때 mask.py가 쓴다
    evidence는 자유 형식이라 schema 계약을 건드리지 않는다.
    """
    for f in findings:
        overlapping = [s for s in spans if s.bbox and f.start < s.end and s.start < f.end]
        if not overlapping:
            continue
        rects = _group_rects_by_line(
            [
                {"page": s.page, "bbox": _clip_span_bbox(s, f.start, f.end)}
                for s in overlapping
            ]
        )
        f.evidence = {**f.evidence, "rects": rects}
        f.bbox = _union_bbox([r["bbox"] for r in rects])
        f.page = rects[0]["page"]


def scan_text(text: str, meta: dict | None = None) -> ScanResult:
    """텍스트 1건을 검사한다. 훈련 모드(C)의 실시간 답장 스캔이 이 함수를 직접 호출한다."""
    meta = meta or {}
    findings: list[Finding] = []

    # 1. 정규식 + 체크섬
    findings += [_raw_to_finding(d, "rule") for d in rules.find_all(text)]

    # 2. NER — 모델이 아직 없으면(ner.py가 비어 있으면) 건너뛴다.
    if ner is not None and hasattr(ner, "detect"):
        findings += [_raw_to_finding(d, "ner") for d in ner.detect(text)]

    # 3. 숨은 텍스트. 파서가 준 서식 정보(spans)가 있으면 흰 글씨·0pt·숨김 속성까지
    # 보고, 없으면(훈련 모드의 실시간 답장 스캔) 문자열만으로 제로폭·Bidi·태그
    # 문자를 잡는다 — 서식을 못 봐도 이쪽은 잡을 수 있어서 건너뛰면 손해다.
    if hidden is not None:
        spans = meta.get("spans")
        if spans and hasattr(hidden, "detect"):
            findings += [_raw_to_finding(d, "format") for d in hidden.detect(spans)]
        elif hasattr(hidden, "detect_text"):
            findings += [_raw_to_finding(d, "format") for d in hidden.detect_text(text)]

    # 4. 인젝션 + 5. 오탐 제거 — models.py 연결은 다음 단계로 미뤄뒀다(_ENABLE_CLASSIFIER_STAGE).
    filtered_out: list[Finding] = []
    if _ENABLE_CLASSIFIER_STAGE:
        findings += _find_injections(text)
        findings, filtered_out = _apply_classifier_filters(findings, text)

    # 6. 겹치는 구간 정리
    findings = _dedupe(findings)
    _reassign_ids(findings)
    # 걸러낸 항목에도 id를 준다. 화면 03의 "오탐으로 제외한 항목" 카드가 이 목록을
    # 그리는데, id가 다 빈 문자열이면 프론트가 항목을 구분하지 못한다. 번호는
    # findings 뒤에 이어 붙여 한 ScanResult 안에서 유일하게 만든다.
    _reassign_ids(filtered_out, offset=len(findings))

    # 7. 오프셋 -> 페이지 좌표. 파서가 서식 정보를 준 파일 검사에서만 가능하다
    # (훈련 모드의 텍스트 스캔은 좌표라는 개념 자체가 없다).
    if meta.get("spans"):
        _attach_bboxes(findings, meta["spans"])

    result = ScanResult(
        filename=meta.get("filename", ""),
        raw_text=text,
        findings=findings,
        filtered_out=filtered_out,
    )

    # 마스킹 사본 — masking 모듈이 아직 없으면 원문 그대로 둔다.
    if mask is not None and hasattr(mask, "build"):
        result.masked_text = mask.build(result.raw_text, result.findings)

    return result.finalize()  # 8. 위험 점수 계산


def scan_file(path: str) -> ScanResult:
    """파일 1개를 파싱해서 검사하고, 마스킹된 파일 사본까지 만든다.

    parser 모듈(backend/scanner/parser/parse.py)이 아직 없어서, 지금은 UTF-8 텍스트를
    직접 읽어 scan_text로 넘기는 임시 다리 역할만 한다. PDF/DOCX/이미지 분기는
    parse.load가 준비되면 이 함수의 분기만 바꿔 끼우면 된다.
    """
    doc = None
    try:
        if parse is not None and hasattr(parse, "load"):
            doc = parse.load(path)
            result = scan_text(doc.raw_text, meta={"filename": path, "spans": doc.spans})
        else:
            with open(path, encoding="utf-8") as fh:
                raw_text = fh.read()
            result = scan_text(raw_text, meta={"filename": path})
    except _FILE_ERRORS as exc:
        # 업로드된 파일은 무엇이든 들어올 수 있는 시스템 경계라, 못 읽는 파일은
        # 예외가 아니라 결과로 돌려준다(schema.ScanResult.error가 그 자리다).
        # parse.ParseError의 메시지는 파일 내용을 담지 않기로 계약돼 있어서
        # 그대로 내보내고, 그 외 예외는 메시지에 원문 조각이 섞일 수 있으니
        # 종류만 남긴다.
        detail = str(exc) if _ParseError and isinstance(exc, _ParseError) else type(exc).__name__
        result = ScanResult(filename=path, error=f"파일을 읽지 못했습니다: {detail}")
        result.file_type = _guess_file_type(path)
        return result.finalize()

    result.filename = path
    # 파서가 판단한 형식이 우선이다(스캔본 PDF를 image로 넘기는 등의 판단이 들어있다).
    result.file_type = getattr(doc, "file_type", "") or _guess_file_type(path)

    # 페이지 번호. 좌표가 있는 PDF는 _attach_bboxes가 이미 채웠고, docx/xlsx처럼
    # 좌표가 없는 형식은 page_map(문자 1개당 페이지·시트 번호 1개)으로 채운다.
    page_map = getattr(doc, "page_map", None)
    if page_map:
        for f in result.findings:
            if f.page is None and f.start < len(page_map):
                f.page = page_map[f.start]

    # 마스킹된 **파일** 사본. scan_text가 채운 masked_text(텍스트 치환)와는 별개다 —
    # 제품의 주 동작은 "마스킹된 파일 다운로드"이고, PDF에서 값을 실제로 지우려면
    # 오프셋이 아니라 페이지 좌표(bbox)가 필요하다. 그 좌표는 doc.spans에만 있어서
    # ParsedDoc을 통째로 넘긴다. parser와 mask가 둘 다 준비돼야 동작한다.
    if doc is not None and mask is not None and hasattr(mask, "build_file"):
        result.masked_path = mask.build_file(path, doc, result.findings)

    return result


def scan_files(paths: list[str]) -> ScanBatch:
    """파일 여러 개를 검사하고 위험도 순으로 정렬해 돌려준다.

    파일 하나가 예상 못 한 예외로 죽어도 배치는 끝까지 돈다 — 같이 올린 멀쩡한
    파일들의 결과까지 날아가면 "파일 10개를 위험도순으로" 화면이 파일 하나 때문에
    통째로 실패한다. 예상되는 파일 오류는 scan_file이 이미 error로 바꿔 돌려주므로,
    여기서 잡히는 것은 엔진 버그다. 그래서 메시지를 구분해 둔다.
    """
    results = []
    for path in paths:
        try:
            results.append(scan_file(path))
        except Exception as exc:  # noqa: BLE001
            broken = ScanResult(filename=path, error=f"검사 중 오류 ({type(exc).__name__})")
            broken.file_type = _guess_file_type(path)
            results.append(broken.finalize())
    return ScanBatch(results=results)
