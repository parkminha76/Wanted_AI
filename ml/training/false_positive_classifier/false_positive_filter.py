"""
오탐 제거 분류기 (False Positive Filter)
==========================================

목적: 정규식이 형식으로 찾은 후보가 "진짜 그 필드인지" vs "형태만 같은 다른 값
(오탐)인지"를 문맥으로 판별한다. 체크섬이 없는 필드(계좌번호, 운전면허번호)에서
특히 중요하고, 체크섬이 있는 필드에서도 이중 방어선 역할을 한다.

입력: 문장 + type(RiskType) + start/end(문장 안 값 위치, 필수)
출력: 0(오탐) / 1(진짜) 확률

담당: A. 학습 데이터는 B가 Faker로 생성해서 전달.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from scipy.sparse import hstack, csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import OneHotEncoder

from ml.training.false_positive_classifier.features import tokenize


# ---------------------------------------------------------------------------
# 데이터 로딩
# ---------------------------------------------------------------------------

def load_training_data(path: str) -> list[dict]:
    """B가 넘긴 JSON 로드. 요청 스펙(학습데이터_요청스펙_B_C.md) 형식 그대로.

    각 항목: {"text": ..., "type": ..., "label": 0/1, "start": int, "end": int}
    start/end는 요청 스펙 개정으로 필수가 됐다 — 문장에 후보가 여러 개 있을
    수 있어서, 값 위치를 명시하지 않으면 어떤 후보를 두고 하는 라벨인지
    알 수 없다.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        assert "text" in item and "type" in item and "label" in item, f"필수 키 누락: {item}"
        assert "start" in item and "end" in item, (
            f"start/end 누락 (필수 키): {item}. "
            "문장 안에서 값의 위치를 알아야 실제 체크섬 검증을 할 수 있다."
        )
    return data


def merge_json_files(paths: list[str]) -> list[dict]:
    """B가 여러 번 나눠서 보낸 파일들을 합친다."""
    merged = []
    for p in paths:
        merged.extend(load_training_data(p))
    return merged


# ---------------------------------------------------------------------------
# 체크섬 feature — validators.py 결과를 그대로 가져다 쓴다
# ---------------------------------------------------------------------------

def get_checksum_feature(text: str, risk_type: str, start: int, end: int) -> int:
    """체크섬 검증 가능한 타입이면 pass=1/fail=0, 검증 불가능한 타입이면 -1.

    text 전체가 아니라 text[start:end]로 잘라낸 실제 값만 validator에
    넘긴다. 문장 전체를 넘기면(예: "계좌번호 123-45-6789로 입금해주세요")
    validator가 하이픈/숫자 이외의 문자(공백, 한글) 때문에 자릿수 검증부터
    실패해서 항상 False가 나온다 — 체크섬 feature가 사실상 죽어있는
    상태였다.
    """
    from ml.data_generation.validators import (
        validate_biz_reg, validate_foreign_reg, validate_rrn, validate_card_luhn,
    )

    checkable = {
        "biz_reg": validate_biz_reg,
        "foreign_reg": validate_foreign_reg,
        "rrn": validate_rrn,
        "card": validate_card_luhn,
        # passport는 인쇄된 여권번호 자체엔 체크 디지트가 없어 등록하지 않는다
        # (validators.py의 "검증 불가능" 섹션 설명 참고). MRZ를 별도로 캡처해서
        # 검증하고 싶으면 validate_passport_mrz_check_digit()을 쓴다.
    }
    validator = checkable.get(risk_type)
    if validator is None:
        return -1  # 체크섬 없는 필드 (account, driver_license, emp_no, passport 등)

    value = text[start:end]
    return 1 if validator(value) else 0


def mask_candidate(text: str, start: int, end: int) -> str:
    """후보값은 체크섬 feature에 맡기고 텍스트 feature에서는 문맥만 남긴다."""
    if not 0 <= start < end <= len(text):
        raise ValueError(f"잘못된 start/end: {start}, {end}, text_length={len(text)}")
    return f"{text[:start]} __VALUE__ {text[end:]}"


# ---------------------------------------------------------------------------
# Feature 조립: TF-IDF(kiwi) + type 원-핫 + 체크섬
# ---------------------------------------------------------------------------

