# backend/scanner — 정보유출 스캐너 엔진

담당 **B (민하 · 윤정)**

파일을 넣으면 탐지 결과가 나오는 백엔드. `backend/shared/`에서 정한 계약을 구현하는 쪽.

한 줄로: **파일 → `ScanResult` (+ 마스킹 사본 파일)**
화면(D)도, 훈련 모드(C)도, 성능 지표(A)도 전부 이 출력 하나를 본다.

데이터 규격은 [`backend/shared/schema.py`](../shared/schema.py)에 정의되어 있다.
이 문서는 그 규격을 **무엇으로 채우는가**를 다룬다.

---

## 1. 만들 파일

```
backend/
  shared/
    schema.py          ✅ 완료   데이터 규격 (4명 공용 계약)
  scanner/
    parser/
      parse.py         ⬜   파일 → raw_text + 서식 정보(spans). 이미지/텍스트 라우팅도 여기
    detectors/
      rules.py         ⬜   정규식 + 체크섬 (형식이 고정된 값)
      hidden.py        ⬜   숨은 텍스트 탐지 (서식 속성 검사)
      ner.py           ⬜   한국어 NER (이름·주소·조직명)
      models.py        ⬜   ml/의 분류기 호출부 ← 껍데기는 B가, 알맹이는 A가
    masking/
      mask.py          ⬜   마스킹 사본 생성 (원본 형식 유지)
    scan.py            ⬜   위 전부를 순서대로 호출하는 오케스트레이터
  main.py              ⬜   FastAPI 앱. B가 만들고 C가 훈련 모드 라우터를 얹는다
```

### 두 사람이 나누는 선

같은 파일을 동시에 고치면 충돌만 난다. **파일 형식 계열 / 탐지 계열**로 자르는 게 이음매가 가장 적다.

| | 담당 | 성격 |
|---|---|---|
| **B-1 (파일)** | `parser/` · `masking/` · `detectors/hidden.py` | PDF/docx/xlsx 내부 구조를 다룬다. PyMuPDF·python-docx·openpyxl |
| **B-2 (탐지)** | `detectors/{rules,ner,models}.py` · `scan.py` · `main.py` | 텍스트에서 위험을 찾는다. 정규식·HuggingFace·FastAPI |

**두 사람 사이의 유일한 약속**은 `parse.py`의 출력 형식이다. 이것만 첫날 고정하면 이후에는 서로 안 봐도 된다.

```python
# parser/parse.py 출력 — 이 형식만 지키면 서로 독립적으로 작업 가능
@dataclass
class ParsedDoc:
    kind: str              # "text" | "image"  — 어느 파이프라인으로 보낼지
    raw_text: str          # 문서 전체 텍스트를 이어붙인 것. 모든 offset의 기준.
    spans: list[TextSpan]  # 서식 정보가 붙은 조각들 (숨은 텍스트 판정용)
    page_map: list[int]    # raw_text의 각 문자가 몇 페이지인지 (Finding.page 채울 때)

@dataclass
class TextSpan:
    text: str
    start: int             # raw_text 기준 offset
    end: int
    page: int
    font_size: float       # pt
    color: str             # "#ffffff"
    bg_color: str          # 그 위치의 실제 배경 채움색. 흰색으로 가정하지 않는다 (↓ 주의)
    render_mode: int       # PDF 전용. 3 = 화면에 안 그려짐
    opacity: float         # PDF 전용. 0.0 = 완전 투명 (색·크기·렌더모드 검사를 모두 통과한다)
    hidden_attr: bool      # docx의 vanish, xlsx의 hidden row/col 등
    bbox: tuple | None     # 마스킹 좌표 (PDF)
```

`bbox`가 여기 있는 이유: PyMuPDF는 탐지할 때 얻은 좌표를 **그대로 리댁션에 넘길 수 있다.** 탐지 따로, 마스킹 따로 좌표를 구하면 어긋난다.

