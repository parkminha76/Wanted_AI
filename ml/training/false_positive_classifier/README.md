# 오탐 제거 분류기 v1

정규식이 찾은 후보가 실제 개인정보인지 문맥으로 판별한다. 후보값의
체크섬은 `text[start:end]`를 validator에 넘겨 계산하고, TF-IDF에서는
후보값을 `__VALUE__`로 치환해 숫자열이 아닌 주변 문맥을 학습한다. Kiwi 단어
n-gram과 문자 n-gram을 같이 사용하며, `type`과 문맥 토큰을 결합한 특성으로
같은 단어도 탐지 타입에 따라 다른 의미를 학습한다.

v1 학습 대상은 `account`, `biz_reg`, `card`다. 표준 형식과 체크섬이 없는
`emp_no`와 문맥 분류 성능이 불안정한 `phone`은 학습에서 제외한다. 저장 모델의
`risk_types`에도 들어가지 않으므로 스캐너에서 분류기를 우회하고 기존 탐지 결과를
유지한다. `rules.py`의 사번·전화번호 탐지 규칙은 이 학습 과정에서 변경하지 않는다.

## 학습

```powershell
uv run python -m ml.training.false_positive_classifier.train
```

`sample_data/false_positive/false_positive_*.json` 중 파일명에 `_eval_`이 없는
학습 파일만 읽는다. 같은 `group_id`가 학습과 평가 fold에 나뉘지 않도록 5-fold `StratifiedGroupKFold`로 평가한다.
로지스틱 회귀의 `C` 후보를 비교한 뒤 최종 모델은 전체 데이터로 다시
학습한다.

모델의 `C`는 PR-AUC를 우선해 선택한다. 선택된 모델의 그룹 교차검증 예측에서
개인정보 후보 누락률(FNR)이 5% 이하인 지점 중 precision이 가장 높은 임계값을
`model.operating_threshold`에 저장한다. 스캐너는 고정된 0.5 대신 이 값을 사용한다.

`phone`은 휴대전화, 서울·지역 전화, 인터넷전화, 안심번호와 하이픈·공백·붙여 쓴
형식 모두 앞단 규칙이 찾은 결과를 그대로 유지한다. 오탐이 늘더라도 실제 전화번호가
마스킹에서 제외되는 위험을 피하기 위한 개인정보 보호 우선 정책이다.

- 모델: `ml/models/fp_filter_v1.pkl`
- 교차검증: `ml/eval/false_positive_eval/fp_filter_v1_metrics.json`
- 별도 holdout: `ml/eval/false_positive_eval/fp_filter_v1_holdout_metrics.json`

## 테스트

```powershell
uv run python -m ml.eval.false_positive_eval.evaluate_holdout
uv run python -m unittest ml.eval.false_positive_eval.test_false_positive_filter -v
```

v1은 합성 데이터 190건으로 학습하고 `group_id` 단위 교차검증으로 평가한다.
별도 파일 중 지원 타입에 해당하는 48건은 학습에서 제외하고 holdout으로 측정한다.
동일 문장은 없지만 32건이 학습셋과 같은 `group_id`와 유사 문장 틀을 사용하므로 완전 독립
평가셋으로 간주하지 않는다. 최신 수치는 두 평가 JSON을 함께 확인한다.
합성 데이터의 양성 비율은 실제 `rules.py` 후보 분포와 다를 수 있으므로 PR-AUC와
precision을 운영 환경의 실제 비율로 해석하면 안 된다.
