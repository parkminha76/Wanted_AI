# 인젝션 분류기 v1

검사 대상 문장이 AI의 지시를 바꾸거나 정보 유출·안전장치 우회를 유도하는지
판별하는 한국어 이진 분류기다.

## 학습

저장소 루트에서 실행한다.

```powershell
uv run python ml/training/injection_classifier/injection_classifier.py
```

기본 입력은 `sample_data/injection/injection_*.json`, 출력은 다음 두 파일이다.

- 모델: `ml/models/injection_classifier_v1.pkl`
- 평가: `ml/eval/injection_eval/injection_classifier_v1_metrics.json`

같은 `group_id`의 문장이 학습·검증 fold에 갈라지지 않도록 5-fold
`StratifiedGroupKFold`를 사용한다. `level`, `source`, `attack_type`은 모델 feature로
사용하지 않는다.

## 추론

```python
from ml.training.injection_classifier import InjectionClassifier

model = InjectionClassifier.load("ml/models/injection_classifier_v1.pkl")
is_command, confidence = model.predict(sentence)
```

`confidence`는 `label=1`인 인젝션일 확률이며 기본 임계값은 0.5다.

## v1 결과와 제한

- 학습 데이터: 합성 데이터 587건, 501개 그룹
- label=0: 374건 / label=1: 213건
- 그룹 분리 5-fold 교차검증: Precision 0.9306, Recall 0.9437, F1 0.9371
- ROC-AUC 0.9861, PR-AUC 0.9798
- Lv.1~5와 영문 데이터 40건을 포함한다. 레벨별 성능은 평가 JSON에 기록한다.
- Lv.2는 FP 5건/FN 3건(FPR 4.0%, FNR 4.8%), Lv.3은 FP 7건/FN 4건
  (FPR 5.6%, FNR 6.2%)이다.
- 일반 업무문서 오탐률은 2.1%, hard negative와 보안교육 인용문 오탐률은 각각
  10.0%, 한국어 공격 문장 누락률은 4.7%다. 영문 공격 문장 누락률은 15.0%로
  추가 개선이 필요하다.
- 모두 합성 데이터 생성 흐름에서 만들어졌으므로 독립 실문서 평가 성능은 아직
  확인되지 않았다. 발표 수치에는 평가 방식과 이 제한을 함께 적는다.

`pickle` 모델은 임의의 외부 파일을 로드하면 코드 실행 위험이 있으므로 이 학습
스크립트가 만든 신뢰 가능한 로컬 파일만 사용한다.