`bg_color`를 흰색으로 가정하지 않는 이유: 파란 표 셀에 파란 글씨를 넣으면 "흰 배경 + 흰 글씨"만 보는
검사를 그냥 통과한다. 그래서 이 값은 상수가 아니라 **그 위치의 실제 채움색**이어야 하고, 그건 span을
뽑는 `parse.py`만 알 수 있다 (PDF는 도형·사각형 채움, XLSX는 셀 `fill`, DOCX는 문단·표 음영).
정말로 알아낼 수 없을 때만 흰색으로 두되, 그 사실을 `hidden.py`가 알 수 있어야 한다 —
"모르는 값"과 "진짜 흰색"을 구분하지 못하면 오탐이 난다.

---

## 2. 각 파일이 하는 일

### `parser/parse.py` — 파일을 텍스트로 푼다

**먼저 입력을 갈라야 한다.** 텍스트가 있는 문서(PDF/워드/엑셀)인지, 이미지(신분증·스캔본)인지 구분해서 각각 다른 파이프라인으로 보낸다 (`docs/`의 이미지/텍스트 하이브리드 파이프라인 참고). 이미지 쪽은 `ml/`의 CNN 탐지기가 받는다.

| 형식 | 라이브러리 | 주의점 |
|---|---|---|
| PDF | **PyMuPDF (fitz)** | `page.get_texttrace()`를 쓴다. `get_text()`가 아니다 — 아래 설명 |
| DOCX | python-docx | 본문 문단만 읽으면 안 된다. 표·머리말/꼬리말·텍스트상자·주석까지 |
| XLSX | openpyxl | 숨긴 시트, 숨긴 행/열, 셀 주석까지 |
| TXT/MD | 내장 | UTF-8, 인코딩 실패 시 cp949 재시도 |

**`get_texttrace()`를 쓰는 이유** — PDF에는 "글자를 배치하되 화면에는 그리지 않는" 렌더링 모드 3이 있다. 이건 글자색 검사도, 폰트 크기 검사도 둘 다 통과하면서 사람 눈에는 안 보인다. 숨은 명령을 심기에 가장 좋은 자리인데 `get_text()`나 pdfplumber로는 이 값이 안 나온다. `get_texttrace()`는 span마다 렌더 모드·색·크기·bbox를 다 준다.

**투명도 0도 같은 사각지대다.** 실제로 넣고 읽어보면 `color=(0,0,0)` `size=11` `type=0`으로
검사를 전부 통과하는데 `opacity=0.0`이라 화면에는 안 보인다. 렌더 모드와 함께 검사한다.

**offset 관리가 이 파일의 핵심이자 유일한 어려움이다.** `raw_text`를 만들면서 각 span이 몇 번째 문자에서 시작하는지 같이 기록해야 한다. 여기가 어긋나면 화면 하이라이트가 엉뚱한 글자에 칠해진다.

```python
raw_parts, spans, cursor = [], [], 0
for s in page_spans:
    raw_parts.append(s.text)
    spans.append(TextSpan(text=s.text, start=cursor, end=cursor + len(s.text), ...))
    cursor += len(s.text)
raw_text = "".join(raw_parts)
```

---

### `detectors/rules.py` — 형식이 고정된 값

필드를 하나로 뭉치지 않고 **종류별로 따로** 탐지한다. 각 필드는 **정규식 + 검증 함수** 한 쌍이다.

| 필드 | 패턴 | 검증 (오탐을 크게 줄여주는 부분) |
|---|---|---|
| 주민등록번호 | `\d{6}[-\s]?[1-4]\d{6}` | 생년월일 유효성 + 체크섬 |
| 외국인등록번호 | `\d{6}[-\s]?[5-8]\d{6}` | 뒷자리 첫 숫자 5~8 |
| 사업자등록번호 | `\d{3}-?\d{2}-?\d{5}` | 체크섬 |
| 법인등록번호 | `\d{6}-?\d{7}` | 체크섬 |
| 운전면허번호 | `\d{2}[-\s]?\d{2}[-\s]?\d{6}[-\s]?\d{2}` | 지역코드 유효 범위 |
| 여권번호 | `[MSRODmsrod]\d{8}` | 첫 글자 종류 |
| 카드번호 | `\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}` | **Luhn 알고리즘** |
| 계좌번호 | 은행별 자릿수 패턴 | 검증 불가 → **오탐 제거 분류기가 담당** |
| 휴대폰 | `01[016789][-\s]?\d{3,4}[-\s]?\d{4}` | — |
| 이메일 | 표준 패턴 | — |
| IP 주소 | IPv4 | 사설 대역 제외 옵션 |
| API 키/토큰 | `sk-…` `ghp_…` `AKIA…` `AIza…` JWT `Bearer …` | 접두어 목록 |
| DB 접속정보 | `postgres://` `mysql://` `mongodb://` URI | — |

