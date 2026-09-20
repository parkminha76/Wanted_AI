"""실제로 실패했던 CSV/이미지 텍스트로 파인튜닝 전후 NER 결과를 비교한다.

seqeval f1=1.0은 합성 검증셋이 학습 패턴과 너무 닮아서 나온 수치일 수 있으므로
믿지 않는다. 대신 이번 세션에서 실제로 이름을 놓치거나 잘라 먹던 진짜 문장을
그대로 넣어, 파인튜닝된 모델이 베이스 모델보다 실제로 나아졌는지 확인한다.

실행 (GPU 파드에서):
    python3 -m ml.training.ner_finetune.verify_real_cases
"""

from __future__ import annotations

from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline

BASE_MODEL = "Leo97/KoELECTRA-small-v3-modu-ner"
FINETUNED_MODEL = "/workspace/wanted/ml/models/ner_person_org_v1"

# 실측: 주문내역.csv 실제 행(오미정/양재호/김채원 놓침), 참석자명단.png 실제 줄
# (번호 목록 "1. 이름 (회사)", 두 줄 블록 "이름  (회사)\n연락처 이메일").
CASES = [
    ("CSV행-오미정", "ORD-2026-10234,2026-09-01 00:00,오미정,010-3000-5000,buyer01@example.com"),
    ("CSV행-양재호", "ORD-2026-10237,2026-09-01 21:00,양재호,010-3003-5003,buyer04@example.com"),
    ("CSV행-김채원", "ORD-2026-10240,2026-09-02 18:00,김채원,010-3006-5006,buyer07@example.com"),
    ("번호목록", "3. 박서준 (블루웨이브 솔루션)"),
    ("참석자두줄", "이지훈  (넥스트브릿지)\n010-4455-6677    guest12@example.com"),
    ("자연문장(회귀확인)", "김민준님이 한빛전자에서 근무 중입니다."),
]


def _extract(nlp, text: str) -> list[str]:
    results = nlp(text)
    out = []
    for r in results:
        if r["entity_group"] in ("PS", "OG"):
            out.append(f"{r['entity_group']}:{r['word']}({r['score']:.2f})")
    return out


def main() -> None:
    for label, model_path in (("베이스", BASE_MODEL), ("파인튜닝", FINETUNED_MODEL)):
        print(f"\n===== {label} 모델 ({model_path}) =====")
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model = AutoModelForTokenClassification.from_pretrained(model_path)
        nlp = pipeline(
            "token-classification", model=model, tokenizer=tokenizer,
            aggregation_strategy="simple", device=0,
        )
        for case_label, text in CASES:
            found = _extract(nlp, text)
            print(f"[{case_label}] {text!r}\n  -> {found}")


if __name__ == "__main__":
    main()
