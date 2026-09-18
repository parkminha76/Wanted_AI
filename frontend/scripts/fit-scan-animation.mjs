// 첫 화면 스캔 애니메이션(public/scan-animation/index.html)을 우리 화면 크기에 맞춘다.
//
//   npm run fit:animation        (frontend/ 에서)
//
// 왜 필요한가
// -----------
// 이 파일은 클로드 디자인에서 내보낸 원본을 그대로 쓴다. 원본은 무대 너비 1300px쯤을
// 가정하고 만들어졌는데, 우리는 첫 화면 오른쪽 칸(약 575px)에 넣기 때문에 탐지 결과
// 패널의 글자 폭이 200px 남짓밖에 안 된다. 원본 크기 그대로면 이름·생년월일·이메일이
// 전부 두 줄로 접힌다.
//
// 그래서 값마다 길이에 맞는 크기를 정해 둔다. 일괄로 줄이면 짧은 이름은 너무 작아지고
// 긴 주소는 여전히 넘치기 때문에 한 번에 같은 비율로 줄일 수가 없다.
//
// 디자인을 다시 내보내면 이 조정이 원본 값으로 되돌아간다. 그때 이 스크립트를 한 번
// 돌리면 된다. 두 번 돌려도 결과는 같다.
import { readFileSync, writeFileSync } from 'node:fs'

const FILE = 'public/scan-animation/index.html'

// 값 글씨 크기(px). 패널 글자 폭 약 200px에 한 줄로 들어가는 크기다.
// PROMPT INJECTION 항목은 만든 쪽에서 이미 작게(15) 잡아 두므로 여기서 다루지 않는다.
const SIZES = {
  rName: 30, rBirth: 24, rAddr: 14, rPhone: 24, rEmail: 15,
  cClient: 15, cCompany: 18, cCeo: 30, cBizNo: 24, cPhone: 24,
  cEmail: 16, cAccount: 17, cHolder: 18,
  iName: 30, iPhone: 24, iAccount: 17, iHolder1: 30, iHolder2: 30,
}

let html = readFileSync(FILE, 'utf8')

for (const [key, size] of Object.entries(SIZES)) {
  const pattern = new RegExp(`(key:'${key}'[^}]*zoom:)\\d+`)
  if (!pattern.test(html)) throw new Error(`${FILE}에 '${key}' 항목이 없다. 애니메이션 구성이 바뀌었는지 확인할 것.`)
  html = html.replace(pattern, (_, head) => head + size)
}

// 글씨가 작아진 만큼 패널도 함께 줄인다(여백만 남지 않게).
html = html.replace(
  /min-height:\d+px;display:flex;flex-direction:column;gap:\d+px;padding:\d+px \d+px/,
  'min-height:150px;display:flex;flex-direction:column;gap:12px;padding:20px 22px',
)

// 표에 없는 항목은 원본 크기 그대로 남는다 — 새 항목이 생겼다면 알려준다.
const unknown = [...html.matchAll(/key:'(\w+)'/g)]
  .map((m) => m[1])
  .filter((key) => !(key in SIZES) && !key.endsWith('Inject'))
if (unknown.length) console.warn(`[알림] 표에 없는 항목: ${unknown.join(', ')} — 크기를 확인할 것`)

writeFileSync(FILE, html)
console.log(`${FILE}: 값 ${Object.keys(SIZES).length}개 크기와 패널 여백 적용 완료`)