> **체크섬 검증을 꼭 넣어라.** 이건 AI가 아니라 순수 규칙인데, 오탐의 절반 이상을 여기서 걷어낸다. 분류기가 감당할 짐이 줄고, "우리는 오탐을 겨냥한다"는 주장의 첫 번째 근거가 된다. 체크섬으로 걸러진 개수를 세어두면 그대로 발표 자료가 된다.

계좌번호처럼 검증할 방법이 없는 값(vs 주문번호·사번·송장번호)이 **오탐 제거 분류기가 존재하는 이유**다. B는 후보를 다 잡아서 넘기고, 최종 판정은 분류기가 한다. 헷갈리는 쌍은 필드마다 따로 있으므로, 분류기 검증도 필드별로 해야 한다.

---

### `detectors/hidden.py` — 서식으로 감춰진 텍스트

AI 모델이 전혀 필요 없는 규칙 검사인데, **데모에서 가장 임팩트가 큰 부분**이다.

| 형식 | 탐지 조건 |
|---|---|
| 공통 | 보이지 않는 유니코드 문자 — 제로폭 · Bidi 재정의 · 태그 문자 (아래 목록) |
| PDF | 렌더 모드 3 / **투명도 0** / 폰트 크기 < 2pt / 글자색 ≈ 배경색 / CropBox 밖 좌표 / 이미지에 가려진 z-order |
| DOCX | `w:vanish`(숨김 속성) / 글자색 `FFFFFF` / `w:sz` ≤ 4 (=2pt) / 머리말·꼬리말·텍스트상자 / 변경내용 추적·메모 |
| XLSX | 숨긴 행·열 / 숨긴 시트 — 특히 `veryHidden`(엑셀 UI에서 "숨기기 취소"조차 안 보인다) / 흰색 글꼴 / 사용자 지정 서식 `;;;` / 사용 범위 밖 셀 |

#### 보이지 않는 유니코드 문자

제로폭 4~6개만 보면 절반도 못 잡는다. 정규식 한 줄로 범위를 넓힌다.

```python
INVISIBLE = re.compile(
    "[\u200b-\u200f"          # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "\u202a-\u202e"           # Bidi 재정의 (Trojan Source)
    "\u2060-\u2064"           # word joiner, invisible operators
    "\u2066-\u2069"           # Bidi isolate
    "\ufeff\u00ad\u034f"      # BOM, soft hyphen, CGJ
    "\U000e0000-\U000e007f"   # 태그 문자
    "]"
)
```

두 범위가 특히 중요하다.

- **`\u202a-\u202e` Bidi 재정의** — 화면에 보이는 글자 순서와 파일에 저장된 순서를 다르게 만든다. 케임브리지 연구팀이 2021년 "Trojan Source"로 발표한 기법이다. 소스코드 공격으로 유명해졌지만 문서에도 그대로 통한다.
- **`\U000e0000-\U000e007f` 태그 문자** — 어떤 폰트로도 렌더링되지 않는 블록인데 ASCII를 1:1로 인코딩할 수 있다(`0xE0000`을 빼면 원래 ASCII가 나온다). 아스키 문장 하나를 통째로 투명하게 숨길 수 있어서, LLM 프롬프트 인젝션에서 실제로 쓰이는 최신 기법이다("ASCII smuggling"). 정규식 한 줄인데 발표에서 힘이 실린다.

#### ⚠️ 오탐 주의 — 문자 하나 발견을 위험으로 잡지 않는다

위 목록에는 **정상 문서에 널려 있는 문자가 섞여 있다.** 발견 즉시 신고하면 멀쩡한 파일이 전부 빨간불이 되고, "우리는 오탐을 겨냥한다"는 주장이 우리 손으로 무너진다.

그래서 문자를 **두 등급으로 나눈다.** 같은 규칙을 전부에 적용하면 안 된다.

