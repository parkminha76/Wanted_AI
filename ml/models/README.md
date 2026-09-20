# ml/models — 학습된 가중치 저장 위치

오탐 제거 분류기, 한국어 인젝션 분류기, 신분증 CNN(YOLO) 가중치, NER 파인튜닝
가중치가 여기 쌓임. 용량이 커서 `.gitignore`가 이 폴더 전체를 기본 제외하고,
실제로 배포 서버가 로드하는 최종 가중치 파일만 개별 예외로 올려둠.
배포용으로 필요한 경량 가중치만 별도로 `infra/`쪽 배포 설정에 포함시킬 것.

- `ner_person_org_v1/` — `Leo97/KoELECTRA-small-v3-modu-ner`를 짧은 맥락(CSV 행·
  번호 목록·표 셀)의 이름·회사명 인식으로 이어서 학습한 모델
  (`ml/training/ner_finetune/` 참고). `model.safetensors`(55MB)는 Git LFS로
  추적함(`.gitattributes`). `backend/scanner/detectors/ner.py`가 이 폴더가
  있으면 베이스 모델 대신 이걸 우선 로드한다.
