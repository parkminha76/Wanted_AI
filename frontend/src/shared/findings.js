// 탐지 결과(Finding)를 화면에 보여줄 때 쓰는 규칙. 유형 이름 자체는 서버가 finding.label로 준다.

// 화면의 네 묶음. 타입 목록은 backend/shared/schema.py의 RiskType을 나눈 것이다.
export const GROUPS = {
  personal: {
    label: '개인정보',
    types: ['rrn', 'passport', 'driver_license', 'foreign_reg', 'person', 'address', 'phone', 'email', 'birth_date', 'emp_no', 'id_photo', 'signature', 'id_meta'],
  },
  sensitive: {
    label: '민감정보',
    types: ['account', 'card', 'api_key', 'db_credential'],
  },
  hidden: {
    label: '숨겨진 명령어',
    types: ['injection', 'hidden_text'],
  },
  other: {
    label: '기타',
    types: ['biz_reg', 'corp_reg', 'ip', 'org'],
  },
}

export const GROUP_ORDER = ['personal', 'sensitive', 'hidden', 'other']

export function groupOf(type) {
  return GROUP_ORDER.find((key) => GROUPS[key].types.includes(type)) ?? 'other'
}

export function countByGroup(findings = []) {
  const counts = Object.fromEntries(GROUP_ORDER.map((key) => [key, 0]))
  for (const finding of findings) counts[groupOf(finding.type)] += 1
  return counts
}

export const SOURCE_LABELS = {
  rule: '형식·체크섬 규칙',
  ner: '개체명 인식 모델',
  classifier: '직접 학습한 분류기',
  format: '문서 서식 검사',
  cnn: '이미지 탐지 모델',
}

const EXPLANATIONS = {
  rrn: '주민등록번호는 바꿀 수 없는 고유식별정보라 한 번 유출되면 되돌릴 수 없고, 명의 도용에 바로 쓰입니다.',
  passport: '여권번호는 법으로 처리가 제한된 고유식별정보입니다. 신분 위조나 명의 도용에 쓰일 수 있습니다.',
  driver_license: '운전면허번호는 법으로 처리가 제한된 고유식별정보입니다. 신분 확인을 속이는 데 쓰일 수 있습니다.',
  foreign_reg: '외국인등록번호는 주민등록번호와 같은 고유식별정보라 유출되면 되돌릴 수 없습니다.',
  account: '계좌번호는 이름·연락처와 함께 유출되면 사칭 송금 요구나 보이스피싱에 쓰입니다.',
  card: '카드번호는 유효기간 등과 결합되면 부정 결제로 바로 이어질 수 있습니다.',
  api_key: 'API 키가 유출되면 누구나 서비스에 접속해 데이터를 빼내거나 요금을 발생시킬 수 있습니다.',
  db_credential: 'DB 접속 정보가 유출되면 저장된 데이터 전체가 외부에 노출될 수 있습니다.',
  phone: '전화번호는 스팸·피싱의 표적이 되고, 다른 정보와 합쳐지면 신원을 특정할 수 있습니다.',
  email: '이메일은 피싱 메일의 표적이 되고, 계정 탈취 시도의 시작점이 됩니다.',
  person: '이름은 단독으로는 피해가 제한적이지만, 연락처·주소와 합쳐지면 특정 개인을 알아볼 수 있습니다.',
  address: '주소는 거주지를 드러내 방문·우편 사기나 신원 특정에 쓰일 수 있습니다.',
  birth_date: '생년월일은 본인 확인 질문에 자주 쓰여, 다른 정보와 합쳐지면 계정 복구를 악용할 수 있습니다.',
  emp_no: '사번은 사내 시스템 계정과 연결되는 경우가 많아 내부 사칭에 쓰일 수 있습니다.',
  injection: '이 문서를 AI 도구에 넣는 순간 AI가 이 지시를 따라 정보를 유출하거나 결과를 조작할 수 있습니다.',
  hidden_text: '사람 눈에는 보이지 않게 숨겨진 글입니다. AI나 검색 도구는 이 글을 그대로 읽습니다.',
  biz_reg: '사업자등록번호는 공개 조회가 가능해 위험도는 낮지만, 거래처 사칭에 쓰일 수 있습니다.',
  corp_reg: '법인등록번호는 공개 정보라 위험도는 낮지만, 거래처 사칭에 쓰일 수 있습니다.',
  ip: 'IP 주소는 내부 시스템 구조를 드러내 공격 준비에 쓰일 수 있습니다.',
  org: '조직명은 단독으로 위험하지 않지만, 이름·연락처와 합쳐지면 표적 사칭에 쓰일 수 있습니다.',
  id_photo: '신분증 얼굴 사진은 위조 신분증이나 비대면 본인 인증 도용에 쓰일 수 있습니다.',
  signature: '서명·도장 이미지는 계약서·위임장 위조에 쓰일 수 있습니다.',
  id_meta: '신분증 발급 정보는 다른 정보와 합쳐지면 신분 확인을 속이는 데 쓰일 수 있습니다.',
}