**A급 — 정상 문서에 나올 이유가 없다.** 개수나 밀도만 넘어도 신고한다.

| 범위 | 무엇 |
|---|---|
| `U+202A ~ U+202E` | Bidi 재정의 (Trojan Source) |
| `U+2066 ~ U+2069` | Bidi isolate |
| `U+E0000 ~ U+E007F` | 태그 문자 (ASCII smuggling) |

**B급 — 정상 문서에 흔하다.** 개수·밀도를 넘어도 **복원까지 통과해야** 신고한다.

| 문자 | 정상적으로 나오는 이유 |
|---|---|
| `U+FEFF` BOM | UTF-8 파일 맨 앞에 아주 흔하다. 맨 앞 1개는 아예 세지 않는다 |
| `U+00AD` soft hyphen | 워드의 자동 하이픈. 정상 문서에 수십 개씩 들어 있다 |
| `U+200B` ZWSP | 줄바꿈 위치 지정용. 웹에서 복사해 붙이면 딸려온다 |
| `U+200C` ZWNJ | 아랍어·페르시아어·인도계 문자에서 정상적으로 쓴다 |
| `U+200E` `U+200F` LRM/RLM | 아랍어·히브리어가 섞인 문서에서 정상 |
| `U+2060 ~ U+2064` | 수식 조판에서 나온다 |
| `U+034F` CGJ | 정렬·검색 보정용 |
| `U+200D` ZWJ | **이모지 결합.** 함정 2 참고 — 별도 예외가 필요하다 |

**판정 규칙**

| 조건 | A급 | B급 |
|---|---|---|
| **개수** — 한 span/문단에 3개 이상 | 신고 | 다음 조건을 본다 |
| **밀도** — 한 span/문단에서 2% 초과 | 신고 | 다음 조건을 본다 |
| **복원** — 제거·디코드하면 의미 있는 문장이 나온다 | 신고 | **신고** |

복원이 가장 강한 근거다. 태그 문자는 `0xE0000`을 빼서 디코드하고 Bidi는 재정의를 걷어낸 뒤, 의미 있는 문장이 나오는지 본다. 나오면 개수·밀도와 무관하게 신고하고 그 문장을 `evidence`에 넣는다(숨은 명령 확인 화면이 그대로 보여준다). 나오지 않으면 서식 잡음으로 보고 버린다.

**3개 / 2%는 일단 정해둔 값이다.** 숨은 텍스트 샘플 8~10개와 정상 문서 대조군을 직접 돌려서, **놓치면 내리고 오탐이 나면 올리며** 맞춘다. 맞춘 뒤에는 최종 값과 맞춘 날짜를 이 문서에 적어둔다 — 심사에서 "왜 2%냐"를 물으면 그 실험이 답이다.

##### 함정 1 — 밀도의 분모를 문서 전체로 잡지 않는다

50,000자짜리 계약서에 제로폭 200개를 심어도 문서 전체 기준으로는 0.4%다. 그냥 통과한다.

숨은 명령은 한 자리에 뭉쳐 있으므로 **분모는 span 하나 또는 문단 하나**여야 한다. 그 문단만 떼어 보면 밀도가 확 올라간다.

반대로 짧은 span에서는 밀도가 의미가 없다(10자에 1개면 10%다). **50자 미만이면 밀도 판정을 건너뛰고 개수 규칙만 본다.**

##### 함정 2 — `U+200D`(ZWJ)는 이모지가 정상적으로 쓴다

가족 이모지 하나가 ZWJ 3개다. 전체 7자 중 3자니까 밀도 43%다. **이모지 하나만으로 개수와 밀도를 동시에 통과한다.**

특히 `scan_text()`는 C의 훈련 모드에서 실시간 채팅 답장을 검사한다. 짧은 메시지에 이모지 하나면 무조건 오탐이다.

→ ZWJ는 **앞뒤가 이모지면 세지 않는다.**

