# backend/db

InfoGuard 데이터베이스 레이어. TiDB Cloud(MySQL 호환)를 쓴다.

담당: A (backend/db 중 B와 안 겹치는 스키마/로직 부분)

---

## 폴더 구성

```
backend/db/
├── __init__.py
├── tables.py       테이블 정의 (SQLAlchemy ORM 클래스)
├── session.py      DB 연결, 세션, 테이블 생성
├── converters.py   backend/shared/schemas.py ↔ DB row 변환
└── README.md       이 문서
```

역할이 세 파일로 나뉜 이유: `tables.py`는 스키마만 알면 되고, `session.py`는 연결 정보(.env)만 알면 되고, `converters.py`만 `backend/shared/schemas.py`(B의 계약 파일)를 안다. 계약 파일이 바뀌어도 `tables.py`/`session.py`는 안 건드려도 되게 분리했다.

---

## 처음 세팅하는 법

### 1. 패키지 설치
```bash
uv add sqlalchemy pymysql python-dotenv
```

### 2. `.env` 파일 (프로젝트 루트, `backend/`와 같은 레벨)
```dotenv
DB_HOST = gateway01.ap-northeast-1.prod.aws.tidbcloud.com
DB_PORT = 4000
DB_USERNAME = xxx.root
DB_PASSWORD = ***********
DB_DATABASE = infoguard
-> 예시용으로 db 이름은 그냥 원하는거 해도 됩니다
```
TiDB Cloud 대시보드 → 클러스터 → Connect 에서 발급받는다. `.env`는 반드시 `.gitignore`에 포함할 것 (커밋 금지).

### 3. 테이블 생성
프로젝트 루트에서:
```bash
python -m backend.db.session
```
`테이블 생성 완료: [...]`가 뜨면 8개 테이블이 다 만들어진 것이다.

---

## 테이블 목록

| 테이블 | 역할 | 비고 |
|---|---|---|
| `companies` | 기업 계정 확장 자리 | 로직 없음, row 안 생김 (확장 방향성만) |
| `users` | 세션 식별용 사용자 | 정식 회원가입 없이 이름/사번만 |
| `scan_results` | 파일/텍스트 1건 검사 결과 | `ScanResult`와 1:1 대응 |
| `findings` | 검사에서 찾은 위험 항목 | `Finding`과 1:1 대응. 오탐 제거된 것도 `excluded=True`로 남김 (지우지 않음) |
| `hidden_commands` | 숨은 명령/인젝션 확인 상태 | 사용자가 "제거/무시" 선택한 상태만 별도 추적 |
| `training_progress` | 훈련 레벨 진행 상황 | 레벨 하나 = row 하나 |
| `training_events` | 훈련 중 턴별 유출 시도 기록 | Defender AI 리포트의 재료 |
| `scam_cases` | 본선용 RAG 사례 풀 | **예선 스코프 아님.** 테이블만 미리 생성, 데이터/로직 없음 |

`companies`, `scam_cases`는 지금 스코프에서 완전히 비어있는 테이블이다. 지우지 말고 그대로 둘 것 — 발표에서 확장 구조 근거로 쓴다.

---

## B/C가 실제로 쓰는 법

`backend/shared/schemas.py`의 `scan_file()` / `scan_text()`가 돌려주는 `ScanResult`를 그대로 DB에 저장하려면 `converters.py`를 거친다. 직접 `tables.py`의 ORM 클래스를 조립하지 말고 아래처럼 쓸 것.

### B — 파일 스캔 (`POST /scan`)
```python
from backend.shared.schemas import scan_file
from backend.db.session import get_session
from backend.db.converters import save_scan_result

@app.post("/scan")
def scan(file_path: str, user_id: int, db: Session = Depends(get_session)):
    result = scan_file(file_path).finalize()
    save_scan_result(db, user_id, result)
    db.commit()
    return result.to_dict()
```

### C — 훈련 중 실시간 답장 스캔 (`POST /training/{level}/message`)
```python
from backend.shared.schemas import scan_text
from backend.db.session import get_session
from backend.db.converters import save_scan_result
from backend.db.tables import TrainingEvent

@app.post("/training/{level}/message")
def message(text: str, training_progress_id: int, turn_no: int, user_id: int, db: Session = Depends(get_session)):
    result = scan_text(text).finalize()
    scan_row = save_scan_result(db, user_id, result) if result.findings else None
    db.add(TrainingEvent(
        training_progress_id=training_progress_id,
        scan_result_id=scan_row.id if scan_row else None,
        turn_no=turn_no,
        detected_field=result.findings[0].type if result.findings else None,
        action="경고표시" if result.findings else None,
    ))
    db.commit()
```

DB에서 다시 읽어서 API로 돌려줄 땐 `converters.scan_result_from_row()`로 역변환한다.

---

## 주의사항

- **`type` 컬럼은 `String`이지 `Enum`이 아니다.** `backend/shared/schemas.py`의 `RiskType`이 계속 늘어날 걸 감안해서 자유롭게 값이 들어가게 열어뒀다. 새 타입 추가돼도 DB 마이그레이션 불필요.
- **`masked_path`는 절대 API 응답에 노출하지 않는다** (서버 내부 경로). `ScanResult.to_dict()`도 이미 이 필드를 뺀다.
- **findings는 지우지 않는다.** 오탐 제거된 항목도 `excluded=True`로 남겨서 "우리가 오탐을 걸러냈다"는 증거로 화면에 보여준다.
- 로컬 개발 시 TiDB 대신 도커 MySQL 쓰려면 `session.py`의 `DATABASE_URL` 생성부에서 SSL 옵션 없는 주석 처리된 줄로 바꿔서 쓴다.
- `backend/shared/schemas.py`가 바뀌면(특히 `RiskType`에 새 값 추가) `converters.py`는 대부분 그대로 동작하지만, `RISK_WEIGHTS`/`TYPE_LABELS`에 새 타입 추가 시 스키마 버전(`SCHEMA_VERSION`)이 올라갔는지 확인할 것.

---

## 아직 안 된 것 (TODO)

- [ ] `scam_cases`에 실제 데이터 채우기 — 본선 진출 시
- [ ] 마스킹 사본 만료(`expires_at`) 배치 삭제 — 지금은 lazy delete도 미구현, 요청 시 체크 로직 필요
- [ ] `hidden_commands.status` 변경 API (`PATCH /scan/{id}/hidden-commands/{id}`) — B가 라우트 추가 필요