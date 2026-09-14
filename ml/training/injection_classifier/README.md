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

`confidence`는 `label=1`인 인젝션일 확률이며 모델의 기본 임계값은 0.6이다.

## v1 결과와 제한

- 학습 데이터: 합성 데이터 963건, 625개 그룹
- label=0: 610건 / label=1: 353건
- 운영 후보 임계값 0.6의 그룹 분리 5-fold 교차검증: Precision 0.9484,
  Recall 0.9377, F1 0.9430
- ROC-AUC 0.9916, PR-AUC 0.9888
- Lv.1~5와 영문 문장 60건(공격 40건, 정상 20건)을 포함한다. 레벨별 성능은
  평가 JSON에 기록한다.
- Lv.2는 FP 6건/FN 7건(FPR 3.4%, FNR 7.2%), Lv.3은 FP 6건/FN 7건
  (FPR 4.0%, FNR 7.1%)이다.
- 문서 머리글·표 셀·꼬리글 형태의 정상 조각 96건을 추가했고, 해당 source의
  교차검증 오탐률은 0%(0/96)다.
- 별도 100건 검증셋에서 스캐너와 같은 키워드 보조 판정을 포함한 오프라인 평가의
  임계값 0.6 기준 Precision 0.917, Recall 0.825, F1 0.868
  (TP 33, FP 3, FN 7, TN 57)을 기록했다.
  이 검증셋은 모델 설정 선택에 사용했으므로 최종 독립 테스트 수치로 사용하지 않는다.
- 현재 `backend/scanner/detectors/models.py`의 통합 임계값 0.7에서는 같은 검증셋의
  Precision 0.935, Recall 0.725, F1 0.817이다. 0.6 적용은 스캐너 담당자가 통합
  정책을 확인한 뒤 반영해야 한다.
- 네 데모 문서 회귀 검사에서는 정상 문서 3개에 인젝션 오탐이 없었고, 공격 문서는
  숨겨진 인젝션 1건만 탐지했다.
- 보안교육 인용문의 키워드가 스캐너의 규칙 기반 보조 판정에 걸리는 사례가 남아 있다.
  기존 `translated_en` 영문 공격 source의 교차검증 누락률은 40.0%에서 15.0%로
  감소했다.
- 데이터가 모두 합성이므로 독립 실문서 평가는 별도의 미사용 평가셋으로 진행해야 한다.
  발표 수치에는 평가 방식과 이 제한을 함께 적는다.

`pickle` 모델은 임의의 외부 파일을 로드하면 코드 실행 위험이 있으므로 이 학습
스크립트가 만든 신뢰 가능한 로컬 파일만 사용한다.
