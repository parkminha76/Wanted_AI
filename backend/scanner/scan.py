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
build_file은 doc(ParsedDoc, parse.load()가 준 것)의 spans를 받아서 findings의
offset(start/end)을 bbox로 되짚어야 한다 — masked_text는 텍스트 치환이라
오프셋만 있으면 되지만, PDF 리댁션은 페이지 좌표(bbox)가 있어야 실제로 값을
지울 수 있다. doc 없이는 build_file을 호출할 수 없다(parser가 준비돼야 한다).

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
    Finding으로 바꾼다. field는 이미 schema.RiskType 문자열이라 번역이 필요 없다."""
    risk_type = raw["field"]
    evidence = {"checksum": "pass"} if risk_type in _CHECKSUM_VERIFIED_TYPES else {}
    return Finding(
        id="",  # 최종 목록이 정해진 뒤 _reassign_ids에서 한 번에 부여한다.
        type=risk_type,
        text=raw["value"],
        start=raw["start"],
        end=raw["end"],
        confidence=raw["confidence"],
        source=source,
        reason=_REASONS.get(risk_type, "탐지 규칙 일치"),
        evidence=evidence,
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


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """구간이 겹치면 위험 가중치(schema.RISK_WEIGHTS)가 높은 쪽만 남긴다.
    안 그러면 같은 값을 여러 탐지기가 동시에 잡을 때(예: 이메일을 NER이 조직명으로도
    잡는 경우) 점수가 부풀려진다."""
    by_weight = sorted(findings, key=lambda f: f.weight, reverse=True)
    kept: list[Finding] = []
    for f in by_weight:
        if any(f.start < k.end and k.start < f.end for k in kept):
            continue
        kept.append(f)
    return sorted(kept, key=lambda f: f.start)


def _reassign_ids(findings: list[Finding], offset: int = 0) -> None:
    for i, f in enumerate(findings, start=offset):
        f.id = schema.make_finding_id(i)


def _guess_file_type(path: str) -> str:
    return _FILE_TYPE_BY_EXTENSION.get(os.path.splitext(path)[1].lower(), "txt")


def scan_text(text: str, meta: dict | None = None) -> ScanResult:
    """텍스트 1건을 검사한다. 훈련 모드(C)의 실시간 답장 스캔이 이 함수를 직접 호출한다."""
    meta = meta or {}
    findings: list[Finding] = []

    # 1. 정규식 + 체크섬
    findings += [_raw_to_finding(d, "rule") for d in rules.find_all(text)]

    # 2. NER — 모델이 아직 없으면(ner.py가 비어 있으면) 건너뛴다.
    if ner is not None and hasattr(ner, "detect"):
        findings += [_raw_to_finding(d, "ner") for d in ner.detect(text)]

    # 3. 서식 검사(숨은 텍스트) — 파서가 뽑아준 서식 정보(spans)가 있을 때만 가능하다.
    if hidden is not None and hasattr(hidden, "detect") and meta.get("spans"):
        findings += [_raw_to_finding(d, "format") for d in hidden.detect(meta["spans"])]

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

    result = ScanResult(
        filename=meta.get("filename", ""),
        raw_text=text,
        findings=findings,
        filtered_out=filtered_out,
    )

    # 마스킹 사본 — masking 모듈이 아직 없으면 원문 그대로 둔다.
    if mask is not None and hasattr(mask, "build"):
        result.masked_text = mask.build(result.raw_text, result.findings)

    return result.finalize()  # 7. 위험 점수 계산


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
            result = scan_text(
                doc.raw_text, meta={"filename": path, "spans": getattr(doc, "spans", [])}
            )
        else:
            with open(path, encoding="utf-8") as fh:
                raw_text = fh.read()
            result = scan_text(raw_text, meta={"filename": path})
    except Exception as exc:  # noqa: BLE001
        # 업로드된 파일은 무엇이든 들어올 수 있는 시스템 경계다. 파일 하나가
        # 깨졌다고 예외를 위로 던지면 scan_files가 통째로 죽어서, 같이 올린
        # 멀쩡한 파일들의 결과까지 날아간다("파일 10개를 위험도순으로" 화면이
        # 파일 하나 때문에 통째로 실패한다). schema.ScanResult.error가 바로
        # 이 경우를 위해 있는 필드다.
        #
        # 메시지에 파일 내용을 넣지 않는다 — 예외 문자열에 원문 조각이 섞여
        # 화면까지 나가면 개인정보가 새는 셈이다.
        result = ScanResult(filename=path, error=f"파일을 읽지 못했습니다 ({type(exc).__name__})")
        result.file_type = _guess_file_type(path)
        return result.finalize()

    result.filename = path
    result.file_type = _guess_file_type(path)

    # 마스킹된 **파일** 사본. scan_text가 채운 masked_text(텍스트 치환)와는 별개다 —
    # 제품의 주 동작은 "마스킹된 파일 다운로드"이고, PDF에서 값을 실제로 지우려면
    # 오프셋이 아니라 페이지 좌표(bbox)가 필요하다. 그 좌표는 doc.spans에만 있어서
    # ParsedDoc을 통째로 넘긴다. parser와 mask가 둘 다 준비돼야 동작한다.
    if doc is not None and mask is not None and hasattr(mask, "build_file"):
        result.masked_path = mask.build_file(path, doc, result.findings)

    return result


def scan_files(paths: list[str]) -> ScanBatch:
    """파일 여러 개를 검사하고 위험도 순으로 정렬해 돌려준다."""
    return ScanBatch(results=[scan_file(p) for p in paths])
