"""3개 후보 한국어 NER 모델을 로딩시간 + 추론속도 + 정확도 기준으로 비교한다.

ner.py에 어떤 모델을 쓸지 고르기 위한 일회성 벤치마크다. 모델 로딩은 배포
파이프라인에서 가장 오래 걸리고 리스크가 큰 작업이라(무거운 모델은 배포 서버에서
아예 못 뜨거나 첫 요청이 타임아웃날 수 있다), 통합하기 전에 미리 재본다.

1차 버전의 실수: `from transformers import pipeline`을 모델마다 반복 호출되는
_load_pipeline() 안에 넣어서, 첫 모델을 잴 때 transformers 자체를 초기화하는
고정 비용(~20초)이 로딩시간에 섞여 들어갔다. 세 모델이 다 20초 안팎으로 나와서
크기 차이(56MB vs 450MB대)가 전혀 안 보였다. transformers import를 파일 맨
위로 올려서 한 번만 내고, 그 다음부터 pipeline() 생성 시간만 잰다.

실행: uv run python -m backend.scanner.detectors.ner_benchmark
"""

from __future__ import annotations

import time

from transformers import pipeline as _hf_pipeline  # 무거운 초기화 비용을 한 번만 낸다

CANDIDATES = [
    "Leo97/KoELECTRA-small-v3-modu-ner",
    "KPF/KPF-bert-ner",
    "monologg/koelectra-base-v3-naver-ner",
    # 라벨이 NAME/ADDRESS/ORG로 우리가 필요한 세 종류와 정확히 일치해서 기대했지만,
    # 실측 결과 세 지표 모두 꼴찌라 탈락시켰다(2026-09-09 측정):
    #   로딩 29.7초(다른 셋은 2초 안팎) / 추론 197ms(small의 17.5배) / 커버리지 94.7%
    #   — 유일하게 100%를 못 맞췄다. 가중치도 1.3GB로 small 모델의 24배다.
    # 라벨이 맞아떨어지는 이점은 ner.py의 _TAG_TO_RISK_TYPE 3줄이면 해결되는
    # 문제라 애초에 큰 장점도 아니었다. 목록에 남겨두는 이유는 "4개를 실측 비교해서
    # 골랐다"는 근거를 남기기 위해서다. 처음 돌릴 때 1.3GB를 받는다.
    "vmaca123/korean-pii-ner-v3",
]

# 정답을 아는 문장 몇 개로 정확도를 가늠한다. 정식 성능 지표가 아니라 3개 모델을
# 상대 비교하기 위한 용도다 — 실제 발표용 Precision/Recall/F1은 ml/eval의 정식
# 평가셋으로 낸다.
SAMPLES: list[tuple[str, set[str]]] = [
    ("김민수 대표는 서울특별시 강남구 테헤란로에 있는 삼성전자 본사에서 발표했다.",
     {"김민수", "서울특별시", "강남구", "테헤란로", "삼성전자"}),
    ("네이버와 카카오는 각각 경기도 성남시에 사옥을 두고 있다.",
     {"네이버", "카카오", "경기도", "성남시"}),
    ("이지은 고객님의 주소는 부산광역시 해운대구입니다.",
     {"이지은", "부산광역시", "해운대구"}),
    ("박서준 팀장이 대전광역시 유성구에 있는 한국전자통신연구원 소속으로 이직했다.",
     {"박서준", "대전광역시", "유성구", "한국전자통신연구원"}),
    ("문의사항은 최유정 담당자에게 연락 주시고, 강원특별자치도 춘천시 지사로 방문해도 됩니다.",
     {"최유정", "강원특별자치도", "춘천시"}),
]

# 추론속도는 문장 5개를 이 횟수만큼 반복 실행해서 평균낸다. 한 번만 재면
# 캐시/JIT 흔들림 때문에 튄다.
INFERENCE_REPEATS = 5


def _load_pipeline(model_name: str):
    return _hf_pipeline("token-classification", model=model_name, aggregation_strategy="simple")


def _score_coverage(pipe, samples) -> float:
    """모델이 태그 이름을 뭐라고 부르든 상관없이, 정답 표면형을 개체로 잡아내긴
    하는지만 본다(entity_group 의미 해석은 모델마다 다를 수 있어서 여기선 안 본다).
    KPF-bert-ner처럼 라벨이 익명화된 모델은 이 값이 높아도 실제로는 쓸 수 없다 —
    "어떤 태그가 인물/기관/지명인지" 매핑표가 따로 있어야 하기 때문이다."""
    hit, total = 0, 0
    for text, expected in samples:
        found_words = {e["word"].replace(" ", "") for e in pipe(text)}
        total += len(expected)
        hit += sum(1 for exp in expected if any(exp in f or f in exp for f in found_words))
    return hit / total if total else 0.0


def _measure_inference_ms(pipe, samples) -> float:
    """문장 1개를 처리하는 데 걸리는 평균 시간(ms). 배포 후 요청마다 드는 비용이라
    로딩시간 못지않게 중요하다 — 로딩은 서버 뜰 때 한 번이지만 추론은 요청마다다."""
    texts = [text for text, _ in samples]
    start = time.perf_counter()
    for _ in range(INFERENCE_REPEATS):
        for text in texts:
            pipe(text)
    elapsed = time.perf_counter() - start
    return (elapsed / (INFERENCE_REPEATS * len(texts))) * 1000


def run() -> list[dict]:
    results = []
    for name in CANDIDATES:
        print(f"\n=== {name} ===")
        start = time.perf_counter()
        try:
            pipe = _load_pipeline(name)
        except Exception as exc:  # noqa: BLE001 - 벤치마크는 실패도 결과로 남겨야 한다
            print(f"로딩 실패: {exc}")
            results.append({"model": name, "load_seconds": None, "coverage": None, "inference_ms": None, "error": str(exc)})
            continue
        load_seconds = time.perf_counter() - start
        coverage = _score_coverage(pipe, SAMPLES)
        inference_ms = _measure_inference_ms(pipe, SAMPLES)
        print(
            f"로딩 시간: {load_seconds:.2f}초 | 문장당 추론시간: {inference_ms:.1f}ms | "
            f"개체 커버리지(근사): {coverage:.0%}"
        )
        results.append(
            {
                "model": name,
                "load_seconds": round(load_seconds, 2),
                "inference_ms": round(inference_ms, 1),
                "coverage": round(coverage, 3),
            }
        )
    return results


if __name__ == "__main__":
    summary = run()
    print("\n=== 요약 ===")
    for r in summary:
        print(r)