```python
# 변형 선택자(\ufe0f)와 피부색 수정자도 이모지 쪽에 포함시킨다.
# 하트+불꽃 이모지처럼 ZWJ 바로 앞이 \ufe0f인 조합이 있기 때문이다.
EMOJI = re.compile(
    "[\U0001f000-\U0001faff"     # 그림 이모지 대부분
    "\u2600-\u27bf\u2b00-\u2bff"   # 기호·화살표류
    "\ufe0f\U0001f3fb-\U0001f3ff"     # 변형 선택자, 피부색 수정자
    "]"
)

def is_emoji_zwj(text: str, i: int) -> bool:
    """이모지를 잇는 ZWJ면 True — 세지 않는다."""
    return (text[i] == "\u200d"
            and 0 < i < len(text) - 1
            and EMOJI.match(text[i - 1]) is not None
            and EMOJI.match(text[i + 1]) is not None)
```

정상 문서 대조군에서 **오탐 0건**을 확인하고 넘어간다. 그 숫자가 그대로 발표 자료가 된다.

#### 색 비교

정확히 같은 값만 보면 안 된다. `#fffffe` 같은 회피를 잡으려면 거리 임계값을 쓴다.

```python
def is_invisible_color(fg, bg, threshold=30):
    # 두 색의 RGB 거리가 threshold 미만이면 안 보이는 것으로 본다
```

**배경을 흰색으로 가정하지 않는다.** 파란 표 셀에 파란 글씨를 넣으면 "흰 배경 + 흰 글씨"만 보는 검사는 그냥 통과한다. `bg_color`는 상수가 아니라 그 위치의 **실제 채움색**이어야 하고, 그 값은 `parse.py`가 span을 뽑을 때 같이 뽑아줘야 한다 (PDF는 도형·사각형 채움, XLSX는 셀 `fill`, DOCX는 문단·표 음영).

숨은 텍스트를 찾으면 `type="hidden_text"`(25점)로 Finding을 만들고, **그 문장이 AI를 향한 명령인지**는 `models.is_injection()`에 물어서 참이면 `type="injection"`(50점)으로 **승격**한다.

⚠️ 승격은 **타입 교체**다. Finding을 두 개 만들면 한 문장이 75점을 받는다. 어떻게 숨겨져 있었는지는 `evidence`에 남긴다 — 숨은 명령 확인 화면이 그 값을 쓴다.

---

### `detectors/ner.py` — 이름·주소·조직명

정규식으로 잡을 수 없는 값. **직접 학습하지 않고 공개 모델을 그대로 쓴다** (제안서 확정 사항).

후보 (첫날 셋 다 돌려보고 하나 고른다):

| 모델 | 크기 | 비고 |
|---|---|---|
| `Leo97/KoELECTRA-small-v3-modu-ner` | 작음 ⭐ | 모두의말뭉치 기반. **배포 무게 때문에 1순위** |
| `KPF/KPF-bert-ner` | 중간 | 언론 기사 기반, 개체명 종류 많음 |
| `monologg/koelectra-base-v3-naver-ner` | 중간 | 네이버 NER 데이터셋 |

선택 기준은 정확도가 아니라 **정확도 ÷ 로딩시간**이다. 심사 링크가 10/5까지 살아 있어야 하고 무료 배포는 메모리가 좁다. 큰 모델을 골랐다가 배포가 안 되면 정확도는 의미가 없다.

- NER 태그(PS/LC/OG)를 schema의 `person / address / org`로 매핑한다.
- 주소는 NER만으로 부족하다 → `LC` 태그 + `(시|도|구|군|읍|면|동|로|길)\s?\d+` 패턴을 함께 본다.
- 모델은 **프로세스 시작 시 한 번만 로드**한다(전역 싱글턴). 요청마다 로드하면 매번 30초씩 걸린다.
- `confidence`는 모델의 softmax 값을 그대로 넣는다. 점수 계산식이 이 값을 곱하므로 불확실한 NER 결과는 자동으로 점수를 덜 흔든다.

---

### `detectors/models.py` — `ml/`의 분류기를 부르는 껍데기

**B가 먼저 만들고, A가 나중에 알맹이를 채운다.** 이 순서가 중요하다. B가 모델을 기다리면 아무것도 못 한다.

```python
# 인터페이스를 먼저 합의해서 고정할 것. 이후 시그니처 변경 금지.

def filter_false_positive(text, context, risk_type) -> tuple[bool, float]:
    """이 값이 진짜 개인정보인가?  반환: (진짜면 True, 확신도 0~1)
    모델이 준비되기 전에는 (True, 1.0)을 돌려준다 = 전부 통과."""

def is_injection(sentence) -> tuple[bool, float]:
    """이 문장이 AI에게 내리는 명령인가?  반환: (명령이면 True, 확신도 0~1)
    준비 전에는 키워드 목록으로 판정한다 ("무시하고", "시스템 프롬프트", ...)."""
```

