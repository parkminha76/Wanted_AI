# backend/db

InfoGuard 데이터베이스 레이어. TiDB Cloud(MySQL 호환)를 쓴다.

담당: A (backend/db 중 B와 안 겹치는 스키마/로직 부분)

---

## 폴더 구성

```
backend/db/
├── __init__.py
├── tables.py             테이블 정의 (SQLAlchemy ORM 클래스)
├── session.py            DB 연결, 세션, 테이블 생성
├── converters.py         backend/shared/schema.py ↔ DB row 변환
├── codes.py              자유 텍스트 -> 고정 코드 변환, evidence 화이트리스트
├── seed_demo_user.py     공모전 데모용 고정 사용자(id=1) 준비
├── schema.sql            위 tables.py와 같은 내용을 SQL DDL로 옮긴 것(참고용)
├── retention.md          보존 기간·삭제 정책. 이 문서와 역할이 다르니 헷갈리지 말 것
├── validation_scope.md   @validates가 실제로 커버하는 범위(ORM 경로 한정) 설명
└── readme.md             이 문서
```

역할이 여러 파일로 나뉜 이유: `tables.py`는 스키마만 알면 되고, `session.py`는 연결 정보(.env)만 알면 되고, `converters.py`만 `backend/shared/schema.py`(B의 계약 파일)를 안다. 계약 파일이 바뀌어도 `tables.py`/`session.py`는 안 건드려도 되게 분리했다.

> **주의**: 이 파일 안 예전 버전은 계약 파일을 `backend/shared/schemas.py`(복수형)라고 적어뒀는데 실제 모듈명은 `backend/shared/schema.py`(단수형)다. import 예시에 그대로 쓰면 `ModuleNotFoundError`가 난다 — 2026-09-16 정정.

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

### 3. 테이블 생성 + 데모 유저

**2026-09-16부터 `backend/main.py`의 앱 시작(`lifespan`)이 이 두 단계를 자동으로 해준다** (`init_db()` + `ensure_demo_user()`, 실패해도 서버는 그대로 뜬다 — "DB 없어도 스캔은 된다" 원칙). 서버를 한 번이라도 띄우면 별도 작업이 필요 없다.

로컬에서 서버를 안 띄우고 DB만 먼저 준비하고 싶을 때만 수동으로 돌린다:
```bash
python -m backend.db.session
python -m backend.db.seed_demo_user
```
`테이블 생성 완료: [...]`가 뜨면 8개 테이블이 다 만들어진 것이고, `데모 사용자 생성: id=1, role=individual`이 뜨면 이후 스캔·훈련 저장이 참조할 기본 사용자가 준비된 것이다.

---

## 테이블 목록

| 테이블 | 역할 | 실제로 쓰이나? |
|---|---|---|
| `companies` | 기업 계정 확장 자리 | ❌ 로직 없음, row 안 생김 (확장 방향성만) |
| `users` | 세션 식별용 사용자 | 🟡 `seed_demo_user.py`가 만든 데모 계정(id=1) 하나만 씀. 로그인이 없어서 여러 유저를 구분하지 않는다 |
| `scan_results` | 파일/텍스트 1건 검사 결과 | ✅ `ScanResult`와 1:1 대응. 2026-09-16부터 `/scan`, `/scan/text`가 실제로 씀 |
| `findings` | 검사에서 찾은 위험 항목 | ✅ `Finding`과 1:1 대응. 오탐 제거된 것도 `excluded=True`로 남김(지우지 않음). `scan_results`와 같이 씀 |
| `hidden_commands` | 숨은 명령/인젝션 확인 상태 | ✅ `save_scan_result()`가 hidden_text/injection Finding마다 자동으로 `status="확인필요"` row를 만들고, 2026-09-16부터는 `PATCH /scan-results/{scan_result_id}/hidden-commands/{finding_ref}`로 "제거함"/"무시함"으로 바꿀 수 있다(화면 연동은 아직 안 됨) |
| `training_progress` | 훈련 레벨 진행 상황 | ✅ `/training/start`, `/training/{id}/reply` 완료 시 씀 |
| `training_events` | 훈련 중 턴별 유출 시도 기록 | ✅ 2026-09-16부터 `/training/{id}/reply`가 턴마다 씀. Defender AI 리포트의 재료 |
| `scam_cases` | 본선용 RAG 사례 풀 | ❌ **예선 스코프 아님.** 테이블만 미리 생성, 데이터/로직 없음 |

`companies`, `scam_cases`는 지금 스코프에서 완전히 비어있는 테이블이다. 지우지 말고 그대로 둘 것 — 발표에서 확장 구조 근거로 쓴다.

---

## B/C가 실제로 쓰는 법

