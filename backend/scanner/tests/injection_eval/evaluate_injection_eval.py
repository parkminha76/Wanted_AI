"""B가 만든 인젝션 평가셋을 검사하고, 지금 스캐너가 그 위에서 얼마나 맞히는지 잰다.

이 폴더의 데이터는 **평가 전용**이다. 인젝션 학습 스크립트
(ml/training/injection_classifier/)는 sample_data/injection/injection_*.json만 읽으므로
여기 있는 파일은 학습에 섞이지 않는다. 섞이면 "독립 평가"가 아니게 되므로, 이 스크립트가
먼저 학습 데이터와 겹치는 문장이 없는지 확인한다.

두 가지를 따로 잰다.
  - 모델 단독: injection_classifier_v1.pkl의 확률만으로 판정했을 때
  - 스캐너 실제 동작: models.is_injection() — 모델 + 영문/고전 키워드 보조 판정 +
    INJECTION_THRESHOLD. 서비스에서 실제로 쓰는 판정은 이쪽이다.

실행(저장소 루트):
    uv run python backend/scanner/tests/injection_eval/evaluate_injection_eval.py
    # 파일 하나만: --eval backend/scanner/tests/injection_eval/injection_eval_B_0914_002.json

종료 코드: 스키마 오류(파일 사이 group_id 중복 포함)가 있거나 학습 데이터와 같은 문장이 있으면 1.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from backend.scanner.detectors import models  # noqa: E402

DEFAULT_EVAL = [
    Path(__file__).with_name("injection_eval_B_0914.json"),
    Path(__file__).with_name("injection_eval_B_0914_002.json"),
]
TRAIN_GLOB = str(REPO_ROOT / "sample_data" / "injection" / "injection_*.json")
REQUIRED = ("text", "label", "level", "source", "group_id")
MODEL_THRESHOLDS = (0.5, 0.6, 0.65, 0.7, 0.75)
# 이 값 이상이면 "거의 같은 문장"으로 보고 경고한다(글자 3개 묶음 기준 자카드 유사도).
NEAR_DUPLICATE_SIMILARITY = 0.8


def validate(rows: list[dict]) -> list[str]:
    errors = []
    for i, row in enumerate(rows):
        missing = [k for k in REQUIRED if k not in row]
        if missing:
            errors.append(f"{i}: 필수 키 누락 {missing}")
            continue
        if row["label"] not in (0, 1):
            errors.append(f"{i}: label은 0 또는 1")
        if row["level"] not in range(1, 6):
            errors.append(f"{i}: level은 1~5")
        if row["label"] == 1 and not row.get("attack_type"):
            errors.append(f"{i}: 공격 문장에는 attack_type 필요")
    return errors


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def _trigrams(text: str) -> set[str]:
    t = _normalize(text)
    return {t[i : i + 3] for i in range(max(1, len(t) - 2))}


def overlap_with_training(rows: list[dict]) -> dict:
    train = []
    for path in sorted(glob.glob(TRAIN_GLOB)):
        with open(path, encoding="utf-8") as fh:
            train += [r["text"] for r in json.load(fh)]
    train_exact = set(train)
    train_norm = {_normalize(t) for t in train}
    train_grams = [(t, _trigrams(t)) for t in train]

    exact = [r["text"] for r in rows if r["text"] in train_exact]
    normalized = [r["text"] for r in rows if _normalize(r["text"]) in train_norm]
    near = []
    for r in rows:
        grams = _trigrams(r["text"])
        best = max(
            ((len(grams & g) / len(grams | g), t) for t, g in train_grams if grams | g),
            default=(0.0, ""),
        )
        if best[0] >= NEAR_DUPLICATE_SIMILARITY:
            near.append((round(best[0], 3), r["text"], best[1]))
    return {"train_rows": len(train), "exact": exact, "normalized": normalized, "near": near}


def prf(labels: list[int], predicted: list[int]) -> tuple[float, float, float]:
    tp = sum(1 for y, p in zip(labels, predicted) if y == 1 and p == 1)
    fp = sum(1 for y, p in zip(labels, predicted) if y == 0 and p == 1)
    fn = sum(1 for y, p in zip(labels, predicted) if y == 1 and p == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def main() -> int:
    parser = argparse.ArgumentParser(description="B 인젝션 평가셋 검사·측정")
    parser.add_argument("--eval", type=Path, nargs="+", default=DEFAULT_EVAL,
                        help="평가 파일(여러 개면 합쳐서 잰다). 기본값은 1차·2차 전체")
    args = parser.parse_args()

    rows = []
    for path in args.eval:
        with path.open(encoding="utf-8") as fh:
            part = json.load(fh)
        print(f"  {path.name}: {len(part)}건")
        rows += part
    print(f"평가셋 {len(rows)}건 — {dict(Counter(r['label'] for r in rows))} (1=공격, 0=정상)")

    errors = validate(rows)
    group_ids = Counter(r.get("group_id") for r in rows)
    errors += [f"group_id 중복: {g}" for g, n in group_ids.items() if n > 1]
    print(f"[스키마] 오류 {len(errors)}건", errors[:5])

    ov = overlap_with_training(rows)
    print(
        f"[학습 데이터 {ov['train_rows']}건과 겹침] 완전 일치 {len(ov['exact'])} · "
        f"공백·기호 무시 일치 {len(ov['normalized'])} · 거의 같은 문장(≥{NEAR_DUPLICATE_SIMILARITY}) {len(ov['near'])}"
    )
    for sim, text, train_text in ov["near"][:5]:
        print(f"   {sim}  평가: {text}\n         학습: {train_text}")

    labels = [r["label"] for r in rows]

    model = models._get_injection_model()
    if model is None:
        print("[모델 단독] 인젝션 모델을 읽지 못해 건너뜀")
    else:
        probs = [model.predict_proba(r["text"]) for r in rows]
        print("[모델 단독] 임계값별")
        for th in MODEL_THRESHOLDS:
            p, r_, f = prf(labels, [int(x >= th) for x in probs])
            print(f"   {th:<5} 정밀도 {p:.3f}  재현율 {r_:.3f}  F1 {f:.3f}")

    verdicts = [models.is_injection(r["text"]) for r in rows]
    predicted = [int(hit) for hit, _ in verdicts]
    p, r_, f = prf(labels, predicted)
    print(
        f"[스캐너 실제 동작 — is_injection, 임계값 {models.INJECTION_THRESHOLD} + 키워드] "
        f"정밀도 {p:.3f}  재현율 {r_:.3f}  F1 {f:.3f}"
    )

    by_level = defaultdict(lambda: [0, 0])
    by_category = defaultdict(lambda: [0, 0])
    mistakes = []
    for row, pred, (_, conf) in zip(rows, predicted, verdicts):
        if row["label"] == 1:
            by_level[row["level"]][0] += pred
            by_level[row["level"]][1] += 1
        else:
            cat = row.get("category", "normal")
            by_category[cat][0] += pred
            by_category[cat][1] += 1
        if pred != row["label"]:
            kind = "놓침" if row["label"] == 1 else "오탐"
            mistakes.append((kind, round(conf, 3), row.get("category", ""), row["text"]))
    print("   공격 레벨별 탐지:", {lv: f"{h}/{n}" for lv, (h, n) in sorted(by_level.items())})
    print("   정상 종류별 오탐:", {c: f"{h}/{n}" for c, (h, n) in sorted(by_category.items())})
    for kind, conf, cat, text in mistakes:
        print(f"   {kind} {conf:<5} [{cat}] {text}")

    return 1 if errors or ov["exact"] or ov["normalized"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
