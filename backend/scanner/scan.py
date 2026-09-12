"""탐지 파이프라인 진입점: parse -> rules -> ner -> hidden -> 오탐제거/인젝션 -> dedupe -> 점수.

backend/shared/schema.py가 정의한 공용 계약(Finding, ScanResult, scan_text/scan_file/
scan_files)의 실제 구현이다.

붙어 있는 것: rules.py(정규식+체크섬), ner.py(이름·주소·조직명),
hidden.py(숨은 텍스트), id_detector.py(신분증 CNN), parser/parse.py(문서 파싱),
parser/locate.py(오프셋->좌표), masking/mask.py(마스킹 사본),
models.py(오탐 제거·인젝션, 지금은 _ENABLE_CLASSIFIER_STAGE로 꺼둠).

"모델이 없어도 엔진 전체가 돌아가야 한다" 원칙에 따라, 모듈이 없거나 약속한
함수가 없으면 그 단계만 건너뛰고 나머지 파이프라인은 그대로 돈다.

탐지기 공통 반환 형식(rules.py / ner.py / hidden.py / id_detector.py 모두 동일):
    [{"field": <schema.RiskType 문자열>, "value": str, "start": int, "end": int,
      "confidence": float}, ...]
    reason과 evidence를 함께 담아 보내면 그 값을 그대로 쓴다 — hidden.py는
    판정 근거(글자색·폰트 크기·복원한 문장)를 evidence에 담아 보내고, 화면 05가
    그것을 그린다.

mask.py가 쓰는 두 함수:
    build(raw_text, findings) -> str        # 텍스트용. scan_text가 부른다.
    build_file(path, doc, findings) -> str  # 파일 사본용. scan_file이 부른다.

좌표 분담(팀 계획서 기준):
    parser/locate.py (B-1)  오프셋 -> 좌표 매핑 함수를 제공한다. span 기하를 아는 쪽
    scan.py          (B-2)  locate.fill_coords를 불러 Finding.bbox와 page를 채운다
    masking/mask.py  (B-1)  그 좌표를 **읽기만** 한다. 다시 찾지 않는다

좌표를 두 군데서 따로 구하면 같은 값이 여러 번 나올 때 엉뚱한 자리를 지운다.
그리고 scan.py가 채우지 않으면 Finding.bbox가 null로 남아, PDF 마스킹 사본이
만들어지지 않고 화면도 미리보기에 하이라이트를 그릴 수 없다.

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
    from backend.scanner.parser import locate
except ImportError:
    locate = None

try:
    from backend.scanner.masking import mask
except ImportError:
    mask = None

# 신분증 이미지 CNN 호출부. models.py와 같은 패턴이다 — B가 부르는 자리를 만들고
# A가 알맹이를 채운다(backend/scanner/README.md: "ml/에서 학습된 모델을 갖다 쓰는 자리").
# 계약: id_detector.detect(path) -> rules.py와 같은 형식의 목록.
#       field는 schema.RiskType의 "id_photo" | "signature" | "id_meta".
try:
    from backend.scanner.detectors import id_detector
except ImportError:
    id_detector = None

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
    # 휴대폰뿐 아니라 집·사무실·인터넷전화·안심번호를 포함한다. schema.py의
    # 라벨도 "전화번호"다 — 화면에 "휴대폰 02-1234-5678"로 나가면 안 된다.
    "phone": "전화번호 형식",
    "email": "이메일 형식",
    "ip": "IP 주소 형식",
    "api_key": "알려진 API 키/토큰 접두어 패턴",
    "db_credential": "DB 접속 문자열(URI) 패턴",
    "injection": "AI에게 내리는 지시로 보이는 문장 (키워드 기반 판정)",
    # hidden.py는 판정 근거별로 훨씬 구체적인 reason을 직접 담아 보낸다.
    # 이건 그게 없을 때만 쓰는 최후 문구다.
    "hidden_text": "서식으로 감춰진 텍스트",
}

# evidence.checksum은 각 탐지기가 직접 담아 보낸다(rules.py의 CHECKSUM_PASS /
# CHECKSUM_NOT_AVAILABLE). 여기서 타입 목록을 따로 들고 있으면, 어느 필드가
# 체크섬 검증되는지에 대한 판단이 두 곳에 생겨서 어긋난다 — 실제로 법인등록번호를
# "검증됨"으로 잘못 표시하고 있었다(알고리즘 출처가 확정되지 않은 필드였다).

# 문장 단위로 잘라 인젝션 여부를 검사한다. 마침표/느낌표/물음표/줄바꿈 기준.
_SENTENCE_SPLIT_PATTERN = re.compile(r"[^.!?\n]+[.!?]?")

# 오탐 제거 분류기에 넘길 context: 탐지된 값 앞쪽 문장(대략 50자).
_CLASSIFIER_CONTEXT_RADIUS = 50

# models.py(오탐 제거 + 인젝션) 연결은 다음 단계로 미룬다. 지금은 rules.py만 연결한
# 최소 버전을 C에 넘기는 게 목표라 꺼둔다. True로 바꾸면 바로 붙는다.
_ENABLE_CLASSIFIER_STAGE = False

# 확장자 -> schema.ScanResult.file_type. 화면(D)이 "PDF 사본 받기"인지 "텍스트 사본
# 받기"인지 구분하는 데 쓰고, mask.build_file도 이 값으로 리댁션 방식을 고른다.
#
# 표를 손으로 두 벌 관리하면 parse.py가 확장자를 늘릴 때 여기가 조용히 뒤처진다.
# 실제로 .csv·.log·.bmp·.gif·.webp·.tif·.tiff·.xlsm 8개가 빠져 있었다. 그래서
# parse.py의 표를 권위로 삼아 그대로 가져다 쓴다.
# parse.load()가 if 분기로 직접 처리해서 그 표에 없는 형식만 여기서 보탠다.
_FILE_TYPE_BY_EXTENSION: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
}
if parse is not None:
    _FILE_TYPE_BY_EXTENSION.update(getattr(parse, "TEXT_EXTENSIONS", {}))
    _FILE_TYPE_BY_EXTENSION.update(getattr(parse, "IMAGE_EXTENSIONS", {}))


def _raw_to_finding(raw: dict, source: str) -> Finding:
    """rules.py/ner.py/hidden.py 공통 반환 형식({field, value, start, end, confidence})을
    Finding으로 바꾼다. field는 이미 schema.RiskType 문자열이라 번역이 필요 없다.

    탐지기가 reason/evidence를 직접 담아 보내면 그것을 그대로 쓴다. hidden.py는
    무엇을 근거로 숨은 텍스트라고 판정했는지(글자색·폰트 크기·제로폭 문자 개수)를
    evidence에, 사람이 읽을 설명을 reason에 담아 보내고 화면 05가 그걸 그린다.
    여기서 일괄로 덮어쓰면 그 정보가 사라진다.
    """
    risk_type = raw["field"]
    evidence = raw.get("evidence") or {}
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
        # 좌표를 이미 아는 탐지기는 직접 담아 보낸다. 이미지 CNN이 그 경우다 —
        # 이미지에는 문자 오프셋이 없어서 _attach_bboxes로는 좌표를 만들 수 없고,
        # YOLO가 준 박스가 유일한 마스킹 근거다. 여기서 버리면 얼굴을 가릴
        # 좌표가 사라진다.
        bbox=raw.get("bbox"),
        page=raw.get("page"),
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


# hidden.py의 _looks_dangerous가 "AI에게 내리는 지시문"이라고 판정했을 때 쓰는 문구.
# 그 판정은 내부에서 models.is_injection을 부른 결과다.
_HIDDEN_INJECTION_KIND = "AI에게 내리는 지시문"


def _promote_hidden_injections(findings: list[Finding]) -> None:
    """숨겨진 텍스트가 AI를 향한 명령이면 injection으로 **타입을 교체**한다.

    hidden_text(25점)는 그 자체로는 "확인이 필요하다"는 신호일 뿐이다. 정상 문서에도
    숨은 텍스트는 있다(메모, 편집 흔적, 서식 잔재). 실제 위험은 그 내용이 AI에게
    내리는 명령일 때 생기고, 그때 injection(50점)이 된다 — schema.py의 점수표가
    이 승격 구조를 전제로 짜여 있다.

    Finding을 새로 만들지 않고 타입만 바꾸는 이유: 둘 다 남기면 한 문장이
    25+50=75점을 받는다. 어떻게 숨겨져 있었는지는 evidence에 그대로 남아 있어서
    화면 05가 "흰 글씨로 숨겨져 있던 명령"이라고 보여줄 수 있다.

    판정 경로가 둘이다.
      - 제로폭·Bidi·태그로 숨긴 경우: hidden.py가 복원한 문장을 이미 판정해서
        evidence["restored_kind"]에 남겨뒀다. 그 결과를 그대로 쓴다.
      - 서식으로 숨긴 경우(흰 글씨·0pt·투명도): 복원할 것이 없고 보이는 문장
        자체가 명령문이다. models.is_injection으로 직접 본다.

    _ENABLE_CLASSIFIER_STAGE와 무관하게 항상 돈다. 그 플래그는 "문서 전체를
    문장 단위로 훑는 인젝션 스캔 + 오탐 제거"를 미뤄둔 것이고, 이쪽은 이미 탐지된
    항목의 위험도를 25점과 50점 중 어디로 볼지 가르는 판정이라 성격이 다르다.
    """
    for f in findings:
        if f.type != "hidden_text":
            continue

        if f.evidence.get("restored_kind") == _HIDDEN_INJECTION_KIND:
            promoted = True
        else:
            # 복원된 문장이 있으면 그것을, 없으면 보이는 문장을 본다.
            candidate = f.evidence.get("restored") or f.text
            promoted, _ = models.is_injection(candidate)

        if not promoted:
            continue

        f.evidence = {**f.evidence, "promoted_from": "hidden_text", "hidden_reason_text": f.reason}
        f.type = "injection"
        f.reason = "숨겨진 자리에서 발견된 AI 지시문"


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
    """확장자로 형식을 추측한다. parse.load()가 판단한 doc.file_type이 없을 때만 쓴다.

    모르는 확장자는 빈 문자열로 둔다. 읽지도 못한 .hwp를 "txt"라고 표시하면 화면이
    "텍스트 사본 받기" 버튼을 띄울 수 있다 — 사본이 없는 파일에 다운로드 버튼이
    붙는다.
    """
    return _FILE_TYPE_BY_EXTENSION.get(os.path.splitext(path)[1].lower(), "")


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

    # 6. 숨겨진 텍스트가 AI 지시문이면 injection으로 승격(25점 -> 50점).
    # dedupe보다 먼저 해야 한다 — 승격되면 가중치가 바뀌고, dedupe는 가중치로
    # 무엇을 남길지 정하기 때문이다. 순서가 뒤집히면 숨겨진 인젝션이 같은 자리의
    # 다른 탐지(api_key 40점 등)에 밀려 사라진다.
    _promote_hidden_injections(findings)

    # 7. 겹치는 구간 정리
    findings = _dedupe(findings)
    _reassign_ids(findings)
    # 걸러낸 항목에도 id를 준다. 화면 03의 "오탐으로 제외한 항목" 카드가 이 목록을
    # 그리는데, id가 다 빈 문자열이면 프론트가 항목을 구분하지 못한다. 번호는
    # findings 뒤에 이어 붙여 한 ScanResult 안에서 유일하게 만든다.
    _reassign_ids(filtered_out, offset=len(findings))

    # 오프셋 -> 페이지 좌표 변환은 scan_file이 한다. locate.fill_coords가 doc 전체를
    # 필요로 하는데(spans의 글자별 경계 + page_map) 여기서는 doc이 없다.

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


def _scan_image(doc) -> ScanResult:
    """텍스트 레이어가 없는 파일(신분증 사진, 스캔본 PDF)을 이미지 파이프라인으로 보낸다.

    parse.py가 kind="image"로 표시해준 파일이 여기로 온다. 정규식·NER·서식 검사는
    글자가 있어야 돌아가므로 이 파일들에는 아무것도 못 하고, 신분증 CNN이 얼굴
    사진·서명·발급일자를 찾아야 한다.

    CNN이 아직 연결되지 않았을 때 findings를 빈 채로 돌려주면 위험점수 0 =
    "안전"(초록불)으로 나간다. 신분증 사진은 고유식별정보 덩어리인데 그걸 안전하다고
    표시하는 것은 이 서비스가 낼 수 있는 가장 위험한 오답이다. 그래서 검사할 수단이
    없으면 error에 남겨, 화면이 점수 대신 안내를 띄우도록 한다.
    """
    result = ScanResult(raw_text="")
    if id_detector is not None and hasattr(id_detector, "detect"):
        # 스캔본 PDF는 페이지마다 그림이 하나씩 구워져 image_paths에 담겨 온다.
        # doc.path는 그중 첫 장이라, 그것만 넘기면 2쪽부터는 검사가 통째로 빠진다
        # (3쪽짜리 실측: 20건 중 6건만 잡혔다). 사진 한 장짜리는 image_paths가
        # 비어 있으므로 doc.path로 떨어진다.
        findings = []
        for page_number, image_path in enumerate(
            getattr(doc, "image_paths", None) or [doc.path], start=1
        ):
            for raw in id_detector.detect(image_path):
                # id_detector는 그림 한 장만 받아서 자기가 몇 쪽인지 모른다.
                # page를 1로 고정해 돌려주므로 여기서 실제 쪽 번호로 덮어쓴다 —
                # 안 그러면 3쪽의 주민번호가 화면에서 1쪽으로 표시되고, 마스킹도
                # 엉뚱한 페이지를 지운다.
                raw["page"] = page_number
                findings.append(_raw_to_finding(raw, "cnn"))
        result.findings = findings
        _reassign_ids(result.findings)
    else:
        result.error = "이미지 파일은 아직 검사할 수 없습니다 (신분증 검사기 연결 전)"
    return result.finalize()


def scan_file(path: str) -> ScanResult:
    """파일 1개를 파싱해서 검사하고, 마스킹된 파일 사본까지 만든다.

    parse.load()가 형식을 판단해서 텍스트(pdf/docx/xlsx/txt)와 이미지(사진, 텍스트
    레이어가 없는 스캔본 PDF)로 갈라주고, 이 함수가 그 kind를 보고 텍스트
    파이프라인과 이미지 파이프라인으로 분기한다. parse가 없는 환경에서는 UTF-8
    텍스트로 직접 읽는 경로로 떨어진다.
    """
    doc = None
    try:
        try:
            if parse is not None and hasattr(parse, "load"):
                doc = parse.load(path)
                # 파서가 이미지로 판정한 파일(사진, 텍스트 레이어 없는 스캔본 PDF)은
                # 글자가 없어서 텍스트 탐지기를 돌릴 것이 없다. 이미지 파이프라인으로 보낸다.
                if getattr(doc, "kind", "text") == "image":
                    result = _scan_image(doc)
                else:
                    result = scan_text(
                        doc.raw_text, meta={"filename": path, "spans": doc.spans}
                    )
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
            detail = (
                str(exc) if _ParseError and isinstance(exc, _ParseError) else type(exc).__name__
            )
            result = ScanResult(filename=path, error=f"파일을 읽지 못했습니다: {detail}")
            result.file_type = _guess_file_type(path)
            return result.finalize()

        result.filename = path
        # 파서가 판단한 형식이 우선이다(스캔본 PDF를 image로 넘기는 등의 판단이 들어있다).
        result.file_type = getattr(doc, "file_type", "") or _guess_file_type(path)

        # 오프셋 -> 페이지 좌표. 이걸 빼먹으면 Finding.bbox가 영원히 null로 남아
        # PDF 마스킹 사본이 아예 만들어지지 않고, 화면도 미리보기에 하이라이트 박스를
        # 그릴 수 없다. mask.py는 여기서 채운 좌표를 **읽기만** 한다 — 좌표를 두 군데서
        # 따로 구하면 같은 값이 여러 번 나올 때 엉뚱한 자리를 지운다.
        #
        # 좌표가 없는 형식(DOCX/XLSX/TXT)과 이미지는 그냥 지나간다. 이미지는 CNN이
        # 이미 bbox를 채워뒀고 doc.spans가 비어 있어서 덮어쓰이지 않는다.
        if doc is not None and locate is not None and hasattr(locate, "fill_coords"):
            locate.fill_coords(doc, result.findings)

        # 마스킹된 **파일** 사본. scan_text가 채운 masked_text(텍스트 치환)와는 별개다 —
        # 제품의 주 동작은 "마스킹된 파일 다운로드"다.
        if doc is not None and mask is not None and hasattr(mask, "build_file"):
            result.masked_path = mask.build_file(path, doc, result.findings)

        return result
    finally:
        # 스캔본 PDF를 검사하려고 구워 낸 페이지 그림을 지운다. 그 그림을 보는 곳은
        # 신분증 CNN(_scan_image)과 스캔본 마스킹(mask.build_file) 둘뿐이고, 둘 다
        # 이 함수 안에서 끝난다.
        #
        # 놔두면 안 되는 이유: 그 그림은 **마스킹하기 전의 원본 신분증 사진**이다.
        # 스캔 1회당 폴더 하나씩 서버 임시 폴더에 쌓이는 것을 실측으로 확인했다.
        # "업로드 파일은 처리 후 즉시 폐기"라는 제품 원칙이 이 중간 산물에도 똑같이
        # 적용된다.
        #
        # finally인 이유: 파싱이나 마스킹 도중 예외가 나도 원본 그림은 반드시
        # 지워야 한다. except 블록이 중간에 return하는 경로가 있어서, 정상 종료
        # 자리에만 두면 그 경로에서 남는다.
        #
        # masked_path(사용자가 내려받을 사본)와 혼동하지 말 것 — 그쪽은 응답이 나간 뒤
        # main.py가 TTL로 지운다. 여기서 지우는 것은 사용자에게 가지 않는 중간 산물이라
        # 응답을 기다릴 필요가 없다.
        if doc is not None and parse is not None and hasattr(parse, "cleanup"):
            parse.cleanup(doc)


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
