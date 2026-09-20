"""
docXray 탐지 엔진 공용 계약 (Contract)
=======================================

이 파일은 4명이 주고받는 데이터의 "규격"이다.
B(엔진)가 만들고, C(훈련 모드)와 D(화면)가 소비한다.

바꿀 때 규칙
------------
1. 필드를 추가하는 것은 자유. 기존 필드를 지우거나 의미를 바꾸는 것은 4명 합의 후.
2. 오프셋(start/end)은 **항상 ScanResult.raw_text 기준**이다. masked_text 기준이 아니다.
3. 탐지 결과는 전부 findings 하나에 넣는다. 숨은 명령용 별도 리스트는 두지 않는다.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional


# 이 규격의 버전. 필드를 추가하면 뒷자리, 기존 필드의 의미를 바꾸면 앞자리를 올린다.
# 응답 JSON에 실려 나가므로, 화면이 이상하게 나올 때 "누가 옛날 규격을 쓰고 있나"를
# 바로 확인할 수 있다.
# 1.1 -> 1.2: RiskType에 "emp_no"(사번) 추가, LABEL_TO_TYPE 역매핑 추가 (A, 09-09)
# 1.2 -> 1.3: ScanResult.pages(쪽·시트 경계) 추가 — 화면 미리보기 쪽 나누기용 (B, 09-15)
# 1.3 -> 1.4: ScanResult.action_guide(우선 조치 카드) 추가 — 결과 화면 "그래서 뭘
#             해야 하나" 답을 서버가 만들어 내려준다 (B, 09-16)
# 1.4 -> 2.0: compute_risk_score의 100점 포화 구간을 부드럽게 바꿈(_saturate_above_knee).
#             RISK_THRESHOLD_HIGH(60) 이하는 그대로지만, 그 위 raw 합계가 100을
#             넘던 문서들은 전부 100.0으로 뭉쳐 있던 것이 이제 100 미만에서 서로
#             갈린다 — 같은 findings로도 risk_score 값 자체가 달라지므로(필드
#             추가가 아니라 기존 필드의 의미 변경) 앞자리를 올린다 (A, 09-16)
# 2.0 -> 2.1: ScanBatch.risk_level_counts/top_risk_types 추가 — 배치 업로드 요약
#             카드("고위험 3개", "가장 흔한 위험: 이름 154건")를 프론트가 파일
#             목록을 직접 집계하지 않고 바로 그릴 수 있게 한다 (A, 09-16)
# 2.1 -> 2.2: ScanResult.db_id 추가 — DB 저장이 성공했을 때의 ScanResultRow.id.
#             화면이 숨은 명령 상태를 PATCH할 때 이 값이 필요하다 (A, 09-16)
SCHEMA_VERSION = "2.2"


# ---------------------------------------------------------------------------
# 타입 정의
# ---------------------------------------------------------------------------

RiskType = Literal[
    # --- 규칙(정규식 + 체크섬)으로 잡는 것 — 형식이 고정된 값 ---
    # 개인정보보호법상 고유식별정보 4종
    "rrn",              # 주민등록번호
    "passport",         # 여권번호
    "driver_license",   # 운전면허번호
    "foreign_reg",      # 외국인등록번호
    # 금전
    "account",          # 계좌번호
    "card",             # 카드번호
    # 자격증명
    "api_key",          # API 키 / 액세스 토큰
    "db_credential",    # DB 접속 문자열 (postgres:// 등)
    # 연락처
    "email",
    "phone",
    # 사업자 정보 — 공개되는 값이라 위험도가 낮다
    "biz_reg",          # 사업자등록번호
    "corp_reg",         # 법인등록번호
    "ip",               # IP 주소

    # 사내 식별자 — 사업자등록번호·전화번호와 자릿수가 겹쳐 오탐이 잦다.
    # (오탐 제거 분류기가 "사번 vs 일반 숫자열" 쌍을 다루기 위해 09-09 추가)
    "emp_no",           # 사번
    "birth_date",       # 생년월일 — "생년월일" 등 단서어 옆 날짜(rules.py) + 이미지 CNN, person/address와 동급 위험도

    # --- NER로 잡는 것 — 형식이 없는 값 ---
    "person",           # 이름
    "address",          # 주소
    "org",              # 조직명

    # --- 문서 자체의 위협 ---
    "injection",        # AI를 대상으로 한 지시문 (숨겨져 있지 않아도 해당)
    "hidden_text",      # 흰 글씨 / 0pt / 제로폭 / 숨긴 행·열 등 서식으로 감춰진 텍스트

    # --- 이미지(신분증) 전용 — CNN 파이프라인을 실제로 만들 때만 쓴다 ---
    # 아직 구현 확정 전이다. 자리만 잡아둔다.
    "id_photo",         # 얼굴 사진
    "signature",        # 서명 / 도장
    "id_meta",          # 발급일자 / 유효기간 / 신분증 종류
]

Source = Literal[
    "rule",        # 정규식 (+ 체크섬 검증)
    "ner",         # 한국어 NER 모델
    "classifier",  # 직접 학습한 분류기 (오탐 제거 / 인젝션)
    "format",      # 파일 서식 속성 검사 (색상, 폰트 크기, 숨김 속성)
    "cnn",         # 이미지 객체 탐지 (신분증 필드) — 구현 확정 전
]

RiskLevel = Literal["low", "medium", "high"]


# 유형 -> 화면에 쓰는 한국어 이름.
#
# 이 표가 여기 있는 이유: 마스킹 사본은 값을 `[주민등록번호]`처럼 **유형을 남겨서**
# 치환한다(`****`로 뭉개면 사본을 AI에 넣었을 때 문맥이 무너진다). 그런데 같은 이름을
# 화면(D)에서도 칩과 목록에 쓴다. 두 곳이 따로 문자열을 들고 있으면 사본에는
# "주민등록번호", 화면에는 "주민번호"라고 적히는 일이 생긴다. 여기서 한 번만 정의한다.
TYPE_LABELS: dict[str, str] = {
    "rrn": "주민등록번호",
    "passport": "여권번호",
    "driver_license": "운전면허번호",
    "foreign_reg": "외국인등록번호",
    "account": "계좌번호",
    "card": "카드번호",
    "api_key": "API 키",
    "db_credential": "DB 접속정보",
    "email": "이메일",
    "phone": "전화번호",
    "biz_reg": "사업자등록번호",
    "corp_reg": "법인등록번호",
    "ip": "IP 주소",
    "emp_no": "사번",
    "birth_date": "생년월일",
    "person": "이름",
    "address": "주소",
    "org": "조직명",
    "injection": "숨은 명령",
    "hidden_text": "숨겨진 텍스트",
    "id_photo": "얼굴 사진",
    "signature": "서명·도장",
    "id_meta": "신분증 정보",
}


def mask_placeholder(risk_type: str) -> str:
    """마스킹 사본에 넣을 치환 문자열. mask.py가 이것만 쓴다."""
    return f"[{TYPE_LABELS.get(risk_type, '민감정보')}]"


# 한글 라벨 -> RiskType 역매핑. TYPE_LABELS에서 자동 파생되므로 따로 관리할 필요 없다.
#
# 여기 있는 이유: 학습 데이터 라벨링(오탐 제거/인젝션 분류기용)을 한글 필드명으로
# 받는 경우가 있는데("계좌번호" 등), 그 값을 RiskType enum("account")으로 바꿔줄
# 곳이 마땅히 없었다. TYPE_LABELS를 뒤집기만 하면 되므로 여기 둔다. TYPE_LABELS에
# 새 타입을 추가하면 이 표에도 자동으로 반영된다 (직접 수정할 필요 없음).
LABEL_TO_TYPE: dict[str, str] = {label: risk_type for risk_type, label in TYPE_LABELS.items()}


# ---------------------------------------------------------------------------
# 위험 점수 산정 기준
# ---------------------------------------------------------------------------
#
# 세 가지 축으로 정했다. 발표에서 "왜 이 숫자냐"를 물으면 이 축으로 답한다.
#
#   1) 법적 등급     — 개인정보보호법상 고유식별정보인가
#   2) 복구 가능성   — 유출 후 되돌릴 수 있는가 (카드는 재발급, 주민번호는 불가)
#   3) 즉시 악용성   — 그 값 하나만으로 바로 피해가 발생하는가
#
# 절대적인 기준이 아니라 팀 내부 합의값이다. 중요한 건 정확한 숫자가 아니라
# 네 명이 같은 숫자를 쓰는 것이다.

RISK_WEIGHTS: dict[str, int] = {
    # 최상위 — 문서를 처리하는 순간 AI가 공격자 편에 서게 만든다.
    # 다른 항목은 "정보가 새는" 수동적 위험이지만 이것은 능동적 공격이다.
    "injection": 50,

    # 숨겨져 있다는 사실 자체는 "확인이 필요하다"는 신호이지 위험 자체가 아니다.
    # 정상 문서에도 숨은 텍스트는 있다 (메모, 편집 흔적, 서식 잔재).
    # 위험은 그 내용이 AI를 향한 명령일 때 생기고, 그때 injection으로 승격되어 50을
    # 받는다. 점수가 승격 구조를 그대로 반영하도록 한 단계 낮춰 잡는다.
    #
    # 주의: 한 문장을 hidden_text와 injection 두 개의 Finding으로 만들면 그 문장
    # 하나가 75점을 받는다. 타입은 **교체**하고, 어떻게 숨겨져 있었는지는
    # evidence에 남긴다. (화면 05가 그 evidence를 쓴다.)
    "hidden_text": 25,

    # 상위 — 복구 불가능하거나(고유식별정보), 유출 즉시 자동 악용된다(자격증명).
    # 앞의 네 개는 개인정보보호법상 고유식별정보다. "왜 이 넷만 40점이냐"에
    # 법 조문으로 답할 수 있다는 것이 이 등급의 근거다.
    "rrn": 40,
    "passport": 40,
    "driver_license": 40,
    "foreign_reg": 40,
    "api_key": 40,
    "db_credential": 40,

    # 중위 — 금전 피해로 직결되지만 재발급으로 복구 가능하다.
    "account": 30,
    "card": 30,

    # 하위 — 단독으로는 피해가 제한적이고, 결합될 때 위험해진다.
    # 덧셈 구조이므로 이름+전화+주소가 한 파일에 모이면 자연히 점수가 올라간다.
    # NER 기반이라 오탐이 가장 많이 나는 구간이기도 하므로 낮게 잡는다.
    "person": 10,
    "address": 10,
    "org": 10,
    "phone": 10,
    "email": 10,

    # 최하위 — 사업자등록번호·법인등록번호는 국세청에서 조회되는 공개 정보다.
    # 개인정보가 아니므로 잡되 점수는 거의 주지 않는다. IP도 같은 이유.
    "biz_reg": 5,
    "corp_reg": 5,
    "ip": 5,

    # 사번 — person/phone과 동급으로 취급한다. 단독 유출 시 피해가 제한적이지만
    # 조직명·이름과 결합되면 위험도가 올라가는 성격이 비슷하다.
    "emp_no": 10,
    "birth_date": 10,   # 단독 유출은 제한적, 이름/주소 등과 결합시 위험 - person급으로 취급

    # 이미지(신분증) — 신분증 사진 자체가 고유식별정보 덩어리다.
    "id_photo": 40,
    "signature": 30,
    "id_meta": 10,
}

# 위험도 색상 구간 — D가 카드 색을 정할 때 이 기준을 쓴다.
# 각자 다른 임계값을 쓰면 정렬과 색이 어긋나므로 여기서 한 번만 정의한다.
RISK_THRESHOLD_HIGH = 60.0
RISK_THRESHOLD_MEDIUM = 25.0


def _saturate_above_knee(total: float, knee: float = RISK_THRESHOLD_HIGH, cap: float = 100.0) -> float:
    """knee 이하는 그대로 두고, 그 위는 cap에 점근하도록 부드럽게 누른다.

    `min(cap, total)`로 잘랐을 때의 문제: RISK_WEIGHTS는 타입마다 따로 더해지므로
    서로 다른 고위험 타입 몇 개만 겹쳐도(injection 50 + api_key 40 + rrn 40 = 130)
    합계가 100을 가볍게 넘는다. 그러면 탐지 132건짜리 문서와 500건짜리 문서가
    똑같이 "100점"으로 나와, 배치 화면에서 위험도 순 정렬이 그 구간에서 무의미해진다
    (로그 감쇠는 같은 타입이 반복될 때만 완만해지게 하지, 서로 다른 타입이 겹치는
    경우는 애초에 다루지 않는다 — 위 docstring 참고).

    knee(=RISK_THRESHOLD_HIGH) 이하는 손대지 않는다 — "낮음/중간/높음" 등급
    경계와 RISK_WEIGHTS 주석의 가중치 근거가 전부 이 구간이 선형이라는 전제로
    적혀 있어서, 여기를 건드리면 그 근거들이 다시 검증돼야 한다. knee를 넘는
    구간만 지수함수로 늘어뜨려 cap에 다가가게 한다 — knee에서 값과 기울기가
    이어지고(연속), 아무리 커도 cap을 넘지 않으면서도 다시는 평평해지지 않는다.

        total=60(knee) -> 60.0 (경계, 이전과 동일)
        total=100      -> 85.3 (이전엔 100.0 — 여기서부터 차이가 생긴다)
        total=150      -> 95.8
        total=300      -> 99.9 (여전히 100 미만, 정렬 가능)
    """
    if total <= knee:
        return total
    return cap - (cap - knee) * math.exp(-(total - knee) / (cap - knee))


def compute_risk_score(findings: list["Finding"]) -> float:
    """탐지 항목 목록 -> 0~100 위험 점수.

    타입별로 묶어 (가중치 x 평균 확신도 x (1 + ln(개수)))를 더한 뒤,
    RISK_THRESHOLD_HIGH를 넘는 구간만 부드럽게 100에 점근시킨다(_saturate_above_knee).

    확신도를 곱하는 이유
        규칙 기반(confidence 1.0)은 점수에 그대로 반영되고, 불확실한
        NER/분류기 결과(0.6~0.8)는 점수를 덜 흔든다. 오탐 방어가 자동으로 된다.

    개수에 로그를 씌우는 이유
        단순 합산이면 같은 타입이 반복될 때 점수가 무한히 커진다. 이름만 40개
        들어 있는 회의록이 주민번호 12개짜리 고객명단과 똑같이 100점이 되어
        정렬이 무의미해진다. ln(1) = 0 이므로 1건짜리 항목은 전과 완전히
        동일하고, 반복될 때만 증가폭이 완만해진다.

        배수: 1건 x1.00 / 2건 x1.69 / 5건 x2.61 / 12건 x3.48 / 38건 x4.64
    """
    if not findings:
        return 0.0

    confidences_by_type: dict[str, list[float]] = defaultdict(list)
    for finding in findings:
        confidences_by_type[finding.type].append(finding.confidence)

    total = 0.0
    for risk_type, confidences in confidences_by_type.items():
        count = len(confidences)
        mean_confidence = sum(confidences) / count
        weight = RISK_WEIGHTS.get(risk_type, 10)
        total += weight * mean_confidence * (1 + math.log(count))

    return round(_saturate_above_knee(total), 1)


def risk_level(score: float) -> RiskLevel:
    if score >= RISK_THRESHOLD_HIGH:
        return "high"
    if score >= RISK_THRESHOLD_MEDIUM:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# 행동 가이드 — "탐지됐다"에서 "그래서 뭘 해야 하나"로 넘어가는 다리
# ---------------------------------------------------------------------------
#
# 결과 화면이 탐지 목록만 보여주면 사용자는 다음 행동을 스스로 판단해야 한다.
# ScanResult.finalize()가 findings를 여기로 돌려 우선 조치 최대 3개와 공유 전
# 체크리스트를 만들고, 그 결과를 ScanResult.action_guide에 채운다. 화면은 이
# 필드를 그대로 렌더링하기만 하면 되고, "어떤 유형이 왜 우선인가"를 판단하는
# 로직은 여기 한 곳에만 둔다 — 화면마다 따로 판단하면 결과 화면과 다운로드
# 안내가 다른 우선순위를 말하는 일이 생긴다.
#
# RISK_WEIGHTS보다 더 성긴 기준이다. 점수는 "얼마나 위험한가"를 매기지만, 조치는
# "무엇부터 해야 하는가"를 말한다. 예를 들어 account/card는 점수(30점)로는
# 고유식별정보(40점)보다 낮지만, 조치는 둘 다 "마스킹하고 전달 대상을 확인하라"로
# 비슷해서 별도 묶음(financial)으로 둔다.
_ACTION_GROUPS: dict[str, set[str]] = {
    # 능동적 공격. 점수표의 injection(50)·hidden_text(25)와 같은 묶음이다.
    "ai_command": {"injection", "hidden_text"},
    # 유출 즉시 자동 악용되고, 마스킹만으로는 끝나지 않는다(폐기·재발급이 필요).
    "credential": {"api_key", "db_credential"},
    # 되돌릴 수 없는 고유식별정보. 신분증 이미지 3종도 여기 속한다.
    "identity": {"rrn", "foreign_reg", "passport", "driver_license", "id_photo", "signature", "id_meta"},
    # 금전 피해로 직결되지만 재발급으로 복구 가능하다.
    "financial": {"account", "card"},
    # 단독으로는 위험이 제한적이고, 결합될 때 위험해진다.
    "contact": {"person", "phone", "email", "address", "birth_date", "emp_no"},
    # 공개 조회가 가능한 정보라 위험도는 낮다. 다른 조치가 이미 3개면 채우지 않는다.
    "organization": {"biz_reg", "corp_reg", "ip", "org"},
}

# RiskType 하나가 그룹 두 개에 들어가거나 하나도 없으면, 그 타입은 조치 안내
# 없이 조용히 "안전"으로 표시된다 — 신분증 사진에 조치 없음을 알려주는 것보다
# 나쁜 오답이다. 새 RiskType을 추가하고 여기 반영하는 걸 잊는 실수를 모듈
# 임포트 시점에 바로 잡는다(TYPE_LABELS가 RiskType 전체를 담은 권위 목록이다).
_action_group_types = [t for types in _ACTION_GROUPS.values() for t in types]
assert len(_action_group_types) == len(set(_action_group_types)), (
    "행동 가이드 그룹에 같은 RiskType이 두 번 들어감"
)
assert set(_action_group_types) == set(TYPE_LABELS), (
    "RiskType과 행동 가이드 그룹(_ACTION_GROUPS)이 어긋남: "
    f"빠진 타입 {set(TYPE_LABELS) - set(_action_group_types)}, "
    f"모르는 타입 {set(_action_group_types) - set(TYPE_LABELS)}"
)


def build_action_guide(findings: list["Finding"]) -> dict:
    """탐지 결과를 우선 조치 최대 3개 + 공유 전 체크리스트로 요약한다.

    ScanResult.action_guide로 나가는 값을 그대로 만든다. 우선순위는 능동적
    공격(ai_command) > 되돌릴 수 없는 노출(credential·identity) > 결합 위험
    (financial·contact) > 공개 정보(organization) 순으로, RISK_WEIGHTS가 점수를
    매기는 순서와 같다.
    """
    counts = {
        group: sum(1 for f in findings if f.type in types) for group, types in _ACTION_GROUPS.items()
    }

    actions: list[dict] = []
    if counts["ai_command"]:
        actions.append(
            {
                "key": "ai-command",
                "tone": "danger",
                "title": "AI 서비스 업로드를 잠시 중단하세요",
                "description": f"숨은 명령·Prompt Injection {counts['ai_command']}건을 먼저 확인하고 제거한 사본만 사용하세요.",
            }
        )
    if counts["credential"]:
        actions.append(
            {
                "key": "credential",
                "tone": "danger",
                "title": "노출된 인증정보를 폐기하고 재발급하세요",
                "description": f"API 키·DB 접속정보 {counts['credential']}건은 마스킹만으로 끝내지 말고 실제 사용 중인 값인지 확인하세요.",
            }
        )
    if counts["identity"]:
        actions.append(
            {
                "key": "identity",
                "tone": "warning",
                "title": "고유식별정보는 전체 마스킹하세요",
                "description": f"신분증·고유식별정보 {counts['identity']}건은 복구하기 어려운 정보이므로 원문 대신 마스킹 사본을 공유하세요.",
            }
        )
    if counts["financial"]:
        actions.append(
            {
                "key": "financial",
                "tone": "warning",
                "title": "금융정보의 전달 대상과 목적을 확인하세요",
                "description": f"계좌·카드정보 {counts['financial']}건은 필요한 수신자에게만 전달하고 나머지는 마스킹하세요.",
            }
        )
    if counts["contact"]:
        actions.append(
            {
                "key": "contact",
                "tone": "info",
                "title": "개인을 식별할 수 있는 정보는 최소화하세요",
                "description": f"이름·연락처·주소 등 {counts['contact']}건은 업무에 필요한 범위만 남기고 부분 또는 전체 마스킹하세요.",
            }
        )
    if counts["organization"] and len(actions) < 3:
        actions.append(
            {
                "key": "organization",
                "tone": "info",
                "title": "조직 정보의 공개 범위를 확인하세요",
                "description": f"조직·사업자·네트워크 정보 {counts['organization']}건이 외부 공개 가능한 내용인지 확인하세요.",
            }
        )

    if not actions:
        return {
            "title": "바로 공유할 수 있는 상태입니다",
            "description": "현재 검사에서 마스킹이 필요한 위험 요소를 찾지 못했습니다.",
            "actions": [],
            "checklist": [
                "수신자와 공유 범위가 맞는지 마지막으로 확인합니다.",
                "문서를 수정했다면 공유 전에 다시 검사합니다.",
                "공용 링크에는 만료 기간과 접근 권한을 설정합니다.",
            ],
        }

    # 체크리스트는 카드(actions)와 같은 우선순위로 앞에 붙인다. ai_command가
    # credential보다 항상 위에 오도록 순서를 명시한다(리스트 앞에 붙이는 방식은
    # 두 조건이 겹칠 때 순서가 뒤집히기 쉽다).
    checklist: list[str] = []
    if counts["ai_command"]:
        checklist.append("숨은 명령을 확인하기 전에는 문서를 AI 서비스에 업로드하지 않습니다.")
    if counts["credential"]:
        checklist.append("실제 사용 중인 키·비밀번호라면 즉시 폐기하고 새 값으로 교체합니다.")
    checklist += [
        "원본 대신 DocX-ray에서 만든 마스킹 사본을 공유합니다.",
        "수신자와 공유 목적을 확인하고 불필요한 항목은 제외합니다.",
        "공용 링크에는 만료 기간과 접근 권한을 설정합니다.",
    ]

    return {
        "title": "공유 전에 먼저 조치하세요"
        if (counts["ai_command"] or counts["credential"])
        else "안전하게 공유하려면 다음 조치가 필요합니다",
        "description": f"{len(findings)}건의 탐지 결과를 바탕으로 우선 조치를 정리했습니다.",
        "actions": actions[:3],
        "checklist": checklist,
    }


# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """탐지된 위험 요소 하나."""

    id: str                    # "f_001" — 프론트가 특정 항목을 지목할 때 쓴다 (제거 버튼 등)
    type: RiskType
    text: str                  # 탐지된 원문 조각
    start: int                 # raw_text 기준 시작 오프셋 (프론트 하이라이트용)
    end: int                   # raw_text 기준 끝 오프셋
    confidence: float          # 0.0 ~ 1.0
    source: Source
    reason: str                # XAI: 왜 위험한지 한 줄 (화면에 그대로 노출된다)
    page: Optional[int] = None

    # 마스킹 좌표. PDF 전용이고, (x0, y0, x1, y1) 페이지 좌표계다.
    #
    # 여기 있는 이유: PDF 마스킹은 PyMuPDF 리댁션으로 텍스트를 파일에서 실제로 지운다
    # (검은 박스로 덮기만 하면 복사·추출로 되살아난다). 리댁션은 좌표를 요구하는데,
    # 그 좌표는 이미 탐지할 때 get_texttrace()가 준 값이다. 마스킹 단계에서 다시
    # 찾으면 같은 글자가 여러 번 나올 때 엉뚱한 자리를 지운다. 탐지가 찾은 좌표를
    # 그대로 들고 내려간다.
    bbox: Optional[tuple[float, float, float, float]] = None

    evidence: dict = field(default_factory=dict)
    # evidence 예시 — 판정 근거의 원시 데이터. 화면에 근거를 보여줄 때 쓴다.
    #   서식 탐지: {"font_size": 1.0, "color": "#ffffff", "bg": "#ffffff"}
    #   렌더모드:  {"render_mode": 3}
    #   체크섬:    {"checksum": "pass"}
    #   분류기:    {"prob_positive": 0.93, "model": "fp_filter_v1"}
    #
    # 숨은 텍스트가 인젝션으로 승격될 때 (type이 hidden_text -> injection으로 바뀔 때)
    # 어떻게 숨겨져 있었는지는 evidence에 남긴다. type은 하나뿐이라 그것만으로는
    # "흰 글씨였다"는 정보가 사라진다. 화면 05가 그 정보를 보여준다.

    @property
    def weight(self) -> int:
        return RISK_WEIGHTS.get(self.type, 10)

    @property
    def label(self) -> str:
        """화면에 쓰는 한국어 이름."""
        return TYPE_LABELS.get(self.type, "민감정보")

    @property
    def placeholder(self) -> str:
        """마스킹 사본에서 이 값을 대체할 문자열."""
        return mask_placeholder(self.type)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label          # 화면이 유형명을 따로 들고 있지 않게 한다
        return d


@dataclass
class ScanResult:
    """파일 1개(또는 텍스트 1건)의 검사 결과."""

    # 파일 검사면 파일명, 훈련 모드의 답장 스캔(scan_text)이면 빈 문자열이다.
    filename: str = ""
    raw_text: str = ""         # 원문. findings의 오프셋은 전부 이 문자열 기준이다.
    findings: list[Finding] = field(default_factory=list)
    risk_score: float = 0.0    # 0 ~ 100. compute_risk_score()로 채운다.
    masked_text: str = ""      # 마스킹 사본. 하이라이트에는 쓰지 않는다 (오프셋이 어긋난다).
    error: Optional[str] = None

    # 검사는 정상적으로 끝났지만 범위가 줄었다는 사실을 사용자에게 밝혀야 할 때
    # 쓴다(예: 스캔본 PDF가 페이지 상한을 넘어 일부만 OCR했다, 고해상도 이미지를
    # 축소해서 분석했다, 텍스트가 커서 이름·회사명 탐지를 생략했다). error와
    # 다르다 — error는 "검사가 실패/저하됐다"라 action_guide를 지우지만, 이건
    # "검사는 끝났고 결과도 믿을 수 있는데, 그 범위를 알려야 한다"이므로
    # action_guide를 그대로 둔다. 화면은 이걸 옅은 안내(alert--info)로 보여준다.
    notice: Optional[str] = None

    # 애초에 검사 대상이 아닌 파일인가. error와 다르다 — error는 "검사하다 문제가
    # 생겼다"이고, 이건 "이 파일은 우리가 받는 종류가 아니다"이다(신분증이 아닌 이미지 등).
    #
    # 화면은 이 표시가 붙은 파일만 올라왔으면 결과 화면으로 넘어가지 않고 업로드
    # 화면에 안내를 띄운다. 점수 0은 초록불("안전")로 읽히는데, 검사도 안 한 파일에
    # 그 색을 붙이는 것이 이 서비스가 낼 수 있는 가장 위험한 오답이기 때문이다.
    unsupported: bool = False

    # 결과 화면 상단에 놓을 우선 조치 카드. finalize()가 build_action_guide()로
    # 채운다. error가 있으면 findings가 그 실패를 온전히 반영하지 못하므로(신분증
    # 품질 오류 등) None으로 두고, 화면은 오류 안내를 대신 보여준다.
    action_guide: Optional[dict] = None

    # 오탐 제거 분류기가 걸러낸 항목. **버리지 않고 여기 담는다.**
    #
    # 화면 03의 "오탐으로 제외한 항목" 카드가 이 목록을 그린다. 그 카드가 우리가
    # 직접 학습시킨 모델의 유일한 가시적 증거이고, "결국 LLM 래퍼 아니냐"는 질문에
    # 대한 답이다. 점수 계산에는 들어가지 않는다(compute_risk_score는 findings만 본다).
    filtered_out: list[Finding] = field(default_factory=list)

    # 다운로드용. 마스킹 사본은 텍스트가 아니라 **파일**로 돌려주는 것이 주 동작이다.
    # file_id는 GET /download/{file_id} 의 그 id다.
    file_id: str = ""
    file_type: str = ""              # "pdf" | "docx" | "xlsx" | "txt" | "md" | "image"
    masked_path: Optional[str] = None  # 서버 임시 경로. 응답 후 삭제된다. 화면에 노출 금지.

    # 쪽·시트 경계. 화면 미리보기를 쪽별로 나눌 때 쓴다(PDF는 쪽, XLSX는 시트, 그 외는 1쪽 하나).
    #   [{"page": 1, "start": 0, "end": 551, "label": "1쪽"}, ...]
    # start/end는 findings와 같은 raw_text 기준 오프셋이다. 파서의 page_map(글자마다 쪽 번호)을
    # scan.scan_file이 구간으로 묶어 채운다. 파일이 아닌 텍스트 검사(scan_text)는 빈 목록이다.
    pages: list[dict] = field(default_factory=list)

    # DB에 저장된 ScanResultRow.id. main.py의 _persist_scan_results()가 저장에
    # 성공했을 때만 채운다 — DB가 꺼져 있거나 저장이 실패하면 None으로 남는다.
    # 화면이 PATCH /scan-results/{db_id}/hidden-commands/{finding_ref}를 부를 때
    # 이 값이 필요하다. Finding.id(예: "f_003")는 이미 응답에 있으니 그대로 쓰면 된다.
    db_id: Optional[int] = None

    def finalize(self) -> "ScanResult":
        """findings를 다 채운 뒤 마지막에 한 번 호출한다. 점수와 행동 가이드를 채운다."""
        self.risk_score = compute_risk_score(self.findings)
        self.action_guide = build_action_guide(self.findings) if self.error is None else None
        return self

    @property
    def level(self) -> RiskLevel:
        return risk_level(self.risk_score)

    def by_type(self, *types: str) -> list[Finding]:
        """특정 타입만 걸러낸다. 숨은 명령 확인 팝업은 by_type('hidden_text', 'injection')."""
        return [f for f in self.findings if f.type in types]

    @property
    def has_hidden_command(self) -> bool:
        return bool(self.by_type("hidden_text", "injection"))

    @property
    def type_counts(self) -> dict[str, int]:
        """유형별 개수. 결과 카드의 칩("주민등록번호 3")이 이걸 쓴다."""
        counts: dict[str, int] = defaultdict(int)
        for f in self.findings:
            counts[f.type] += 1
        return dict(counts)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("masked_path", None)   # 서버 내부 경로다. 절대 밖으로 내보내지 않는다.
        # asdict()는 중첩된 Finding에 Finding.to_dict()를 쓰지 않는다(label이 빠진다).
        # 직접 갈아 끼운다.
        d["findings"] = [f.to_dict() for f in self.findings]
        d["filtered_out"] = [f.to_dict() for f in self.filtered_out]
        d["level"] = self.level
        d["has_hidden_command"] = self.has_hidden_command
        d["type_counts"] = self.type_counts
        d["filtered_count"] = len(self.filtered_out)
        return d


@dataclass
class ScanBatch:
    """파일 여러 개를 한 번에 올렸을 때의 결과 묶음.

    '파일 10개가 위험도 순으로 정렬되는 화면'이 이 구조를 쓴다.
    정렬은 서버(B)가 책임진다. 프론트가 각자 정렬하지 않는다.
    """

    results: list[ScanResult] = field(default_factory=list)
    batch_id: str = ""   # GET /download/all 이 쓰는 id. 사본 전체를 .zip으로 받을 때.

    def sorted_by_risk(self) -> list[ScanResult]:
        """위험도 내림차순. 동점이면 숨은 명령이 있는 파일을 앞으로 보낸다."""
        return sorted(
            self.results,
            key=lambda r: (r.risk_score, r.has_hidden_command),
            reverse=True,
        )

    @property
    def total_findings(self) -> int:
        return sum(len(r.findings) for r in self.results)

    @property
    def risk_level_counts(self) -> dict[str, int]:
        """파일이 몇 개씩 고/중/저위험인지. 배치 업로드 요약 카드("고위험 3개")가 쓴다.

        결과 화면이 파일마다 이미 쓰는 ScanResult.level을 그대로 세기만 한다 —
        여기서 등급을 다시 판정하면 개별 파일 카드와 다른 기준을 쓰게 될 위험이 있다.
        """
        counts = {"high": 0, "medium": 0, "low": 0}
        for r in self.results:
            counts[r.level] += 1
        return counts

    def top_risk_types(self, limit: int = 5) -> list[dict]:
        """배치 전체에서 가장 흔한 위험 유형. 파일별 type_counts를 그대로 더한다.

        예: 이름이 파일 A에 40건, 파일 B에 114건이면 154건으로 합쳐서 보여준다 —
        "이 배치는 주로 어떤 위험으로 차 있는가"를 파일 목록을 안 열어봐도 알 수 있다.
        """
        totals: dict[str, int] = defaultdict(int)
        for r in self.results:
            for risk_type, count in r.type_counts.items():
                totals[risk_type] += count
        ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]
        return [{"type": t, "label": TYPE_LABELS.get(t, "민감정보"), "count": c} for t, c in ranked]

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "results": [r.to_dict() for r in self.sorted_by_risk()],
            "total_files": len(self.results),
            "total_findings": self.total_findings,
            "risk_level_counts": self.risk_level_counts,
            "top_risk_types": self.top_risk_types(),
        }


# ---------------------------------------------------------------------------
# 진입점 (구현은 engine/scan.py)
# ---------------------------------------------------------------------------


def make_finding_id(index: int) -> str:
    """탐지 항목 id 생성. 한 ScanResult 안에서만 유일하면 된다."""
    return f"f_{index:03d}"


def scan_text(
    text: str,
    meta: dict | None = None,
    masking_policy: dict | None = None,
) -> ScanResult:
    """텍스트 1건을 검사한다.

    훈련 모드(C)의 실시간 답장 스캔이 이 함수를 직접 호출한다.
    meta에는 파서가 뽑은 서식 정보가 들어간다 (문자별 색상/폰트 크기 등).
    """
    raise NotImplementedError


def scan_file(
    path: str,
    masking_policy: dict | None = None,
    masking_selection: list[dict] | None = None,
    create_masked_copy: bool = True,
) -> ScanResult:
    """파일 1개를 파싱해서 검사한다."""
    raise NotImplementedError


def scan_files(
    paths: list[str],
    masking_policy: dict | None = None,
    create_masked_copy: bool = True,
) -> ScanBatch:
    """파일 여러 개를 검사하고 위험도 순으로 정렬해 돌려준다."""
    raise NotImplementedError
