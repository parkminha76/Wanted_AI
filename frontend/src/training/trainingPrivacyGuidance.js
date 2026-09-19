const MASKED_FIELD_GUIDANCE = {
  PHONE: '전화번호나 인증번호는 제공하지 말고, 사내 메신저·대표번호 등 공식 채널로 담당자 신원을 확인하세요.',
  EMAIL: '이메일 주소는 전달하지 말고, 사내 주소록이나 공식 공지에 있는 연락처로 요청 사실을 확인하세요.',
  ACCOUNT: '계좌번호는 전달하거나 변경하지 말고, 등록된 거래처 연락처로 직접 확인한 뒤 내부 승인 절차를 따르세요.',
  CARD: '카드번호와 카드 관련 인증정보는 제공하지 말고, 카드사 공식 앱 또는 고객센터를 통해 확인하세요.',
  RRN: '주민등록번호는 어떤 상황에서도 전달하지 말고, 기관의 공식 연락처로 요청 사실을 확인하세요.',
}

const MASKED_FIELD_LABELS = {
  PHONE: '전화번호',
  EMAIL: '이메일 주소',
  ACCOUNT: '계좌번호',
  CARD: '카드번호',
  RRN: '주민등록번호',
}

// 이름·주소는 한국어 일반 문장과 겹칠 수 있어, "이름은 …"처럼 스스로 밝히는
// 문맥 또는 광역 지역명이 포함된 주소 표현만 보수적으로 안내 대상으로 삼는다.
const SELF_IDENTIFIED_NAME = /(?:제|내)?\s*이름(?:은|이|:)?\s*[가-힣]{2,4}/
const ADDRESS_DISCLOSURE = /(?:서울(?:특별시)?|부산(?:광역시)?|대구(?:광역시)?|인천(?:광역시)?|광주(?:광역시)?|대전(?:광역시)?|울산(?:광역시)?|세종(?:특별자치시)?|경기도|강원(?:특별자치)?도|충청[북남]도|전라[북남]도|경상[북남]도|제주(?:특별자치)?도)\s*[가-힣]{1,}/

export function displayMaskedText(text) {
  return String(text ?? '').replace(
    /\[(PHONE|EMAIL|ACCOUNT|CARD|RRN)\]/g,
    (_, field) => `[${MASKED_FIELD_LABELS[field]}]`,
  )
}

export function getRecommendedResponse(text) {
  const value = String(text ?? '')
  const field = Object.keys(MASKED_FIELD_GUIDANCE).find((key) => value.includes(`[${key}]`))
  if (field) return MASKED_FIELD_GUIDANCE[field]

  if (SELF_IDENTIFIED_NAME.test(value) || ADDRESS_DISCLOSURE.test(value)) {
    return '이름·주소 등 개인정보는 제공하지 말고, 요청한 기관이나 배송사의 공식 앱·대표번호를 통해 요청 사실을 확인하세요.'
  }

  return null
}
