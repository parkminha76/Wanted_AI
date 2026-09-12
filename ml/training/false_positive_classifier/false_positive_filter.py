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
from kiwipiepy import Kiwi
from scipy.sparse import hstack, csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder

kiwi = Kiwi()


def tokenize(text: str) -> list[str]:
    """형태소 단위 토큰화. 명사/동사/형용사/외국어/숫자 위주로 필터링."""
    tokens = kiwi.tokenize(text)
    return [t.form for t in tokens if t.tag.startswith(("N", "V", "SL", "SN"))]


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


# ---------------------------------------------------------------------------
# Feature 조립: TF-IDF(kiwi) + type 원-핫 + 체크섬
# ---------------------------------------------------------------------------

class FalsePositiveFilter:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(
            tokenizer=tokenize,
            token_pattern=None,
            ngram_range=(1, 2),
            min_df=1,
        )
        self.onehot = OneHotEncoder(handle_unknown="ignore")
        self.clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        self.risk_types: list[str] = []

    def _build_features(self, texts: list[str], types: list[str], checksums: list[int], fit: bool):
        if fit:
            text_vec = self.vectorizer.fit_transform(texts)
            type_vec = self.onehot.fit_transform(np.array(types).reshape(-1, 1))
        else:
            text_vec = self.vectorizer.transform(texts)
            type_vec = self.onehot.transform(np.array(types).reshape(-1, 1))

        checksum_vec = csr_matrix(np.array(checksums).reshape(-1, 1))
        return hstack([text_vec, type_vec, checksum_vec])

    def fit(self, data: list[dict]):
        texts = [d["text"] for d in data]
        types = [d["type"] for d in data]
        labels = [d["label"] for d in data]
        checksums = [
            get_checksum_feature(d["text"], d["type"], d["start"], d["end"])
            for d in data
        ]

        X = self._build_features(texts, types, checksums, fit=True)
        y = np.array(labels)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        self.clf.fit(X_train, y_train)

        y_pred = self.clf.predict(X_test)
        print(classification_report(y_test, y_pred, target_names=["오탐(0)", "진짜(1)"]))

        precision, recall, f1, _ = precision_recall_fscore_support(
            y_test, y_pred, average="binary"
        )
        return {"precision": precision, "recall": recall, "f1": f1}

    def predict_proba(self, text: str, risk_type: str, start: int, end: int) -> float:
        """진짜(label=1)일 확률. Finding.confidence에 그대로 넣는다.

        start/end는 스캐너 엔진(B)이 정규식으로 후보를 찾을 때 이미 알고
        있는 값이다 — Finding.start/end와 동일한 걸 그대로 넘기면 된다.
        체크섬 feature를 이 함수 내부에서 직접 계산하므로, 호출부가 미리
        pass/fail을 계산해서 넘길 필요가 없다(이전 버전과 달라진 점).
        """
        checksum = get_checksum_feature(text, risk_type, start, end)
        X = self._build_features([text], [risk_type], [checksum], fit=False)
        return float(self.clf.predict_proba(X)[0][1])

    def save(self, path: str):
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: str) -> "FalsePositiveFilter":
        with open(path, "rb") as f:
            return pickle.load(f)


# ---------------------------------------------------------------------------
# 실행 스크립트
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    DATA_PATHS = [
        # "sample_data/false_positive/false_positive_B_0909.json",
        # B가 데이터 보낼 때마다 여기에 파일 경로 추가
    ]

    if not DATA_PATHS:
        print("아직 학습 데이터가 없습니다. DATA_PATHS에 B가 보낸 파일 경로를 추가하세요.")
    else:
        data = merge_json_files(DATA_PATHS)
        print(f"학습 데이터 {len(data)}건 로드")

        model = FalsePositiveFilter()
        metrics = model.fit(data)
        print(f"\n최종 성능: {metrics}")

        Path("ml/models").mkdir(parents=True, exist_ok=True)
        model.save("ml/models/fp_filter_v1.pkl")
        print("모델 저장 완료: ml/models/fp_filter_v1.pkl")