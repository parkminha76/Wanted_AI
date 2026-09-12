"""한국어 프롬프트 인젝션 분류기 학습 및 추론.

검사 대상 문장에서 AI의 지시를 바꾸거나 정보 유출·안전장치 우회를
유도하는 명령(label=1)과 일반 문서 문장(label=0)을 구분한다.

학습 feature에는 실제 추론 시 제공되는 ``text``만 사용한다. ``source``,
``attack_type``, ``level``은 데이터 점검과 세부 평가에만 사용한다.
"""

from __future__ import annotations

import argparse
import json
import pickle
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
from sklearn.pipeline import FeatureUnion, Pipeline


MODEL_FORMAT_VERSION = 1
DEFAULT_THRESHOLD = 0.5
REQUIRED_FIELDS = frozenset({"text", "label", "level", "source", "group_id"})


def load_training_data(paths: Iterable[str | Path]) -> list[dict]:
    """여러 JSON 배열을 합치고 스키마와 라벨 충돌을 검증한다."""
    rows: list[dict] = []
    for raw_path in paths:
        path = Path(raw_path)
        with path.open(encoding="utf-8") as file:
            batch = json.load(file)
        if not isinstance(batch, list):
            raise ValueError(f"JSON 최상위 값은 배열이어야 함: {path}")
        for index, item in enumerate(batch):
            _validate_item(item, path, index)
            rows.append(item)

    if not rows:
        raise ValueError("학습 데이터가 비어 있음")

    labels = {row["label"] for row in rows}
    if labels != {0, 1}:
        raise ValueError(f"label 0과 1이 모두 필요함: 현재 {sorted(labels)}")

    text_labels: dict[str, int] = {}
    for row in rows:
        previous = text_labels.setdefault(row["text"], row["label"])
        if previous != row["label"]:
            raise ValueError(f"동일 문장에 상충하는 label이 있음: {row['text']!r}")
    return rows


def _validate_item(item: object, path: Path, index: int) -> None:
    prefix = f"{path}:{index}"
    if not isinstance(item, dict):
        raise ValueError(f"{prefix}: 각 항목은 JSON 객체여야 함")
    missing = REQUIRED_FIELDS - item.keys()
    if missing:
        raise ValueError(f"{prefix}: 필수 키 누락 {sorted(missing)}")
    if not isinstance(item["text"], str) or not item["text"].strip():
        raise ValueError(f"{prefix}: text는 비어 있지 않은 문자열이어야 함")
    if type(item["label"]) is not int or item["label"] not in (0, 1):
        raise ValueError(f"{prefix}: label은 정수 0 또는 1이어야 함")
    if type(item["level"]) is not int or item["level"] not in range(1, 6):
        raise ValueError(f"{prefix}: level은 정수 1~5여야 함")
    if not isinstance(item["source"], str) or not item["source"].strip():
        raise ValueError(f"{prefix}: source는 비어 있지 않은 문자열이어야 함")
    if not isinstance(item["group_id"], str) or not item["group_id"].strip():
        raise ValueError(f"{prefix}: group_id는 비어 있지 않은 문자열이어야 함")
    if item["label"] == 1 and (
        not isinstance(item.get("attack_type"), str) or not item["attack_type"].strip()
    ):
        raise ValueError(f"{prefix}: 공격 문장에는 attack_type이 필요함")


def build_pipeline() -> Pipeline:
    """한국어 띄어쓰기와 표현 변형을 함께 잡는 word+character TF-IDF 모델."""
    features = FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    min_df=2,
                    max_df=0.98,
                    sublinear_tf=True,
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=2,
                    max_features=30000,
                    sublinear_tf=True,
                ),
            ),
        ]
    )
    classifier = LogisticRegression(
        C=2.0,
        class_weight="balanced",
        max_iter=2000,
        random_state=42,
    )
    return Pipeline([("features", features), ("classifier", classifier)])