**규칙: 모델이 없어도 엔진 전체가 돌아가야 한다.** 스텁이 있으면 B·C·D는 A와 무관하게 진행하고, A는 모델이 나오는 대로 함수 안쪽만 바꿔 끼운다.

`context`는 탐지된 값의 앞뒤 문장(대략 50자씩)을 넘긴다. "입금 계좌: 123-456" vs "주문번호: 123-456"에서 판단 근거가 되는 게 바로 이 앞뒤 글자다.

오탐으로 걸러낸 항목은 **버리지 말고 `ScanResult.filtered_out`에 담는다** — 화면의 "오탐으로 제외한 항목" 카드가 우리 모델의 유일한 가시적 증거다.

---

### `masking/mask.py` — 마스킹 사본

**원본 형식을 유지한 파일**을 돌려준다. 원본은 절대 건드리지 않고 사본만 만든다.

| 형식 | 방법 |
|---|---|
| PDF | PyMuPDF `add_redact_annot(bbox)` → `apply_redactions()`. **검은 사각형을 그리는 게 아니라 텍스트를 파일에서 실제로 지운다.** 덮기만 하면 복사·추출로 되살아난다 |
| DOCX | python-docx로 run 단위 문자열 치환 (서식 유지) |
| XLSX | openpyxl로 셀 값 치환 |
| TXT/MD | 문자열 치환 |

치환 문자열은 손으로 쓰지 말고 `schema.mask_placeholder()`를 쓴다. **유형을 남긴다**: `홍길동` → `[이름]`. `****`로 뭉개면 사본을 AI에 넣었을 때 문맥이 무너진다.

주 동작은 **다운로드**이고, 여러 파일은 `.zip`으로 묶어 한 번에 준다.

#### 함수는 둘이다

```python
def build(raw_text: str, findings: list[Finding]) -> str:
    """ScanResult.masked_text 용. 지금도 scan.py가 이걸 부르고 있다."""

def build_file(path: str, findings: list[Finding], out_dir: str) -> str:
    """마스킹 사본 파일을 만들고 그 경로를 돌려준다. ScanResult.masked_path에 들어간다."""
```

`build()`만으로는 부족하다. 제품의 주 동작이 **사본 파일 다운로드**이고 schema에 `masked_path` 필드가 이미 있다. 지금 `scan.py`는 `build()`만 부르므로, `scan_file()`에 `build_file()` 호출 한 줄이 더 필요하다.

#### ⚠️ `bbox`는 mask.py가 구하지 않는다

PDF 리댁션에는 좌표가 필요한데, `rules.py`·`ner.py`가 만든 Finding에는 offset(`start`/`end`)만 있고 좌표가 없다. offset을 좌표로 되짚는 일이 어딘가에서 일어나야 한다. **그 자리는 `mask.py`가 아니라 `scan.py`다.**

`Finding.bbox`는 4명이 함께 쓰는 공용 필드이고 `to_dict()`로 화면까지 나간다 (schema.py:269-276). `mask.py`가 좌표를 혼자 구해서 쓰고 버리면 `Finding.bbox`는 영원히 `null`로 남고, **D가 PDF 미리보기 위에 하이라이트 박스를 그릴 방법이 사라진다.**

그래서 이렇게 나눈다.

| 누가 | 무엇 |
|---|---|
| `parser/` (B-1) | offset → 좌표 매핑 함수를 제공한다. span 기하를 아는 쪽이라 여기 있어야 한다 |
| `scan.py` (B-2) | dedupe 직후 그 함수를 불러 `Finding.bbox`와 `Finding.page`를 채운다 |
| `masking/mask.py` (B-1) | `finding.bbox`를 **읽기만** 한다. 좌표를 다시 찾지 않는다 |

```python
# parser/locate.py — B-1이 제공
def rects_for(doc: ParsedDoc, start: int, end: int) -> list[tuple[float, float, float, float]]:
    """offset 구간과 겹치는 span들의 좌표를 돌려준다. 줄바꿈으로 갈라지면 여러 개다."""
```

