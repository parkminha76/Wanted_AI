// 화면의 선택 마스킹 미리보기(src/shared/maskingRules.js)가 서버가 만든 사본과 같은지 확인한다.
//
//   백엔드를 켠 뒤 frontend 폴더에서:  npm run check:masking
//   서버 주소가 다르면:                 API_BASE_URL=http://... npm run check:masking
//
// 샘플 문서마다 두 가지 선택으로 POST /samples/mask를 불러, 서버가 돌려준 masked_text와
// 화면 미리보기 텍스트를 글자 단위로 비교한다. 하나라도 다르면 종료 코드 1.
//   1) 모든 항목 선택 — 부분 마스킹을 지원하는 유형은 부분, 나머지는 전체
//   2) 섞은 선택     — 항목을 하나씩 건너뛰며 빼고, 남은 항목은 부분/전체를 번갈아
//
// backend/scanner/masking/policy.py를 고친 뒤에는 반드시 돌린다.
import { maskedPreviewText } from '../src/shared/maskingRules.js'

const BASE_URL = (process.env.API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')

async function getJson(path, init) {
  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, init)
  } catch {
    throw new Error(`서버(${BASE_URL})에 연결할 수 없습니다. 백엔드를 먼저 켜 주세요.`)
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(`${path} ${response.status} ${JSON.stringify(body?.detail ?? body)}`)
  return body
}

function firstDifference(a, b) {
  const left = Array.from(a)
  const right = Array.from(b)
  const shared = Math.min(left.length, right.length)
  for (let i = 0; i < shared; i += 1) {
    if (left[i] !== right[i]) return i
  }
  return left.length === right.length ? -1 : shared
}

function around(text, index) {
  return JSON.stringify(Array.from(text).slice(Math.max(0, index - 20), index + 20).join(''))
}

try {
  const options = await getJson('/masking/options')
  const standardTypes = new Set(options.types.filter((item) => item.supports_standard).map((item) => item.type))
  const samples = await getJson('/samples')

  let checks = 0
  let failures = 0
  for (const result of samples.results) {
    if (result.findings.length === 0) {
      console.log(`- ${result.filename}: 탐지 항목 없음, 건너뜀`)
      continue
    }

    const scenarios = {
      '모든 항목': Object.fromEntries(
        result.findings.map((finding) => [finding.id, standardTypes.has(finding.type) ? 'standard' : 'full']),
      ),
      '섞은 선택': Object.fromEntries(
        result.findings
          .filter((_, index) => index % 2 === 0)
          .map((finding, index) => [finding.id, index % 2 === 0 && standardTypes.has(finding.type) ? 'standard' : 'full']),
      ),
    }

    for (const [name, selection] of Object.entries(scenarios)) {
      const selections = result.findings
        .filter((finding) => selection[finding.id])
        .map((finding) => ({
          id: finding.id,
          type: finding.type,
          start: finding.start,
          end: finding.end,
          action: selection[finding.id],
        }))
      const server = await getJson('/samples/mask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: result.filename, selections }),
      })
      const preview = maskedPreviewText(result.raw_text, result.findings, selection)

      checks += 1
      const at = firstDifference(server.masked_text, preview)
      if (at === -1) {
        const partial = selections.filter((row) => row.action === 'standard').length
        console.log(`✓ ${result.filename} · ${name} · ${selections.length}개 선택(부분 ${partial}) · 일치`)
      } else {
        failures += 1
        console.log(`✗ ${result.filename} · ${name} · ${at}번째 글자부터 다름`)
        console.log(`    서버: ${around(server.masked_text, at)}`)
        console.log(`    화면: ${around(preview, at)}`)
      }
    }
  }

  console.log(
    failures
      ? `\n불일치 ${failures}/${checks}건 — src/shared/maskingRules.js를 policy.py에 맞춰 고칠 것`
      : `\n전부 일치 (${checks}건)`,
  )
  process.exit(failures ? 1 : 0)
} catch (err) {
  console.error(err.message)
  process.exit(1)
}
