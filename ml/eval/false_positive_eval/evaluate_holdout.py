"""별도 파일로 받은 오탐 제거 holdout 평가셋으로 저장 모델을 검증한다."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)

from ml.training.false_positive_classifier.false_positive_filter import (
    FalsePositiveFilter,
    merge_json_files,
)


MODEL_PATH = Path("ml/models/fp_filter_v1.pkl")
DATA_DIR = Path("sample_data/false_positive")
OUTPUT_PATH = Path("ml/eval/false_positive_eval/fp_filter_v1_holdout_metrics.json")


def metrics_at(labels: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict:
    predictions = (probabilities >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="binary", zero_division=0
    )
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    return {
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "false_negative_rate": float(fn / (fn + tp)) if fn + tp else 0.0,
        "confusion_matrix": {
            "labels": [0, 1],
            "values": [[int(tn), int(fp)], [int(fn), int(tp)]],
        },
    }


def main() -> None:
    eval_paths = sorted(DATA_DIR.glob("false_positive_eval_*.json"))
    train_paths = [
        path
        for path in sorted(DATA_DIR.glob("false_positive_*.json"))
        if "_eval_" not in path.stem.lower()
    ]
    if not eval_paths:
        raise FileNotFoundError("독립 평가셋이 없습니다: false_positive_eval_*.json")

    model = FalsePositiveFilter.load(str(MODEL_PATH))
    rows = [
        row
        for row in merge_json_files([str(path) for path in eval_paths])
        if row["type"] in model.risk_types
    ]
    labels = np.array([int(row["label"]) for row in rows])
    probabilities = model.predict_proba_many(rows)

    train_rows = merge_json_files([str(path) for path in train_paths])
    train_texts = {row["text"] for row in train_rows}
    train_groups = {row.get("group_id") for row in train_rows if row.get("group_id")}
    text_overlap = sum(row["text"] in train_texts for row in rows)
    group_overlap = sum(
        bool(row.get("group_id") and row["group_id"] in train_groups) for row in rows
    )

    per_type = {}
    types = np.array([row["type"] for row in rows])
    for risk_type in sorted(set(types)):
        selected = types == risk_type
        point = metrics_at(
            labels[selected], probabilities[selected], model.operating_threshold
        )
        point["rows"] = int(selected.sum())
        per_type[risk_type] = point

    payload = {
        "evaluation": "held-out wording set",
        "files": [path.name for path in eval_paths],
        "rows": len(rows),
        "label_distribution": dict(Counter(int(value) for value in labels)),
        "text_overlap_with_training": int(text_overlap),
        "group_overlap_with_training": int(group_overlap),
        "independence_warning": (
            "동일 문장은 없지만 학습셋과 같은 group_id 및 유사 문장 틀이 포함되어 "
            "완전 독립 평가셋으로 간주할 수 없다."
        ),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "average_precision": float(average_precision_score(labels, probabilities)),
        "default_point": metrics_at(labels, probabilities, 0.5),
        "operating_point": metrics_at(
            labels, probabilities, model.operating_threshold
        ),
        "per_type_at_operating_threshold": per_type,
        "classification_report_at_operating_threshold": classification_report(
            labels,
            probabilities >= model.operating_threshold,
            target_names=["오탐(0)", "진짜(1)"],
            output_dict=True,
            zero_division=0,
        ),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    point = payload["operating_point"]
    print(
        f"Holdout 평가 {len(rows)}건: F1={point['f1']:.4f} "
        f"precision={point['precision']:.4f} recall={point['recall']:.4f} "
        f"FNR={point['false_negative_rate']:.4f}"
    )
    print(
        f"ROC-AUC={payload['roc_auc']:.4f} "
        f"PR-AUC={payload['average_precision']:.4f} "
        f"텍스트/그룹 중복={text_overlap}/{group_overlap}"
    )
    print(f"평가 저장: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
