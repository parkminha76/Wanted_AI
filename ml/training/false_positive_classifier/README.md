# 오탐 제거 분류기 v1

정규식이 찾은 후보가 실제 개인정보인지 문맥으로 판별한다. 후보값의
체크섬은 문장 전체가 아닌 `text[start:end]`를 validator에 넘겨 계산한다.

## 학습

```powershell
uv run python -m ml.training.false_positive_classifier.train
```

`sample_data/false_positive/false_positive_*.json`을 모두 읽고, 같은 `group_id`가
학습과 평가 fold에 나뉘지 않도록 5-fold `StratifiedGroupKFold`로 평가한다.
로지스틱 회귀의 `C` 후보를 비교한 뒤 최종 모델은 전체 데이터로 다시
학습한다.

- 모델: `ml/models/fp_filter_v1.pkl`
- 평가: `ml/eval/false_positive_eval/fp_filter_v1_metrics.json`

## 테스트

```powershell
uv run python -m unittest ml.eval.false_positive_eval.test_false_positive_filter -v
```

v1은 합성 데이터 298건, 149개 그룹으로 학습했다. 그룹 분리 교차검증에서
`C=4.0`, precision 0.8311, recall 0.8200, F1 0.8255였다. 독립된 실제 문서
평가셋 성능은 아직 확인하지 않았다.
