"""A가 학습시킨 분류기 2종 호출부.

붙어 있는 모델
    인젝션     ml/models/injection_classifier_v1.pkl
               학습 코드 ml/training/injection_classifier/ — C의 합성 공격 문장
               271건(그룹 209개)으로 학습. 그룹 분리 5-fold 교차검증 F1 0.883.
    오탐 제거   ml/models/fp_filter_v1.pkl
               학습 코드 ml/training/false_positive_classifier/ — 학습 데이터
               (sample_data/false_positive/, 298건)는 들어와 있지만 아직 학습 전이라
               파일이 없다. 파일이 생기면 코드 수정 없이 그대로 붙는다.

두 함수 모두 첫 호출 때 모델을 한 번만 읽고 캐싱한다. import 시점에 읽으면 모델
파일이 없는 환경에서 `import models` 자체가 실패해 scan.py 전체가 멎는다
(id_detector.py가 YOLO 가중치를 다루는 방식과 같다).

모델을 못 읽으면 그 사실을 기억해두고 다시 시도하지 않는다 — 문장마다 파일을
열려다 실패하면 문서 한 건에 수백 번 같은 예외가 난다.

시그니처는 9/9에 A와 합의해 고정한 것이다. 인젝션 쪽 threshold만 선택 인자로
덧붙였다(뒤에 붙는 키워드 인자라 기존 호출은 그대로 동작한다) — 호출하는 자리가
둘인데 필요한 동작점이 서로 다르기 때문이다. 아래 상수 설명 참고.
"""

from __future__ import annotations

import os

INJECTION_MODEL_PATH = os.path.join("ml", "models", "injection_classifier_v1.pkl")
FALSE_POSITIVE_MODEL_PATH = os.path.join("ml", "models", "fp_filter_v1.pkl")

# Finding.evidence["model"]에 남길 이름. backend/db/codes.py의 _KNOWN_MODELS가
# 허용하는 값과 글자 하나까지 같아야 한다 — 다르면 sanitize_evidence가 조용히
# 버려서 화면과 DB에 "어느 모델이 판정했는지"가 빈 채로 들어간다.
INJECTION_MODEL_NAME = "injection_classifier_v1"
FALSE_POSITIVE_MODEL_NAME = "fp_filter_v1"


# ---------------------------------------------------------------------------
# 인젝션
# ---------------------------------------------------------------------------

# 문서 전체를 문장 단위로 훑을 때(scan.py의 _find_injections) 쓰는 임계값.
#
# 모델 기본값은 0.5지만 그 값은 공격 문장과 정상 문장이 반반인 학습 데이터에서
# 정해진 것이다. 실제 문서는 문장 수백 개 중 인젝션이 0~2건이라 사정이 다르다.
#
# 0.65인 근거(backend/scanner/tests/의 문서 30건, 문장 137개 실측, 2026-09-12):
#     0.5  -> 56건 탐지 중 38건이 오탐(전체 문장의 40.9%). "계좌: 110-234-567890"
#             (0.588), "Contact: 010-1234-5678"(0.535) 같은 평범한 문장이 걸린다.
#     0.65 -> 실제 인젝션 18건을 모두 잡고 오탐 0건.
# 실제 인젝션의 확률은 0.688~0.950, 평문 최고값은 0.632라 그 사이가 비어 있다.
# C의 학습 데이터 교차검증으로도 0.65에서 정밀도 0.957(재현율 0.652)이다.
#
# 재현율을 내주고 정밀도를 사는 이유: 오탐 1건이 50점짜리 빨간 항목으로 올라가고,
# 마스킹 사본에서는 그 문장이 통째로 [숨은 명령]으로 덮여 멀쩡한 본문이 사라진다.
INJECTION_THRESHOLD = 0.65

# 이미 "숨겨져 있다"고 판정된 텍스트를 승격할 때(scan.py의 _promote_hidden_injections)
# 쓰는 임계값. 이쪽은 모델 기본값을 그대로 둔다 — 일부러 숨긴 문장은 애초에 인젝션일
# 사전확률이 훨씬 높고, 여기서 놓쳐도 탐지가 사라지는 게 아니라 hidden_text(25점)로
# 남을 뿐이다. 문서 전체 스캔과 달리 오탐 비용이 작아서 재현율을 택한다.
HIDDEN_TEXT_INJECTION_THRESHOLD = 0.5

# 모델을 못 읽었을 때의 최소 방어선이자, 모델이 있을 때도 함께 보는 보조 판정.
# 인젝션 모델의 학습 데이터는 전부 한국어라 영문 인젝션은 학습 범위 밖이다
# (ml/training/injection_classifier/README.md가 "영문 키워드 fallback은 백엔드
# 통합 시 별도로 유지한다"고 명시).
_INJECTION_KEYWORDS = (
    "무시하고",
    "이전 지시",
    "시스템 프롬프트",
    "역할을 무시",
    "ignore previous",
    "system prompt",
)

# 키워드로만 잡았을 때 쓰는 확신도. rules.py에서 "알려진 API 키 접두어"에 주는 값과
# 같은 등급이다 — 문자열이 정확히 일치했을 뿐 계산으로 증명된 건 아니라 1.0은 쓰지
# 않는다(1.0은 체크섬을 통과한 값에만 준다).
_KEYWORD_CONFIDENCE = 0.9

