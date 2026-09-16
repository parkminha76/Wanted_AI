# infra — 프론트 배포 (Vercel)

`frontend/`를 Vercel에 정적 빌드로 올린다. 백엔드 배포는
[DEPLOY_BACKEND.md](DEPLOY_BACKEND.md)를 따른다.

- 운영 주소: https://docx-ray.vercel.app
- 배포 브랜치: `main` (push하면 자동 배포)

---

## 1. Vercel 프로젝트 설정

새로 만들 때 [vercel.com/new](https://vercel.com/new)의 **Import Git Repository**를
쓴다. "Clone from GitHub"(새 저장소를 만드는 화면)이 아니다.

| 항목 | 값 |
|---|---|
| Project Name | 소문자·숫자·`-`만. 이것이 곧 도메인이 된다 |
| Root Directory | **`frontend`** |
| Install Command | **`npm ci`** (아래 6번 참고) |
| Build Command | 비워 둔다 (Vite 자동 감지) |
| Output Directory | 비워 둔다 |

## 2. 환경변수

프론트가 쓰는 변수는 **하나뿐이다.**

| Key | Value | Type | Environments |
|---|---|---|---|
| `VITE_API_BASE_URL` | `https://wantedai-production.up.railway.app` | **Config** | Production and Preview |

- **`https://`를 반드시 붙인다.** 빼면 브라우저가 상대경로로 읽어서
  `https://docx-ray.vercel.app/wantedai-production.../samples`를 부르고 404가 난다.
- **Type은 Config다.** `VITE_` 접두사가 붙은 값은 빌드 때 JS 번들에 그대로
  박히므로 Secret으로 저장할 수 없다. 한 번 Secret으로 저장하면 Config로
  바꿀 수 없어서 지우고 다시 만들어야 한다.
- 끝의 `/`는 있어도 된다. `frontend/src/shared/api.js`가 떼어낸다.

저장소 루트의 `.env.example`은 **백엔드 것이다.** Vercel이 DB 비밀번호·API 키를
9개쯤 자동으로 끌어오는데 **전부 지운다.** 프론트는 DB에도 AI API에도 접속하지 않는다.

## 3. 백엔드 CORS 연결

Vercel 주소가 나오면 Railway의 `ALLOWED_ORIGINS`에 **추가한다. 교체가 아니다.**

```
ALLOWED_ORIGINS=https://docx-ray.vercel.app,http://localhost:5173
```

`http://localhost:5173`을 빼면 화면 담당이 로컬에서 배포된 백엔드를 못 부른다.
브랜치 미리보기(Preview)는 배포마다 주소가 달라서 등록할 수 없다 — 미리보기에서
업로드가 막히는 것은 고장이 아니다. 기능 확인은 로컬이나 운영 주소에서 한다.

로컬에서는 `http://localhost:5173`으로 연다. `http://127.0.0.1:5173`은 브라우저가
다른 주소로 취급해서 똑같이 막힌다.

## 4. 배포 확인

배포가 `Ready`여도 환경변수가 비어 있으면 코드 기본값(`http://127.0.0.1:8000`)으로
조용히 떨어진다. **빌드 성공은 정상 동작을 뜻하지 않는다.** 매번 이 한 줄로 확인한다.

```bash
curl -s https://docx-ray.vercel.app | grep -o 'assets/[^"]*\.js' | head -1 \
  | xargs -I{} curl -s https://docx-ray.vercel.app/{} | grep -o 'const ni="[^"]*"'
```

`https://wantedai-production.up.railway.app`가 나오면 성공,
`127.0.0.1`이 나오면 환경변수가 안 들어간 것이다.

그다음 브라우저에서 **샘플 체험 → 결과 → 마스킹 → 다운로드**를 한 번 끝까지 한다.
다운로드는 위 명령으로 확인되지 않는다.

## 5. 재배포가 필요한 때

| 바뀐 것 | 재배포 |
|---|---|
| 코드 (`main`에 push·머지) | 자동 |
| **환경변수** | **수동** — Vite는 빌드 때 값을 박으므로 저장만으로는 안 바뀐다 |
| **Vercel 프로젝트 설정** (Root Directory, Install Command 등) | **수동** |

Deployments → 맨 위 배포 → `···` → Redeploy.
이때 **`Use existing Build Cache` 체크를 푼다.** 캐시를 쓰면 옛 값이 남을 수 있다.

## 6. 패키지 매니저는 npm 하나로 고정

`frontend/`에 npm과 pnpm의 lockfile이 같이 있어서 Vercel이 설치는 npm으로,
빌드는 pnpm으로 돌리던 때가 있었다. `pnpm-lock.yaml`과 `pnpm-workspace.yaml`을
지워서 정리했다(2026-09-16, 화면 담당 확인).

**`frontend/`에는 `package-lock.json`만 둔다.** pnpm이나 yarn으로 설치하면
lockfile이 다시 생기므로 쓰지 않는다.

## 7. 제출과 관련해서

- **운영 주소는 제출 전에 확정한다.** 제출 마감(9/20) 이후에는 링크를 수정할 수
  없는데 Vercel 프로젝트 이름을 바꾸면 도메인이 같이 바뀐다.
- 배포 성공·실패 로그는 Vercel 대시보드 → Deployments에서 본다. Hobby 플랜은
  팀원을 초대할 수 없으므로, 다른 팀원은 **GitHub 커밋 옆 체크 표시**로 확인한다.
- 9/20 이후에도 사이트 자체는 고칠 수 있지만 **제출한 스크린샷이 박제되므로
  레이아웃·디자인은 바꾸지 않는다.** 버그 수정만 한다.