`backend/scanner/scan.py`의 `scan_file()` / `scan_text()`가 돌려주는 `ScanResult`를 DB에 저장하려면 `converters.py`를 거친다. 직접 `tables.py`의 ORM 클래스를 조립하지 말 것.

> `backend/shared/schema.py`에도 `scan_file`/`scan_text`라는 이름이 있지만 그건 계약(타입 시그니처)만 적어둔 자리이고 전부 `NotImplementedError`를 던진다 — 실제 구현은 `backend/scanner/scan.py`에 있다. 이름이 같아서 잘못 import하기 쉽다.

### 실제 연결 지점 — `backend/main.py`의 `_persist_scan_results()`

아래는 예전 계획이 아니라 **지금 실제로 도는 코드**를 그대로 옮긴 것이다(`backend/main.py`).

```python
try:
    from backend.db.session import SessionLocal
    from backend.db.converters import save_scan_result
    from backend.db.seed_demo_user import DEMO_USER_ID
except Exception:
    SessionLocal = None  # DB 자격증명이 없는 환경 — 스캐너는 그대로 떠야 한다

def _persist_scan_results(results: list[ScanResult]) -> None:
    if SessionLocal is None:
        return
    db = SessionLocal()
    try:
        for result in results:
            save_scan_result(db, DEMO_USER_ID, result, file_extension=result.file_type)
        db.commit()
    except Exception:
        db.rollback()  # 실패해도 스캔 응답 자체는 그대로 나간다
    finally:
        db.close()
```

`/scan`(파일 업로드), `/scan/text`(단문 검사) 핸들러 끝에서 `_persist_scan_results(...)`를 호출한다. 아직 로그인이 없어서 **전부 `DEMO_USER_ID`(=1)로 저장한다** — 사용자별 통계가 필요해지면 그때 실제 `user_id`를 받는 구조로 바꿔야 한다.

`/samples`(심사위원용 캐시 미리보기)는 **의도적으로 저장 안 함** — 실제 사용자 스캔이 아니라 캐시 워밍업이라, 저장하면 통계가 오염된다. `/mask`, `/samples/mask`(마스킹 선택 재적용)도 지금은 저장 안 한다.

### 훈련 모드 실시간 답장 — 계획과 실제 구현이 다르다

**여기가 예전 설계와 가장 많이 갈린 부분이다.** 원래 계획은 답장마다 `scan_text()`(NER 포함 정식 스캐너)를 돌리는 것이었지만, 실제 구현(`backend/training/sanitizer.py`)은 그보다 훨씬 가벼운 **정규식 5종(rrn/card/account/phone/email)만 보는 `sanitize_training_text()`**를 쓴다. `Finding`도 `ScanResult`도 안 만들고 `["phone", "account"]`처럼 감지된 타입 이름 리스트만 돌려준다 — 매 턴 NER을 돌리면 응답이 느려지고, 이름·조직명처럼 오탐이 잦은 항목까지 걸릴 위험이 있어서 일부러 좁혀둔 것이다(`sanitizer.py` 주석 참고).

그래서 `save_scan_result()`를 그대로 쓸 수 없다 — `ScanResult`가 없기 때문이다. 대신 `backend/training/router.py`의 `_record_training_event()`가 `TrainingEvent`에 직접 기록한다(실제 라우트는 `/training/{training_progress_id}/reply`이지 `/training/{level}/message`가 아니다):

```python
def _record_training_event(db, training_progress_id, turn_no, shared_fields):
    try:
        db.add(TrainingEvent(
            training_progress_id=training_progress_id,
            turn_no=turn_no,
            # (training_progress_id, turn_no) 유니크 제약 때문에 한 턴에 여러 유형을
            # 같이 공유해도 첫 번째만 남는다 — 정밀 로그가 아니라 "이 턴에 위험한
            # 공유가 있었나"를 보는 용도다.
            detected_field=shared_fields[0] if shared_fields else None,
            action="경고표시" if shared_fields else None,
        ))
        db.commit()
    except Exception:
        db.rollback()  # 실패해도 훈련 진행 자체는 막지 않는다
```

> **알아두어야 할 것**: `converters.py`에도 `record_training_event(db, training_progress_id, turn_no, result: ScanResult | None, action: str)`라는 함수가 이미 있다. 원래 계획(위 문단의 "답장마다 scan_text() 돌리기")대로 짜인 함수라 `ScanResult`를 받는데, 실제 흐름은 `ScanResult`를 만들지 않으므로 **이 함수는 지금 아무 데서도 안 쓰인다.** 이름이 같은 기능을 하는 두 함수가 따로 존재하는 상태다 — 나중에 실시간 답장 검사를 정식 스캐너로 바꾸게 되면 그때 `router.py`의 버전을 지우고 `converters.py`의 버전으로 통일하는 정리가 필요하다.

### `converters.py`의 나머지 함수 (전부 아직 미사용)

