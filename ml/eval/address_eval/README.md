# 주소 탐지 규칙 평가

상세 주소 전체가 마스킹되는지와 서울·강남역 같은 일반 장소가 주소로 오탐되는지를
검증하기 위한 A 담당 산출물이다. 모델 학습 데이터가 아니며 B의 `rules.py`에 주소
패턴을 반영하기 전에 사용하는 합성 평가셋이다.

## 구성

- 도로명 주소 50건
- 지번 주소 50건
- 아파트·동·호 포함 주소 50건
- 일반 장소 30건 + 도로명·숫자가 포함된 문맥형 hard negative 20건
- 전체 200건, 모든 항목에 정확한 `start`/`end` 포함

## 실행

저장소 루트에서 실행한다.

```powershell
uv run python ml/data_generation/generate_address_eval.py
uv run python ml/eval/address_eval/evaluate_address_pattern.py
```

생성기는 seed를 고정해 매번 같은 데이터가 나온다. 평가 파일을 팀 기준선으로 확정한
뒤에는 결과가 좋지 않다는 이유로 문장을 수정하거나 학습 데이터에 합치지 않는다.

## 파일

- `address_cases.json` — 고정 합성 평가셋
- `address_pattern.py` — 상세 주소 정규식 프로토타입
- `address_pattern_metrics.json` — exact-span 평가 결과

정규식은 도로명·지번·동호수 주소를 한 구간으로 찾는 검토용 구현이다. 실제
`rules.py` 반영, NER의 `LC` 결과와 병합, DOCX·PDF·XLSX 오프셋 및 마스킹 검증은
B의 통합 범위다.

## 현재 기준선

200건 기준으로 양성 주소 150건은 모두 전체 구간을 찾았다. 문맥형 hard negative
20건은 정규식이 주소로 판단해 오탐했다(precision 0.8824, recall 1.0000,
F1 0.9375). 이는 의도적으로 남긴 한계다. 개인정보 보호상 주소 누락을 줄이는
규칙을 먼저 적용하고, 문맥형 오탐은 NER·문맥 판단 또는 사용자 확인 단계에서
처리할 수 있는지 B 통합 테스트에서 결정한다.