**줄바꿈 주의.** 값 하나가 두 줄에 걸치면 사각형이 둘 필요하다. 그런데 `Finding.bbox`는 사각형 하나짜리 필드다. 합집합 하나로 지우면 그 사이의 멀쩡한 글자까지 지워진다.

**결정: 사각형은 여러 개로 담는다.** `bbox`의 타입을 리스트로 바꾸는 것은 공용 계약 변경이라
4명 합의가 필요하므로, 기존 필드는 그대로 두고 `evidence`에 나눠 담는다 — `evidence`는 자유
형식이라 계약을 건드리지 않는다.

```python
rects = locate.rects_for(doc, f.start, f.end)   # 줄마다 하나씩, 여러 개
if rects:
    f.bbox = union(rects)            # 화면 하이라이트용 — 합집합 하나 (기존 계약 유지)
    f.evidence["rects"] = rects      # 리댁션용 정밀 좌표 — 이쪽이 실제로 지우는 데 쓰인다
```

리댁션은 **반드시 `evidence["rects"]`를 순회**한다. `bbox` 하나로 지우면 두 줄에 걸친 값의
사이 글자까지 지워진다.

```python
for rect in f.evidence.get("rects") or ([f.bbox] if f.bbox else []):
    page.add_redact_annot(rect, text=f.placeholder)
page.apply_redactions()
```

---

### `scan.py` — 전부 이어 붙이기

```python
def scan_file(path):
    doc = parse.load(path)                                   # 1. 파싱 (+ 이미지/텍스트 분기)
    findings  = rules.detect(doc.raw_text)                   # 2. 정규식 + 체크섬
    findings += ner.detect(doc.raw_text)                     # 3. NER
    findings += hidden.detect(doc.spans)                     # 4. 서식 검사
    findings, filtered = models.apply_filters(findings, doc.raw_text)  # 5. 오탐 제거 + 인젝션
    findings  = dedupe(findings)                             # 6. 겹치는 구간 정리
    locate.fill_coords(doc, findings)                        # 7. offset -> bbox/page 채우기
    result = ScanResult(filename=..., raw_text=doc.raw_text,
                        findings=findings, filtered_out=filtered)
    result.masked_text = mask.build(result.raw_text, result.findings)   # 8. 텍스트 사본
    result.masked_path = mask.build_file(path, result.findings, tmp)    # 9. 파일 사본
    return result.finalize()                                 # 10. 위험 점수 계산
```

> **7·9번은 B-1이 낸 제안이다. `scan.py`는 B-2(민하) 담당이므로 확인을 거쳐 반영한다.**
> `Finding.bbox`/`page`를 채우는 자리와 파일 사본을 만드는 자리가 필요해서다.
> 7번을 빼면 마스킹은 되지만 화면이 좌표를 못 받는다 — 위 `mask.py` 절의 경고 참고.

**6번 중복 제거를 빠뜨리지 말 것.** 같은 글자를 정규식과 NER이 동시에 잡는 일이 흔하다(예: 이메일을 NER이 조직명으로도 잡음). 구간이 겹치면 가중치가 높은 쪽만 남긴다. 안 그러면 점수가 부풀려진다.

---

### `backend/main.py` — 바깥에서 부르는 창구

```
POST /scan          파일 여러 개 업로드 → ScanBatch JSON       (D가 호출)
POST /scan/text     문장 하나 → ScanResult JSON                (C의 실시간 답장 스캔)
GET  /download/{id} 마스킹 사본 파일 하나
GET  /download/all  전체 .zip
GET  /samples       심사위원용 샘플 4개를 미리 검사한 결과
GET  /health        살아있는지 확인 (배포 후 핑용)
```

`GET /samples`는 미리 계산해둔 JSON을 그대로 돌려줘도 된다 — 첫 화면에서 심사위원이 누를 버튼이라 **절대 느리면 안 된다.**

---

## 3. 잊지 말 것