읽기 쪽 변환 함수 4개가 이미 만들어져 있지만 어떤 라우트도 아직 호출하지 않는다 — DB에서 다시 읽어 화면에 보여주는 기능(스캔 이력, Defender 리포트 등)을 만들 때 쓰면 된다.

| 함수 | 용도 |
|---|---|
| `get_hidden_commands_for_scan(db, scan_result_id)` | 이 스캔에 속한 hidden_command 목록. `hidden_commands`엔 `scan_result_id`가 없어서 `findings`를 조인해서 구한다 |
| `record_training_event(...)` | 위 문단 참고 — 지금은 미사용, 정식 스캐너 연결 시 재검토 |
| `build_defender_payload(db, training_progress_id)` | Defender AI에게 넘길 턴별 행동 로그(원문 없이 `action`/`detected_type`만) |
| `scan_summary_from_row(row)` | DB에 저장된 집계만으로 만드는 요약 dict. 원문/하이라이트는 애초에 저장 안 해서 복원 불가 — 스캔 이력 목록 카드 정도에만 쓴다 |

---

## 주의사항

- **`type` 컬럼은 `String`이지 `Enum`이 아니다.** `backend/shared/schema.py`의 `RiskType`이 계속 늘어날 걸 감안해서 자유롭게 값이 들어가게 열어뒀다. 새 타입 추가돼도 DB 마이그레이션 불필요.
- **`masked_path`는 절대 API 응답에 노출하지 않는다** (서버 내부 경로). `ScanResult.to_dict()`도 이미 이 필드를 뺀다.
- **findings는 지우지 않는다.** 오탐 제거된 항목도 `excluded=True`로 남겨서 "우리가 오탐을 걸러냈다"는 증거로 화면에 보여준다.
- **`hidden_commands` 갱신 API는 있지만 화면이 아직 안 부른다.** `PATCH /scan-results/{scan_result_id}/hidden-commands/{finding_ref}`가 2026-09-16에 추가됐다 — `scan_result_id`는 `ScanResult.db_id`(저장 성공했을 때만 채워짐), `finding_ref`는 이미 응답에 있는 `Finding.id`("f_003" 등)를 그대로 쓴다. 화면이 "제거/무시" 버튼을 누를 때 이 요청을 보내도록 프론트 쪽 연동이 남아있다.
- 로컬 개발 시 TiDB 대신 도커 MySQL 쓰려면 `session.py`의 `DATABASE_URL` 생성부에서 SSL 옵션 없는 주석 처리된 줄로 바꿔서 쓴다.
- `backend/shared/schema.py`가 바뀌면(특히 `RiskType`에 새 값 추가) `converters.py`는 대부분 그대로 동작하지만, `RISK_WEIGHTS`/`TYPE_LABELS`에 새 타입 추가 시 스키마 버전(`SCHEMA_VERSION`)이 올라갔는지 확인할 것.
- **테스트에서 실제 TiDB를 직접 건드리지 말 것.** `backend/training/test_router_training_event.py`처럼 인메모리 SQLite(`create_engine("sqlite:///:memory:")`)로 격리하는 걸 기본으로 한다 — BigInteger PK는 SQLite에서 autoincrement가 안 붙으므로 그 파일의 `before_insert` 리스너 패턴을 참고할 것.

---

## 아직 안 된 것 (TODO)

- [ ] `scam_cases`에 실제 데이터 채우기 — 본선 진출 시
- [x] ~~`hidden_commands.status` 변경 API~~ — 2026-09-16에 `PATCH /scan-results/{scan_result_id}/hidden-commands/{finding_ref}`로 백엔드는 완료. **화면 연동은 아직 남음** — "제거/무시" 버튼을 누를 때 이 요청을 보내도록 프론트에서 붙여야 실제로 쓰인다.
- [x] ~~`db/retention_job.py`가 실제로 없다~~ — 2026-09-16에 만들었다. `python -m backend.db.retention_job`(기본은 dry-run, `--execute`로 실제 삭제, `--training-before YYYY-MM-DD`로 완료된 훈련 데이터까지 정리). 아직 크론/스케줄러에 등록은 안 했다 — retention.md의 "스크립트 존재 ≠ 자동 실행" 문단대로, 실제로 주기 실행을 걸 지는 팀이 정할 것.
- [ ] `converters.record_training_event()`와 `router._record_training_event()` 중복 정리 — 위 "훈련 모드 실시간 답장" 문단 참고. 실시간 답장 검사를 정식 스캐너로 바꾸는 시점에 하나로 합칠 것.
- [ ] `/mask`, `/samples/mask`도 DB에 남길지 결정 — 지금은 의도적으로 제외했지만, "마스킹까지 완료한 파일" 통계가 필요해지면 여기도 연결해야 한다.
