# 오탐 제거 분류기 v1

정규식이 찾은 후보가 실제 개인정보인지 문맥으로 판별한다. 후보값의
체크섬은 `text[start:end]`를 validator에 넘겨 계산하고, TF-IDF에서는
후보값을 `__VALUE__`로 치환해 숫자열이 아닌 주변 문맥을 학습한다. Kiwi 단어
n-gram과 문자 n-gram을 같이 사용한다.

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

v1은 합성 데이터로 학습하고 `group_id` 단위 교차검증으로 평가한다.
최신 건수와 성능은 `ml/eval/false_positive_eval/fp_filter_v1_metrics.json`을
기준으로 한다. 독립된 실제 문서 평가셋 성능은 아직 확인하지 않았다.