_injection_model = None
_injection_model_unavailable = False


def _get_injection_model():
    global _injection_model, _injection_model_unavailable
    if _injection_model is not None or _injection_model_unavailable:
        return _injection_model
    try:
        from ml.training.injection_classifier import InjectionClassifier

        _injection_model = InjectionClassifier.load(INJECTION_MODEL_PATH)
    except Exception:
        # 파일 없음(FileNotFoundError), sklearn 미설치(ImportError), pickle 형식
        # 불일치(ValueError/UnpicklingError)가 모두 여기로 온다. 원인이 무엇이든
        # 결론은 하나다 — 키워드로 돌린다. 그래서 예외 종류를 나누지 않는다.
        _injection_model_unavailable = True
    return _injection_model


def injection_model_ready() -> bool:
    """인젝션 모델이 실제로 올라왔는지. 호출부가 evidence에 모델 이름을 남길지
    정하는 데 쓴다 — 모델이 없어 키워드로 판정했는데 모델 이름을 적으면 거짓말이 된다."""
    return _get_injection_model() is not None


def is_injection(sentence, *, threshold: float | None = None) -> tuple[bool, float]:
    """이 문장이 AI에게 내리는 명령인가? 반환: (명령이면 True, 확신도 0~1)

    확신도는 모델이 매긴 인젝션일 확률(label=1)이다. 키워드로만 잡은 경우에는
    _KEYWORD_CONFIDENCE를 돌려준다.

    threshold를 주지 않으면 INJECTION_THRESHOLD를 쓴다.
    """
    if not isinstance(sentence, str) or not sentence.strip():
        return (False, 0.0)

    lowered = sentence.lower()
    keyword_hit = any(keyword.lower() in lowered for keyword in _INJECTION_KEYWORDS)

    model = _get_injection_model()
    if model is None:
        return (keyword_hit, _KEYWORD_CONFIDENCE if keyword_hit else 0.0)

    probability = round(model.predict_proba(sentence), 3)
    limit = INJECTION_THRESHOLD if threshold is None else threshold
    if probability >= limit:
        return (True, probability)
    # 모델이 넘기지 못한 문장이라도 알려진 공격 문구가 그대로 들어 있으면 잡는다.
    # 영문 인젝션이 여기로 온다.
    if keyword_hit:
        return (True, _KEYWORD_CONFIDENCE)
    return (False, probability)


# ---------------------------------------------------------------------------
# 오탐 제거
# ---------------------------------------------------------------------------

# 이 값 이상이면 "진짜 개인정보"로 본다. 학습 코드가 쓰는 기본값과 같다.
FALSE_POSITIVE_THRESHOLD = 0.5

_false_positive_model = None
_false_positive_model_unavailable = False


def _get_false_positive_model():
    global _false_positive_model, _false_positive_model_unavailable
    if _false_positive_model is not None or _false_positive_model_unavailable:
        return _false_positive_model
    try:
        from ml.training.false_positive_classifier.false_positive_filter import (
            FalsePositiveFilter,
        )

        _false_positive_model = FalsePositiveFilter.load(FALSE_POSITIVE_MODEL_PATH)
    except Exception:
        _false_positive_model_unavailable = True
    return _false_positive_model


def false_positive_model_ready() -> bool:
    """오탐 제거 모델이 실제로 올라왔는지. 아직 학습 전이라 지금은 항상 False다."""
    return _get_false_positive_model() is not None


def filter_false_positive(text, context, risk_type) -> tuple[bool, float]:
    """이 값이 진짜 개인정보인가? 반환: (진짜면 True, 진짜일 확률 0~1)

    text     탐지된 값 자체. 예: "512-55-9401-22268"
    context  그 값이 들어 있는 **문장 전체**(값을 포함한다).
             예: "입금 계좌는 512-55-9401-22268입니다. 확인 후 송금 부탁드립니다"

    context에 값 뒷부분까지 담는 이유: 학습 데이터(sample_data/false_positive/,
    298건)를 재보니 값 앞 평균 8.2자, **뒤 평균 11.7자**였다. "입니다. 확인 후 송금
    부탁드립니다"나 "기준으로 발급됩니다"처럼 계좌번호와 사번을 가르는 단서가 값
    뒤쪽에 몰려 있어서, 앞쪽만 넘기면 판단 근거의 절반을 버리게 된다.

    두 번째 값 0~1은 "진짜일 확률"이다. "판정에 대한 확신"이 아니다 — 뜻이 하나여야
    호출하는 쪽에서 뒤집는 계산이 사라진다.

    모델 파일이 아직 없으면 (True, 1.0)을 돌려준다 = 전부 통과.
    """
    model = _get_false_positive_model()
    if model is None:
        return (True, 1.0)

    # 호출부가 문장을 못 찾아 값만 넘겼을 때를 대비한다(값이 문장 경계를 넘어간 경우).
    sentence = context if text and text in context else f"{context}{text}"
    start = sentence.find(text)
    if start < 0:
        start = 0
    end = start + len(text)

    probability = round(float(model.predict_proba(sentence, risk_type, start, end)), 3)
    return (probability >= FALSE_POSITIVE_THRESHOLD, probability)