// 검사 항목 — 결과지의 "무엇을 검사했나"에 쓰는 여섯 묶음.
//
// backend/shared/schema.py의 _ACTION_GROUPS와 같은 구성이다. 그쪽은 RiskType 전체를
// 빠짐없이 한 번씩만 덮는지 import 시점에 assert로 확인하므로, 타입이 새로 생기면
// 서버가 먼저 깨진다. 여기 표는 그 결과를 화면 문구로 옮긴 것이다.
//
// 위의 GROUPS와는 쓰임이 다르다. GROUPS는 "무엇을 가릴까"(마스킹 화면에서 고르는 단위),
// CHECKS는 "무엇을 검사했나"(결과지에서 읽는 단위)다. 같은 타입이 양쪽에서 다르게
// 묶이는 것은 의도한 것이다 — 가리는 기준과 설명하는 기준이 같을 이유가 없다.
export const CHECKS = {
  ai_command: {
    label: '숨겨진 AI 명령',
    covers: '문서에 심어 둔 지시문 · 눈에 안 보이는 글자',
    tone: 'high',
    lead: '문서를 읽는 AI를 조종하는 명령이 심어져 있습니다',
    types: ['injection', 'hidden_text'],
  },
  credential: {
    label: '인증정보',
    covers: 'API 키 · 데이터베이스 접속정보',
    tone: 'high',
    lead: '서비스 계정 열쇠가 값 그대로 적혀 있습니다',
    types: ['api_key', 'db_credential'],
  },
  identity: {
    label: '고유식별정보',
    covers: '주민등록번호 · 여권 · 운전면허 · 외국인등록번호 · 신분증 이미지',
    tone: 'high',
    lead: '한 번 나가면 되돌릴 수 없는 신분 정보가 있습니다',
    types: ['rrn', 'foreign_reg', 'passport', 'driver_license', 'id_photo', 'signature', 'id_meta'],
  },
  financial: {
    label: '금융정보',
    covers: '계좌번호 · 카드번호',
    tone: 'high',
    lead: '계좌·카드 정보가 그대로 남아 있습니다',
    types: ['account', 'card'],
  },
  contact: {
    label: '연락처·신원',
    covers: '이름 · 전화번호 · 이메일 · 주소 · 생년월일 · 사번',
    tone: 'medium',
    lead: '개인을 알아볼 수 있는 정보가 남아 있습니다',
    types: ['person', 'phone', 'email', 'address', 'birth_date', 'emp_no'],
  },
  organization: {
    label: '조직·네트워크 정보',
    covers: '사업자등록번호 · 법인등록번호 · 조직명 · 내부 IP',
    tone: 'medium',
    lead: '조직과 사내 서버 정보가 드러납니다',
    types: ['biz_reg', 'corp_reg', 'org', 'ip'],
  },
}

// 심각한 것부터. 결과지의 검사 항목 목록과 문제 목록이 같은 순서를 쓴다.
export const CHECK_ORDER = ['ai_command', 'credential', 'identity', 'financial', 'contact', 'organization']

export function checkOf(type) {
  return CHECK_ORDER.find((key) => CHECKS[key].types.includes(type)) ?? 'organization'
}

