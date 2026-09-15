# 사용자 선택형 마스킹 API

화면에서 탐지 항목을 보여준 뒤 사용자가 고른 항목만 마스킹하려면 아래의 2단계
흐름을 사용한다. 서버는 두 요청 사이에 원본을 보관하지 않는다. 브라우저가 처음
선택한 `File` 객체를 메모리에 가지고 있다가 두 번째 요청에서 다시 전송한다.

## 1단계: 탐지 결과 받기

```http
POST /scan
Content-Type: multipart/form-data
```

multipart 필드:

- `files`: 원본 파일
- `create_masked_copy`: `false`

`create_masked_copy=false`이면 탐지 결과의 `findings`만 반환하고 다운로드 사본은
만들지 않는다. 각 finding의 다음 필드를 화면 선택 상태와 함께 보관한다.

- `id`
- `type`
- `start`
- `end`

## 2단계: 선택한 항목으로 사본 만들기

```http
POST /mask
Content-Type: multipart/form-data
```

multipart 필드:

- `file`: 1단계에서 사용한 원본 `File` 객체
- `masking_selection`: 아래 형태의 JSON 문자열

```json
{
  "selections": [
    {
      "id": "f_001",
      "type": "phone",
      "start": 4,
      "end": 17,
      "action": "standard"
    },
    {
      "id": "f_003",
      "type": "rrn",
      "start": 32,
      "end": 46,
      "action": "full"
    }
  ]
}
```

- `full`: 탐지값 전체를 `[전화번호]` 같은 유형 라벨로 교체
- `standard`: 개인정보 유형별 표준 부분 마스킹 적용
- selections에 없는 finding은 사본에서 변경하지 않는다.
- 빈 selections는 허용하지 않는다.
- 서버가 같은 파일을 다시 탐지한 결과와 `id/type/start/end`가 하나라도 다르면
  다른 파일 또는 변경된 파일로 보고 HTTP 409를 반환한다.

성공 응답:

```json
{
  "file_id": "...",
  "filename": "upload.pdf",
  "file_type": "pdf",
  "selected_findings": 2,
  "download_url": "/download/..."
}
```

화면은 `download_url`을 사용해 선택 결과 사본을 내려받는다.

## JavaScript 연결 예시

```javascript
// file은 <input type="file">에서 받은 File 객체로 두 요청에 같은 객체를 사용한다.
const previewForm = new FormData();
previewForm.append("files", file);
previewForm.append("create_masked_copy", "false");

const preview = await fetch("/scan", {
  method: "POST",
  body: previewForm,
}).then((response) => response.json());

// 사용자가 체크한 findings와 선택한 action으로 구성한다.
const selections = checkedFindings.map((finding) => ({
  id: finding.id,
  type: finding.type,
  start: finding.start,
  end: finding.end,
  action: selectedAction[finding.id] ?? "full",
}));

const maskForm = new FormData();
maskForm.append("file", file);
maskForm.append("masking_selection", JSON.stringify({ selections }));

const masked = await fetch("/mask", {
  method: "POST",
  body: maskForm,
}).then((response) => response.json());

window.location.href = masked.download_url;
```

## 선택 화면의 기준표

```http
GET /masking/options
```

응답에는 각 `RiskType`의 라벨, 표준 부분 마스킹 지원 여부와 설명이 들어간다.
화면은 이 응답으로 전체/표준 선택지를 구성할 수 있다.

표준 부분 마스킹 지원 유형:

- 이름, 생년월일, 전화번호, 주소, 이메일
- 주민등록번호, 외국인등록번호, 법인등록번호
- 여권번호, 계좌번호, 운전면허번호, 카드번호, IPv4

API 키·DB 접속정보·숨은 명령·이미지 영역 등은 `standard`를 요청해도 전체
마스킹한다. 전화번호의 개인·법인 소유 여부는 번호만으로 판별할 수 없으므로
휴대전화와 유선전화 모두 뒤 4자리를 가린다.

## 업로드 전에 유형별 방식만 고르는 화면

결과를 보기 전에 유형별 방식만 정하는 화면이라면 기존 `POST /scan`에
`masking_policy` JSON 문자열을 함께 보내는 방식도 사용할 수 있다.

```json
{
  "default": "full",
  "rules": {
    "person": "standard",
    "phone": "standard"
  }
}
```

이 필드를 생략하면 기존처럼 모든 탐지값이 전체 마스킹된다.

