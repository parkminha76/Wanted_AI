# frontend — DocX-ray 화면

문서 검사(업로드 → 결과 → 상세 → 마스킹 사본)와 훈련 모드(AI 사기범 대화 → 리포트), 이용 가이드 화면.

## 실행

Node.js 18 이상(LTS 권장)이 필요하다. 백엔드는 저장소 루트에서 따로 띄운다.

```powershell
# 1) 백엔드 (저장소 루트)
uv run uvicorn backend.main:app --reload

# 2) 프론트 (frontend 폴더)
cd frontend
npm install
copy .env.example .env   # 서버 주소를 바꿀 때만. 비워 두면 http://127.0.0.1:8000
npm run dev              # http://localhost:5173
```

`package-lock.json`은 커밋한다. `node_modules/`, `dist/`, `.env`는 커밋하지 않는다.

## 구조 (Vite + React, JavaScript)

TypeScript·CSS 프레임워크(Tailwind 등)·UI 라이브러리·라우터 라이브러리 없이 React와 순수 CSS만 쓴다.
외부 폰트도 불러오지 않는다(설치된 한글 글꼴을 쓴다).

```text
frontend/
├── index.html
├── vite.config.js
├── .env.example                 VITE_API_BASE_URL 키 이름만
└── src/
    ├── main.jsx                 CSS 불러오는 순서: tokens -> base -> components
    ├── App.jsx                  # 주소로 화면 전환 + 화면 사이 데이터(메모리에만)
    ├── shared/
    │   ├── api.js               FastAPI 호출은 전부 여기로
    │   ├── findings.js          탐지 유형 묶음(개인정보·민감정보·숨겨진 명령어·기타), 위험 설명
    │   ├── useHashRoute.js
    │   ├── styles/tokens.css    색상·글꼴·간격 기준값 (DocX-ray 디자인)
    │   ├── styles/base.css      기본 스타일·레이아웃 유틸리티
    │   └── components/          Button, Card, Modal, RiskBadge, AppHeader
    ├── scanner/                 UploadPage, ScanningPage, ResultsPage, FindingDetailPage, MaskPage,
    │                            DocumentPreview, FileSwitcher, HiddenCommandModal
    ├── training/                TrainingHomePage, SimulationPage, ReportPage
    └── guide/                   GuidePage
```

| 주소 | 화면 | 서버 |
|---|---|---|
| `#/` | 문서 업로드, 샘플 문서로 체험하기 | — |
| `#/scanning` | 검사 중 (지난 시간 표시) | `POST /scan`, `GET /samples` |
| `#/results` | 위험도 요약, 문서 미리보기 + 탐지 항목, 오탐으로 제외한 항목, 숨은 명령 팝업 | (검사 결과 사용) |
| `#/results/detail` | 탐지 항목 상세 (왜 위험한가 · 판단 근거) | (검사 결과 사용) |
| `#/results/mask` | 마스킹 사본 미리보기, 다운로드 | `GET /download/{file_id}`, `GET /download/all` |
| `#/training` | 훈련 소개, 레벨 선택 | `GET /health`, `POST /training/start` |
| `#/training/play` | AI 사기범과 대화 (보내기 전 답장 검사) | `POST /scan/text`, `POST /training/{id}/reply` |
| `#/training/report` | 결과 리포트 (하단에 스캐너 전환) | `GET /training/{id}/report` |
| `#/guide` | 이용 가이드 | — |

## 공통 기준

- **색상·글꼴·간격은 `tokens.css` 변수만 쓴다.** 화면 CSS에 `#1769ed`, `13px` 같은 값을 직접 쓰지 않는다.
- **위험도 색은 서버가 준 `level`(high/medium/low)로 정한다.** 화면에서 점수로 구간을 다시 나누지 않는다 — 기준은 `backend/shared/schema.py`(60/25점) 한 곳이다.
- **유형 이름은 서버가 준 `finding.label`을 쓴다.** 화면의 네 묶음(개인정보 등)만 `shared/findings.js`에서 정한다.
- **탐지 위치 칠하기는 `raw_text` 기준이다.** `masked_text`는 오프셋이 달라서 하이라이트에 쓰지 않는다.
- **서버 호출은 `shared/api.js`만 거친다.** 실패하면 `ApiError`가 나고 `err.message`에 화면에 보여줄 한국어 문장이 들어 있다.

```js
import { api } from '../shared/api.js'

try {
  const batch = await api.scanFiles(files)      // POST /scan
} catch (err) {
  setError(err.message)                         // "파일이 너무 큽니다 (최대 20MB)" 등
}
```

- **검사 결과를 브라우저 저장소(localStorage 등)에 넣지 않는다.** 원문과 탐지 값이 들어 있다. 새로고침하면 사라지는 게 맞다.
- **공통 컴포넌트를 쓴다.** 버튼은 `Button`, 상자는 `Card`, 팝업은 `Modal`. 화면마다 버튼 스타일을 새로 만들지 않는다.

### 반응형·접근성

- 기준 폭 **375px**(모바일 우선), 600 / 768 / 960px에서 넓힌다.
- 누를 수 있는 요소는 **가로·세로 44px 이상** (`--touch-target`). 작은 버튼(`size="sm"`)도 높이는 지킨다.
- **가로 스크롤 금지.** 긴 파일명·값은 줄바꿈하고, 장식 그림은 `overflow: hidden` 상자 안에 가둔다.
  `body { overflow-x: hidden }`으로 덮지 않는다 — 잘린 내용이 안 보여서 문제를 숨긴다.
- 글자는 **12px 미만으로 쓰지 않는다.** 보조 글자색은 흰 바탕에서 4.5:1 이상 대비를 지킨다.
- 색만으로 구분하지 않는다 — 위험도 배지에는 항상 "높은 위험/주의/낮은 위험" 글자가 함께 나온다.
- 확인: 브라우저 개발자 도구에서 375px로 놓고 화면마다 가로 스크롤바가 생기지 않는지 본다.

## 아직 서버에 없는 것 (화면에서 대신 처리)

- **숨은 명령 "이 문장을 제거하고 사본 만들기"** — 문장 하나만 지우는 API가 없다. 마스킹 사본이 숨은 명령을 이미
  `[숨은 명령]`으로 바꿔 두므로 사본 화면으로 보낸다.
- **"이 파일 취소"** — 화면 목록에서만 뺀다. 서버 배치에는 남아 있어 전체 사본 zip에는 포함된다.
- **검사 진행률** — 서버가 알려주지 않아 가짜 퍼센트 대신 지난 시간과 검사 순서만 보여준다.
- **훈련 사용자** — 로그인이 없어 `DEMO_USER_ID = 1`로 시작한다(`training/TrainingHomePage.jsx`). DB에 이 사용자가 있어야 한다.

---

서비스 링크는 10월 5일까지 살아있어야 하므로 배포는 경량 모델/가벼운 인프라로 유지할 것.
