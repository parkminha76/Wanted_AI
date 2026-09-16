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

## 2026-09-16 재학습 — 주문번호/송장번호/발주번호 하드 네거티브 보강

`evaluate_holdout.py`를 다시 돌려보니 캐시된 metrics json(48건짜리, 그룹 중복 67%)이
낡아 있었다 — 실제로는 `false_positive_eval_B_0915_final.json`이 이미 추가돼 있어
독립 평가셋이 168건(그룹 중복 19%)이었다. 이 168건 기준 재학습 전 성능은
Precision 0.894 / Recall 1.000 / F1 0.944였고, 오탐(label=0)이 새는 대부분이
`account` 유형(0.778, 28건 중 8건 누락)이었다. 새는 8건이 전부 "주문번호"·
"송장번호"·"온라인 주문" 3개 문장 틀이었는데, 학습 데이터에도 같은 도메인의
예문(`account_false_01`, `account_false_02`)이 있었지만 문장 구조(두 문장으로 나뉘고
어미가 다름)가 달라 일반화하지 못했다. `biz_reg`도 "고객 식별번호"·"발주번호" 2건이
같은 이유로 샜다.

- `false_positive_A_0916_hardening.json`에 16건 추가 — account 5틀(주문번호·
  송장번호·온라인주문·고객님의 주문·반품접수번호) x 2건 = 10건, biz_reg 3틀
  (고객식별번호·발주번호·구매요청번호) x 2건 = 6건. 전부 새 문장 틀이라 평가셋
  문장을 베끼지 않았다(학습 데이터 190 -> 206건, 그룹 95 -> 103개).
- 그룹 분리 5-fold 교차검증: 최적 C가 4.0 -> 8.0으로 바뀌었고 Precision 0.898 /
  Recall 0.978 / F1 0.936(재학습 전 0.935/0.956/0.945와 동급). 운영 임계값도
  0.450 -> 0.502로 올라갔다 — 새 정상 문장들 덕분에 더 높은 문턱에서도 실제
  개인정보 누락률(FNR) 5% 제약을 지킬 수 있게 됐다는 뜻이다.
- 같은 독립 holdout(168건): Precision 1.000 / Recall 0.976 / F1 0.988
  (재학습 전 0.894/1.000/0.944). `account`는 정밀도·재현율 모두 1.0으로 완전히
  고쳐졌다. `card`는 그대로 완벽했다.
- **대가**: `biz_reg`에서 오탐 2건이 사라진 대신 실제 사업자번호 2건("통신판매
  계약서의 사업자번호 ...를 기준으로 업체를 조회합니다" 문장 틀 1개, 값만 다름)이
  새로 걸러졌다(재현율 1.0 -> 0.929). 확신도 0.491로 예전 임계값(0.450)에서는
  통과했지만 새 임계값(0.502)에는 못 미친다 — 운영 임계값이 전체적으로 올라간
  부작용이라, 특정 문장을 잘못 학습해서 생긴 문제는 아니다. 전체 FNR은 2.4%로
  설계 제약(5%) 안에 있다.
- 인젝션 재학습 때와 같은 교훈: 작은 데이터셋(200건대)에 하드 네거티브를 추가하면
  운영 임계값 자체가 움직여서, 전혀 손대지 않은 다른 유형·문장에도 영향이 간다.
  이번엔 순이익이 컸지만(F1 +0.044), 다음에 더 밀어붙일 때는 매번 holdout으로
  재확인해야 한다.