class InjectionClassifier:
    """문장 단위 이진 분류기. 반환 확률은 label=1(인젝션) 기준이다."""

    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        if not 0.0 < threshold < 1.0:
            raise ValueError("threshold는 0과 1 사이여야 함")
        self.threshold = threshold
        self.pipeline = build_pipeline()
        self.metadata: dict = {}

    def fit(self, rows: Sequence[dict]) -> "InjectionClassifier":
        texts = [row["text"] for row in rows]
        labels = np.asarray([row["label"] for row in rows], dtype=int)
        self.pipeline.fit(texts, labels)
        self.metadata = {
            "training_rows": len(rows),
            "label_counts": dict(Counter(int(label) for label in labels)),
            "levels": sorted({row["level"] for row in rows}),
        }
        return self

    def predict_proba(self, text: str) -> float:
        if not isinstance(text, str) or not text.strip():
            return 0.0
        return float(self.pipeline.predict_proba([text])[0, 1])

    def predict(self, text: str) -> tuple[bool, float]:
        probability = self.predict_proba(text)
        return probability >= self.threshold, probability

    def save(self, path: str | Path) -> None:
        """신뢰하는 로컬 모델 경로에만 저장한다. pickle은 외부 파일에 사용 금지."""
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": MODEL_FORMAT_VERSION,
            "threshold": self.threshold,
            "pipeline": self.pipeline,
            "metadata": self.metadata,
        }
        with output.open("wb") as file:
            pickle.dump(payload, file, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str | Path) -> "InjectionClassifier":
        with Path(path).open("rb") as file:
            payload = pickle.load(file)
        if payload.get("format_version") != MODEL_FORMAT_VERSION:
            raise ValueError("지원하지 않는 인젝션 모델 형식")
        model = cls(threshold=float(payload["threshold"]))
        model.pipeline = payload["pipeline"]
        model.metadata = payload.get("metadata", {})
        return model


def evaluate(rows: Sequence[dict], threshold: float = DEFAULT_THRESHOLD) -> dict:
    """같은 group_id가 train/test에 갈라지지 않는 5-fold 교차검증."""
    texts = np.asarray([row["text"] for row in rows], dtype=object)
    labels = np.asarray([row["label"] for row in rows], dtype=int)
    groups = np.asarray([row["group_id"] for row in rows], dtype=object)
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    probabilities = cross_val_predict(
        build_pipeline(),
        texts,
        labels,
        groups=groups,
        cv=cv,
        method="predict_proba",
        n_jobs=None,
    )[:, 1]
    predictions = (probabilities >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="binary", zero_division=0
    )
    matrix = confusion_matrix(labels, predictions).tolist()

    per_level = {}
    for level in sorted({row["level"] for row in rows}):
        mask = np.asarray([row["level"] == level for row in rows])
        p, r, level_f1, _ = precision_recall_fscore_support(
            labels[mask], predictions[mask], average="binary", zero_division=0
        )
        per_level[str(level)] = {
            "rows": int(mask.sum()),
            "precision": float(p),
            "recall": float(r),
            "f1": float(level_f1),
        }

    report = {
        "evaluation": "5-fold stratified group cross-validation",
        "threshold": threshold,
        "rows": len(rows),
        "groups": len(set(groups)),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "average_precision": float(average_precision_score(labels, probabilities)),
        "confusion_matrix": {"labels": [0, 1], "values": matrix},
        "per_level": per_level,
        "classification_report": classification_report(
            labels,
            predictions,
            target_names=["정상(0)", "인젝션(1)"],
            output_dict=True,
            zero_division=0,
        ),
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="InfoGuard 인젝션 분류기 학습")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("sample_data/injection"),
        help="injection_*.json 파일이 있는 폴더",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ml/models/injection_classifier_v1.pkl"),
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=Path("ml/eval/injection_eval/injection_classifier_v1_metrics.json"),
    )
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = sorted(args.data_dir.glob("injection_*.json"))
    if not paths:
        raise SystemExit(f"학습 데이터가 없음: {args.data_dir}")

    rows = load_training_data(paths)
    print(f"학습 데이터 {len(rows)}건 / 그룹 {len({r['group_id'] for r in rows})}개")
    print(f"라벨 분포: {dict(Counter(r['label'] for r in rows))}")

    metrics = evaluate(rows, threshold=args.threshold)
    print(
        "교차검증 성능: "
        f"precision={metrics['precision']:.4f} "
        f"recall={metrics['recall']:.4f} "
        f"f1={metrics['f1']:.4f} "
        f"roc_auc={metrics['roc_auc']:.4f}"
    )

    model = InjectionClassifier(threshold=args.threshold).fit(rows)
    model.metadata["evaluation"] = {
        key: metrics[key]
        for key in ("precision", "recall", "f1", "roc_auc", "average_precision")
    }
    model.save(args.output)

    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"모델 저장: {args.output}")
    print(f"평가 저장: {args.metrics_output}")


if __name__ == "__main__":
    main()
