# 백엔드 운영 로그

InfoGuard는 표준 출력에 JSON Lines 형식으로 로그를 남긴다. Railway 등 배포
플랫폼에서는 별도 파일 설정 없이 각 줄을 수집할 수 있다.

## 실행

```bash
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

기본 레벨은 `INFO`다. 필요하면 환경 변수로 조정한다.

```bash
INFOGUARD_LOG_LEVEL=WARNING
```

애플리케이션이 개인정보 보호형 접근 로그를 직접 만들기 때문에 Uvicorn의 원시
접근 로그는 꺼진다. 원시 접근 로그는 `/download/all?batch_id=...`의 다운로드
자격값을 그대로 기록할 수 있다.

## 기록되는 이벤트

| event | 의미 |
|---|---|
| `service.started` | 서버 시작 및 고아 임시 폴더 청소 결과 |
| `service.stopped` | 서버 종료 |
| `http.request.completed` | 메서드, 라우트 템플릿, 상태 코드, 처리 시간 |
| `http.request.failed` | 처리되지 않은 예외의 클래스와 처리 시간 |
| `scan.files.completed` | 파일 수·확장자·입력 크기·탐지 유형별 건수 |
| `scan.text.completed` | 텍스트 바이트 수와 탐지 유형별 건수 |
| `download.file.ready` | 단일 마스킹 사본 다운로드 준비 |
| `download.batch.ready` | ZIP 다운로드 준비 및 파일 수 |
| `samples.returned` | 데모 샘플 캐시 사용 여부 |
| `training.started` | 훈련 난이도와 시작 상태 |
| `training.reply.processed` | 턴 번호와 탐지 유형별 건수 |
| `training.report.generated` | 리포트 생성 완료 |
| `training.*.failed` | 훈련 단계별 오류 클래스 |

각 요청 응답에는 `X-Request-ID`가 붙고, 같은 요청에서 발생한 로그에는 동일한
`request_id`가 기록된다.

## 기록하지 않는 값

다음 값은 로그 필드 허용 목록에 없어서 `log_event()`에 넘겨도 출력되지 않는다.

- 업로드 파일명과 로컬 경로
- 문서 및 훈련 답장의 원문
- 탐지된 이름·주소·전화번호 등 실제 값
- finding의 `text`, `start`, `end`
- 사용자·세션·훈련 진행 ID
- `file_id`, `batch_id` 및 URL 쿼리 문자열
- API 키와 인증 헤더
- 예외 메시지와 traceback

오류는 `error_code`에 예외 클래스만 남긴다. 상세 재현에는 응답의
`X-Request-ID`, 발생 시각, 입력 파일 형식과 로컬 재현 절차를 사용한다.

## 로그 예시

```json
{"timestamp":"2026-09-15T01:37:54.464+00:00","level":"INFO","logger":"infoguard.backend.main","event":"scan.files.completed","request_id":"6124bb04e68b4cd7a1c98905a882d14b","duration_ms":12319.4,"file_count":1,"file_types":[".txt"],"input_bytes":30,"masked_file_count":1,"total_findings":0,"filtered_out":0,"finding_counts":{},"risk_levels":{"low":1}}
```