export function countByCheck(findings = []) {
  const counts = Object.fromEntries(CHECK_ORDER.map((key) => [key, 0]))
  for (const finding of findings) counts[checkOf(finding.type)] += 1
  return counts
}

export function explanationFor(type) {
  return EXPLANATIONS[type] ?? '다른 정보와 합쳐지면 개인이나 조직을 특정하는 데 쓰일 수 있습니다.'
}

// 마스킹 사본에 들어가는 치환 문자열과 같은 모양. backend/shared/schema.py의 mask_placeholder()와 맞춘다.
export function placeholderFor(finding) {
  return `[${finding.label || '민감정보'}]`
}

export function formatPercent(value) {
  return `${Math.round((value ?? 0) * 100)}%`
}

// raw_text 기준 오프셋(start)이 몇 번째 줄인지. findings의 오프셋은 항상 raw_text 기준이다(schema.py).
export function lineNumberAt(text = '', offset = 0) {
  let line = 1
  for (let i = 0; i < Math.min(offset, text.length); i += 1) {
    if (text[i] === '\n') line += 1
  }
  return line
}

// 원문을 [일반 글, 탐지 구간, 일반 글, ...] 조각으로 나눈다. 조각마다 start/end(원문 기준 위치)를 함께 준다.
// 겹침 규칙은 서버 mask.py의 _ordered()와 같다 — 먼저 시작한 쪽, 같은 자리면 긴 쪽이 남고 겹친 뒤 구간은 버린다.
//
// 서버 오프셋은 파이썬 문자열 기준(코드포인트)이다. 이모지·유니코드 태그 문자처럼 JS가 두 칸(UTF-16)으로 세는
// 글자가 있으면 JS 인덱스와 어긋나므로, 그런 글자가 있을 때만 코드포인트 배열로 자른다.
export function buildSegments(text = '', findings = []) {
  const units = /[\uD800-\uDFFF]/.test(text) ? Array.from(text) : null
  const length = units ? units.length : text.length
  const slice = (start, end) => (units ? units.slice(start, end).join('') : text.slice(start, end))

  const sorted = [...findings]
    .filter((finding) => finding.start >= 0 && finding.end > finding.start && finding.end <= length)
    .sort((a, b) => a.start - b.start || b.end - a.end)

  const segments = []
  let cursor = 0
  for (const finding of sorted) {
    if (finding.start < cursor) continue
    if (finding.start > cursor) segments.push({ text: slice(cursor, finding.start), start: cursor, end: finding.start })
    segments.push({ text: slice(finding.start, finding.end), start: finding.start, end: finding.end, finding })
    cursor = finding.end
  }
  if (cursor < length) segments.push({ text: slice(cursor, length), start: cursor, end: length })
  return segments
}

// 조각 목록을 쪽별로 나눈다. pages는 서버 ScanResult.pages([{ page, start, end, label }]).
//   - 일반 글 조각이 쪽 경계를 넘으면 경계에서 자른다.
//   - 탐지·마스킹 조각은 자르지 않고 시작한 쪽에 넣는다(가린 값이 두 쪽으로 쪼개져 보이지 않게).
// 반환: [{ ...page, segments }]
export function splitByPages(segments, pages) {
  const buckets = pages.map((page) => ({ ...page, segments: [] }))
  const bucketAt = (offset) => buckets.find((bucket) => offset >= bucket.start && offset < bucket.end) ?? buckets[buckets.length - 1]

  for (const segment of segments) {
    if (segment.finding || segment.kind) {
      bucketAt(segment.start).segments.push(segment)
      continue
    }
    const units = /[\uD800-\uDFFF]/.test(segment.text) ? Array.from(segment.text) : null
    for (const bucket of buckets) {
      const from = Math.max(segment.start, bucket.start)
      const to = Math.min(segment.end, bucket.end)
      if (from >= to) continue
      const a = from - segment.start
      const b = to - segment.start
      bucket.segments.push({ ...segment, start: from, end: to, text: units ? units.slice(a, b).join('') : segment.text.slice(a, b) })
    }
  }
  return buckets
}
