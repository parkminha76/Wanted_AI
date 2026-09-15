# docXray 백엔드 Railway 배포 순서

팀: Tracer  
서비스: docXray

## 1. 배포할 커밋 준비

레포 루트에서 테스트를 통과시키고 변경사항을 GitHub에 push한다.

```powershell
uv run python -m unittest backend.tests.test_id_detector_postprocess backend.tests.test_image_quality_guard backend.tests.test_masking_policy backend.tests.test_logging_config -v
uv run python backend/scanner/tests/mask_check.py
git status
```

`.env`는 절대 commit하지 않는다. 모델 세 파일은 Git이 추적하는지 확인한다.

```powershell
git ls-files ml/models
git ls-files .env
```

## 2. Railway 프로젝트 생성

1. Railway에 GitHub 계정으로 로그인한다.
2. `New Project` → `Deploy from GitHub repo`를 선택한다.
3. `skn35-wanted/Wanted_AI` 저장소를 선택한다.
4. 서비스 이름을 `docxray-api`로 바꾼다.
5. Root Directory는 비워 둔다. 백엔드는 `backend/`, `ml/models/`, 루트의
   `pyproject.toml`을 함께 사용하므로 `/backend`로 설정하면 안 된다.

루트 `Dockerfile`은 Railway가 자동으로 감지한다.

## 3. Railway Variables 입력

`docxray-api` → Variables에 다음 키를 입력한다. 값은 로컬 `.env`에서 복사하되
로그나 채팅에는 붙여넣지 않는다.

```dotenv
DB_HOST=...
DB_PORT=4000
DB_USERNAME=...
DB_PASSWORD=...
DB_DATABASE=infoguard
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
ALLOWED_ORIGINS=http://localhost:5173
INFOGUARD_LOG_LEVEL=INFO
```

로컬 `.env`에 `ANTHROPIC_MODEL`이 있고 현재 훈련 모드가 정상 동작한다면 그 값도
같이 등록한다. 값이 없다면 Railway에 빈 변수를 만들지 않고 키 자체를 생략한다.

프론트 배포 전에는 `ALLOWED_ORIGINS`를 임시 로컬 값으로 두고, Vercel 주소가
생기면 `https://<project>.vercel.app`으로 교체한다.

## 4. 서비스 설정

- Region: Southeast Asia (Singapore)
- Replicas: 1
- Healthcheck Path: `/health`
- Healthcheck Timeout: 300초
- Restart Policy: On Failure
- 서버 명령은 Dockerfile에 들어 있으므로 Start Command는 비워 둔다.

모델과 다운로드 레지스트리가 프로세스 메모리에 있으므로 worker와 replica를
여러 개로 늘리지 않는다. 업로드 원본과 마스킹 사본은 임시 디스크만 사용하며
Railway Volume은 연결하지 않는다.

## 5. 공개 주소 생성

Settings → Networking → Generate Domain을 누른다. 생성된 주소를 편의상 아래처럼
기록한다.

```text
BACKEND_URL=https://docxray-api-xxxx.up.railway.app
```

브라우저에서 `${BACKEND_URL}/health`를 열어 `status: ok`와
`training_mode: on`을 확인한다. `training_mode: off`라면 응답의
`training_mode_error`와 Railway 로그를 확인한다.

## 6. DB 테이블 최초 생성

TiDB에 테이블이 이미 있으면 건너뛴다. 새 데이터베이스라면 Railway 서비스 Shell에서
다음 명령을 한 번만 실행한다.

```bash
uv run python -m backend.db.session
```

이 명령은 없는 테이블만 생성한다. `--reset`과 `--drop`은 배포 환경에서 실행하지 않는다.

## 7. 운영 주소에서 백엔드 확인

순서대로 확인한다.

1. `GET /health` → HTTP 200
2. `GET /samples` → 합성 데모 목록 반환
3. 작은 TXT 파일을 `POST /scan`으로 업로드
4. 응답의 `file_id`로 `GET /download/{file_id}` 다운로드
5. `POST /training/start` 호출로 훈련 모드와 외부 API 키 확인
6. Railway Logs에서 원문·탐지값·API 키가 출력되지 않는지 확인

## 8. 프론트 연결 후 마무리

Vercel에 프론트를 배포한 뒤 Railway의 `ALLOWED_ORIGINS`를 Vercel 운영 주소로
바꾸고 재배포한다. Vercel에는 다음 환경변수를 설정한다.

```dotenv
VITE_API_BASE_URL=https://docxray-api-xxxx.up.railway.app
```

마지막으로 브라우저 화면에서 파일 업로드 → 결과 확인 → 선택 마스킹 → 다운로드를
한 번 끝까지 수행한다.
