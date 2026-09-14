"""합성 주소 200건에서 상세 주소 패턴의 exact-span 성능을 측정한다."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from address_pattern import find_address_spans


DEFAULT_DATA = Path("ml/eval/address_eval/address_cases.json")
DEFAULT_OUTPUT = Path("ml/eval/address_eval/address_pattern_metrics.json")


def overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def evaluate(rows: list[dict]) -> dict:
    counts = Counter(row["address_kind"] for row in rows)
    confusion = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    errors: list[dict] = []
    exact_span_hits = 0

    per_kind = {}
    for kind in sorted(counts):
        per_kind[kind] = {"rows": 0, "correct": 0, "errors": 0}

    for row in rows:
        expected = (row["start"], row["end"])
        predicted = find_address_spans(row["text"])
        exact = expected in predicted
        touches_candidate = any(overlaps(span, expected) for span in predicted)

        if row["label"] == 1:
            correct = exact
            confusion["tp" if correct else "fn"] += 1
            exact_span_hits += int(exact)
        else:
            correct = not touches_candidate
            confusion["tn" if correct else "fp"] += 1

        bucket = per_kind[row["address_kind"]]
        bucket["rows"] += 1
        bucket["correct" if correct else "errors"] += 1

        if not correct:
            errors.append(
                {
                    "kind": row["address_kind"],
                    "label": row["label"],
                    "expected": list(expected),
                    "predicted": [list(span) for span in predicted],
                    "text": row["text"],
                }
            )

    tp, fp, fn, tn = (
        confusion["tp"], confusion["fp"], confusion["fn"], confusion["tn"]
    )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(rows)

    for bucket in per_kind.values():
        bucket["accuracy"] = bucket["correct"] / bucket["rows"]

    return {
        "evaluation": "synthetic exact-span address pattern evaluation",
        "rows": len(rows),
        "distribution": dict(counts),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        "positive_exact_span_rate": exact_span_hits / (tp + fn),
        "confusion_matrix": confusion,
        "per_kind": per_kind,
        "errors": errors,
        "limitations": [
            "동일 생성기의 합성 데이터로 측정한 규칙 적합도이며 독립 실문서 성능이 아니다.",
            "B의 NER 결과 병합과 실제 문서 파서 오프셋은 별도 통합 테스트가 필요하다.",
            "제시된 정규식은 rules.py 반영 전 검토용 프로토타입이다.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="주소 정규식 프로토타입 평가")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = json.loads(args.data.read_text(encoding="utf-8"))
    metrics = evaluate(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cm = metrics["confusion_matrix"]
    print(
        f"rows={metrics['rows']} precision={metrics['precision']:.4f} "
        f"recall={metrics['recall']:.4f} f1={metrics['f1']:.4f} "
        f"exact_span={metrics['positive_exact_span_rate']:.4f}"
    )
    print(f"TP={cm['tp']} FP={cm['fp']} FN={cm['fn']} TN={cm['tn']}")
    print(f"오류 {len(metrics['errors'])}건 / 저장: {args.output}")


if __name__ == "__main__":
    main()