- **업로드 파일은 처리 후 즉시 폐기** — 저장하면 안 됨 (개인정보 보호 서비스가 개인정보를 모으면 그 자체로 실격 사유). 임시 디렉터리에서 처리하고 응답 직후 삭제한다.
- **로그에도 원문을 남기지 않는다.** 탐지된 값은 `홍길동` 대신 `person(len=3)` 형태로 남긴다. `ScanResult.masked_path`는 응답 JSON에서 빠지도록 이미 처리되어 있다.
- **외부 LLM에 설명 생성을 맡길 때도 마스킹된 텍스트만 전달.**
- **필드는 하나로 뭉치지 말고 종류별로 따로 탐지** — 계좌번호 vs 주문번호처럼 헷갈리는 쌍이 필드마다 있어서, 오탐 제거 분류기도 필드별로 검증해야 한다.

---

## 4. 필요한 테스트 데이터

학습 데이터는 `ml/data_generation/` 담당이다. B에게 필요한 건 **테스트용 문서**다.

| 무엇 | 몇 개 | 만드는 법 |
|---|---|---|
| 데모 샘플 (심사위원용) | 4개 | 고객명단.xlsx / 개발문서(API키).md / 계약서.pdf / **숨은 명령이 심긴 docx** |
| 형식별 회귀 테스트 | 형식당 2~3개 | pdf, docx, xlsx, txt — 파싱이 안 깨지는지 확인용 |
| 숨은 텍스트 케이스 | 12~14개 | 흰 글씨 / 1pt / 제로폭 / 렌더모드3 / 숨긴 행 / `veryHidden` 시트 / `;;;` 서식 / Bidi 재정의 / 태그 문자 / 색 배경에 같은 색 글씨 — **하나씩 직접 만들어 봐야 탐지 코드를 짤 수 있다** |
| **오탐 대조군** | 5개 | 아무것도 숨기지 않은 정상 문서. BOM 있는 txt · 자동 하이픈(soft hyphen) 있는 워드 · 이모지 있는 문서 · 웹에서 복사해 붙인 문단 · 아랍어나 인도계 문자가 섞인 문서. **여기서 탐지가 0건이어야 통과다** |
| 오탐 평가셋 | 100건 | `ml/eval/`에 둔다. 계좌 vs 주문번호·사번·송장번호. **학습에 절대 쓰지 않는다** |

전부 Faker(ko_KR) + 직접 작성. **실제 개인정보는 한 건도 넣지 않는다.**

> 숨은 명령 샘플을 만드는 작업이 곧 `hidden.py` 개발이다. Word에서 글자색을 흰색으로 바꿔 저장한 뒤 그 파일을 파이썬으로 열어보는 것부터 시작하면 된다.

---

## 5. 진행 순서

| 순서 | 하는 일 | 왜 이 순서인가 |
|---|---|---|
| 1 | `detectors/models.py` **스텁**부터 | 이게 있어야 A를 안 기다린다 |
| 2 | `scan_text()`를 정규식만으로 동작시킨다 | C가 훈련 모드에서 바로 부를 수 있다 |
| 3 | `parser/parse.py` (txt → pdf → docx → xlsx 순) | 쉬운 형식부터. 한 형식이라도 되면 전체가 돈다 |
| 4 | `detectors/rules.py` 전체 필드 + 체크섬 | |
| 5 | `detectors/hidden.py` | 데모 임팩트 담당 |
| 6 | `detectors/ner.py` | 모델 로딩·배포 무게를 여기서 확인 |
| 7 | `masking/mask.py` | 사본 다운로드까지 |
| 8 | `backend/main.py` + D 연결 | |

**어떤 단계에서도 "완성 후 다음"으로 가지 않는다.** 텍스트 파일만 되는 상태여도 API까지 뚫어놓고, 그 다음에 형식을 늘린다.

---

## 6. 패키지

패키지 관리는 **uv**를 쓴다 (팀 규칙). `pip install`을 직접 치지 않는다.

```bash
uv sync                      # 저장소를 처음 받았을 때 / 남이 패키지를 추가한 뒤
uv add <패키지>              # 새로 추가할 때 (pyproject.toml을 손으로 고치지 않는다)
uv run python -m backend.main
```

추가한 뒤에는 **`pyproject.toml`과 `uv.lock`을 같이 커밋**하고 팀에 알린다. Python은 `.python-version`대로 **3.12**.
