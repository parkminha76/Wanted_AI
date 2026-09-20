"""`Leo97/KoELECTRA-small-v3-modu-ner`를 짧은 맥락(CSV 행·목록·표 셀) 이름·회사명
인식으로 파인튜닝한다. GPU 필요 — CPU로는 현실적인 시간 안에 못 돈다.

generate_ner_data.py가 만든 (text, entities) JSONL을 읽어, 문자 오프셋을
KoELECTRA 서브워드 토큰에 맞춰 BIO 라벨로 바꾼 뒤 HuggingFace Trainer로
이어서 학습(continued fine-tuning)한다. 기존 라벨 체계(id2label 31개)를 그대로
쓴다 — 새 분류head를 만들지 않고 이어서 학습해야, 모델이 원래 잘하던 자연스러운
문장에서의 인식 능력을 최대한 유지한다(생성 데이터에도 자연스러운 문장을
일부 섞어 둔 것과 같은 이유).

실행 (GPU 파드에서):
    uv run python -m ml.training.ner_finetune.train_ner
    또는: python3 ml/training/ner_finetune/train_ner.py

출력:
    ml/models/ner_person_org_v1/           파인튜닝된 모델(토크나이저 포함)
    ml/eval/ner_eval/ner_person_org_v1_metrics.json   검증셋 성능
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from datasets import Dataset
from seqeval.metrics import classification_report, f1_score, precision_score, recall_score
from transformers import (
    AutoModelForTokenClassification,
    AutoTokenizer,
    DataCollatorForTokenClassification,
    Trainer,
    TrainingArguments,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(__file__).resolve().parent / "data"
MODEL_NAME = "Leo97/KoELECTRA-small-v3-modu-ner"
OUTPUT_MODEL_DIR = REPO_ROOT / "ml" / "models" / "ner_person_org_v1"
EVAL_DIR = REPO_ROOT / "ml" / "eval" / "ner_eval"

# 우리가 다루는 라벨만 좁혀서 본다 — 나머지(FD/TR/AF/LC/CV/DT/TI/QT/EV/AM/PT/MT/TM)는
# 이번 데이터에 없으므로 건드리지 않는다(원래 가중치를 그대로 둔다).
_TARGET_ENTITY_LABELS = {"PS", "OG"}


def _load_jsonl(path: Path) -> list[dict]:
    examples = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            examples.append(json.loads(line))
    return examples


def _char_spans_to_bio(offsets, entities, label2id) -> list[int]:
    """토크나이저의 offset_mapping(서브워드별 (char_start, char_end))과 문자
    단위 entity 목록을 받아 서브워드마다 하나씩 라벨 id를 만든다.

    서브워드가 엔티티 구간과 조금이라도 겹치면 그 엔티티에 속한 것으로 본다.
    엔티티의 첫 서브워드는 B-, 그 다음은 I-를 붙인다. special token(offset이
    (0,0))은 -100으로 둬서 손실 계산에서 빠진다(HF 관례).
    """
    labels = [-100] * len(offsets)
    for idx, (start, end) in enumerate(offsets):
        if start == end:
            continue  # special token
        labels[idx] = label2id["O"]

    for start, end, entity_label in entities:
        if entity_label not in _TARGET_ENTITY_LABELS:
            continue
        first = True
        for idx, (tok_start, tok_end) in enumerate(offsets):
            if tok_start == tok_end:
                continue
            if tok_end <= start or tok_start >= end:
                continue
            prefix = "B-" if first else "I-"
            labels[idx] = label2id[f"{prefix}{entity_label}"]
            first = False
    return labels


def build_dataset(examples: list[dict], tokenizer, label2id) -> Dataset:
    texts = [example["text"] for example in examples]
    tokenized = tokenizer(
        texts, truncation=True, max_length=128, return_offsets_mapping=True
    )
    all_labels = []
    for i, example in enumerate(examples):
        offsets = tokenized["offset_mapping"][i]
        all_labels.append(_char_spans_to_bio(offsets, example["entities"], label2id))
    tokenized["labels"] = all_labels
    tokenized.pop("offset_mapping")
    return Dataset.from_dict(tokenized)


def main() -> None:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForTokenClassification.from_pretrained(MODEL_NAME)
    label2id = model.config.label2id
    id2label = model.config.id2label

    train_examples = _load_jsonl(DATA_DIR / "train.jsonl")
    val_examples = _load_jsonl(DATA_DIR / "val.jsonl")
    print(f"train={len(train_examples)} val={len(val_examples)}")

    train_dataset = build_dataset(train_examples, tokenizer, label2id)
    val_dataset = build_dataset(val_examples, tokenizer, label2id)

    collator = DataCollatorForTokenClassification(tokenizer)

    def compute_metrics(eval_pred):
        predictions, labels = eval_pred
        predictions = np.argmax(predictions, axis=2)

        true_labels = [
            [id2label[l] for l in label_row if l != -100]
            for label_row in labels
        ]
        true_predictions = [
            [id2label[p] for p, l in zip(pred_row, label_row) if l != -100]
            for pred_row, label_row in zip(predictions, labels)
        ]
        return {
            "precision": precision_score(true_labels, true_predictions),
            "recall": recall_score(true_labels, true_predictions),
            "f1": f1_score(true_labels, true_predictions),
        }

    args = TrainingArguments(
        output_dir=str(REPO_ROOT / "ml" / "training" / "ner_finetune" / "_run"),
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        learning_rate=3e-5,
        per_device_train_batch_size=32,
        per_device_eval_batch_size=64,
        num_train_epochs=6,
        weight_decay=0.01,
        logging_steps=20,
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=collator,
        compute_metrics=compute_metrics,
    )

    trainer.train()
    metrics = trainer.evaluate()
    print("최종 검증 지표:", metrics)

    # 서브워드 단위 classification_report도 같이 남긴다 — precision/recall/f1
    # 숫자만으로는 "PS는 잘하는데 OG가 약하다" 같은 유형별 차이를 못 본다.
    predictions, labels, _ = trainer.predict(val_dataset)
    predictions = np.argmax(predictions, axis=2)
    true_labels = [[id2label[l] for l in row if l != -100] for row in labels]
    true_predictions = [
        [id2label[p] for p, l in zip(pred_row, label_row) if l != -100]
        for pred_row, label_row in zip(predictions, labels)
    ]
    report = classification_report(true_labels, true_predictions, output_dict=True)

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(EVAL_DIR / "ner_person_org_v1_metrics.json", "w", encoding="utf-8") as fh:
        json.dump(
            {
                "overall": {k: v for k, v in metrics.items() if isinstance(v, (int, float))},
                "by_label": report,
                "train_size": len(train_examples),
                "val_size": len(val_examples),
                "base_model": MODEL_NAME,
            },
            fh, ensure_ascii=False, indent=2,
            # seqeval의 classification_report가 support 값을 numpy int64로
            # 돌려줘서 그대로는 json.dump가 직렬화하지 못한다.
            default=lambda o: o.item() if hasattr(o, "item") else str(o),
        )
    print(f"평가 결과 저장: {EVAL_DIR / 'ner_person_org_v1_metrics.json'}")

    OUTPUT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(OUTPUT_MODEL_DIR))
    tokenizer.save_pretrained(str(OUTPUT_MODEL_DIR))
    print(f"모델 저장: {OUTPUT_MODEL_DIR}")


if __name__ == "__main__":
    main()