class FalsePositiveFilter:
    def __init__(self, *, c: float = 1.0):
        self.vectorizer = TfidfVectorizer(
            tokenizer=tokenize,
            token_pattern=None,
            ngram_range=(1, 2),
            min_df=1,
            sublinear_tf=True,
        )
        self.char_vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=2,
            max_features=20_000,
            sublinear_tf=True,
        )
        self.onehot = OneHotEncoder(handle_unknown="ignore")
        self.clf = LogisticRegression(
            C=c,
            max_iter=1000,
            class_weight="balanced",
            random_state=42,
        )
        self.c = c
        self.risk_types: list[str] = []

    def _build_features(self, texts: list[str], types: list[str], checksums: list[int], fit: bool):
        if fit:
            text_vec = self.vectorizer.fit_transform(texts)
            char_vec = self.char_vectorizer.fit_transform(texts)
            type_vec = self.onehot.fit_transform(np.array(types).reshape(-1, 1))
        else:
            text_vec = self.vectorizer.transform(texts)
            char_vec = self.char_vectorizer.transform(texts)
            type_vec = self.onehot.transform(np.array(types).reshape(-1, 1))

        checksum_vec = csr_matrix(np.array(checksums).reshape(-1, 1))
        return hstack([text_vec, char_vec, type_vec, checksum_vec])

    def fit(self, data: list[dict]) -> "FalsePositiveFilter":
        """전체 데이터로 모델을 학습한다. 성능 평가는 evaluate_group_cv를 쓴다."""
        return self.fit_final(data)

    def fit_final(self, data: list[dict]) -> "FalsePositiveFilter":
        """평가가 끝난 뒤 전달용 모델을 전체 데이터로 학습한다."""
        texts = [mask_candidate(d["text"], d["start"], d["end"]) for d in data]
        types = [d["type"] for d in data]
        labels = np.array([d["label"] for d in data])
        checksums = [
            get_checksum_feature(d["text"], d["type"], d["start"], d["end"])
            for d in data
        ]
        X = self._build_features(texts, types, checksums, fit=True)
        self.clf.fit(X, labels)
        self.risk_types = sorted(set(types))
        return self

    def predict_proba_many(self, data: list[dict]) -> np.ndarray:
        """평가용 일괄 추론. 각 항목에는 text/type/start/end가 필요하다."""
        texts = [mask_candidate(d["text"], d["start"], d["end"]) for d in data]
        types = [d["type"] for d in data]
        checksums = [
            get_checksum_feature(d["text"], d["type"], d["start"], d["end"])
            for d in data
        ]
        X = self._build_features(texts, types, checksums, fit=False)
        return self.clf.predict_proba(X)[:, 1]

    def predict_proba(self, text: str, risk_type: str, start: int, end: int) -> float:
        """진짜(label=1)일 확률. Finding.confidence에 그대로 넣는다.

        start/end는 스캐너 엔진(B)이 정규식으로 후보를 찾을 때 이미 알고
        있는 값이다 — Finding.start/end와 동일한 걸 그대로 넘기면 된다.
        체크섬 feature를 이 함수 내부에서 직접 계산하므로, 호출부가 미리
        pass/fail을 계산해서 넘길 필요가 없다(이전 버전과 달라진 점).
        """
        checksum = get_checksum_feature(text, risk_type, start, end)
        feature_text = mask_candidate(text, start, end)
        X = self._build_features([feature_text], [risk_type], [checksum], fit=False)
        return float(self.clf.predict_proba(X)[0][1])

    def save(self, path: str):
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: str) -> "FalsePositiveFilter":
        with open(path, "rb") as f:
            return pickle.load(f)


def evaluate_group_cv(
    data: list[dict], *, c: float, folds: int = 5, threshold: float = 0.5
) -> dict:
    """같은 문장 템플릿(group_id)이 학습/평가에 갈라지지 않게 평가한다."""
    labels = np.array([int(d["label"]) for d in data])
    groups = np.array([d.get("group_id", f"row_{i}") for i, d in enumerate(data)])
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=42)
    probabilities = np.zeros(len(data), dtype=float)

    for train_index, test_index in splitter.split(np.zeros(len(data)), labels, groups):
        model = FalsePositiveFilter(c=c).fit_final([data[i] for i in train_index])
        probabilities[test_index] = model.predict_proba_many([data[i] for i in test_index])

    predictions = (probabilities >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="binary", zero_division=0
    )
    report = classification_report(
        labels,
        predictions,
        target_names=["오탐(0)", "진짜(1)"],
        output_dict=True,
        zero_division=0,
    )
    return {
        "evaluation": f"{folds}-fold stratified group cross-validation",
        "c": c,
        "threshold": threshold,
        "rows": len(data),
        "groups": len(set(groups)),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "average_precision": float(average_precision_score(labels, probabilities)),
        "confusion_matrix": {
            "labels": [0, 1],
            "values": confusion_matrix(labels, predictions, labels=[0, 1]).tolist(),
        },
        "classification_report": report,
    }


# ---------------------------------------------------------------------------
# 실행 스크립트
# ---------------------------------------------------------------------------

def train_and_save() -> dict:
    """데이터 로드, 교차검증, 전체 재학습, 산출물 저장을 실행한다."""
    data_paths = sorted(Path("sample_data/false_positive").glob("false_positive_*.json"))
    if not data_paths:
        raise FileNotFoundError("sample_data/false_positive에 학습 JSON이 없습니다.")

    data = merge_json_files([str(path) for path in data_paths])
    print(f"학습 데이터 {len(data)}건 / 파일 {len(data_paths)}개 로드")

    candidates = [0.25, 0.5, 1.0, 2.0, 4.0]
    results = [evaluate_group_cv(data, c=c) for c in candidates]
    best = max(results, key=lambda result: (result["f1"], result["recall"]))
    print("C 탐색 결과:")
    for result in results:
        print(
            f"  C={result['c']:<4} precision={result['precision']:.4f} "
            f"recall={result['recall']:.4f} f1={result['f1']:.4f}"
        )

    model = FalsePositiveFilter(c=best["c"]).fit_final(data)
    model_path = Path("ml/models/fp_filter_v1.pkl")
    metrics_path = Path("ml/eval/false_positive_eval/fp_filter_v1_metrics.json")
    model_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(model_path))

    payload = {"selected": best, "candidates": results}
    with metrics_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    print(f"\nbest C={best['c']} / F1={best['f1']:.4f}")
    print(f"모델 저장: {model_path}")
    print(f"평가 저장: {metrics_path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(
        "pickle 모델의 패키지 경로를 보존하려면 "
        "`python -m ml.training.false_positive_classifier.train`으로 실행하세요."
    )
