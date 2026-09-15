// 표준 부분 마스킹 규칙 — backend/scanner/masking/policy.py의 standard_mask()를 그대로 옮긴 것.
//
// 왜 화면에 두 벌이 있는가: 선택 마스킹에서 "부분"을 고르는 순간 미리보기에 "010-2310-****" 모양을
// 보여주려면, 체크할 때마다 서버를 부르지 않고 화면에서 바로 계산해야 한다.
// 대신 서버 규칙과 어긋나면 미리보기와 실제 사본이 달라진다. policy.py를 고치면 이 파일도 같이 고치고,
// `npm run check:masking`(서버를 켠 상태)으로 샘플 문서 전체가 서버 사본과 글자 하나까지 같은지 확인한다.
//
// 파이썬 문자열 판정과 맞춘 대응표:
//   str.isdigit() -> \p{Nd}   str.isalpha() -> \p{L}   str.isalnum() -> \p{L}|\p{N}   str.isspace() -> \s
// 글자 수는 코드포인트 기준(Array.from)으로 센다 — 파이썬 len()과 같게.

import { buildSegments, placeholderFor } from './findings.js'

const DIGIT = /^\p{Nd}$/u
const ALPHA = /^\p{L}$/u
const ALNUM = /^[\p{L}\p{N}]$/u
const SPACE = /^\s$/u
const HANGUL = /[가-힣]/

const chars = (value) => Array.from(value)

function maskAfterNDigits(value, visibleDigits) {
  let seen = 0
  return chars(value)
    .map((char) => {
      if (!DIGIT.test(char)) return char
      seen += 1
      return seen <= visibleDigits ? char : '*'
    })
    .join('')
}

function maskDigitPositions(value, start, end) {
  let index = 0
  return chars(value)
    .map((char) => {
      if (!DIGIT.test(char)) return char
      const masked = start <= index && index < end ? '*' : char
      index += 1
      return masked
    })
    .join('')
}

function maskPerson(value) {
  if (HANGUL.test(value)) {
    // 한글 이름: 단어마다 첫 글자만 남긴다.
    let visible = false
    return chars(value)
      .map((char) => {
        if (SPACE.test(char) || !(ALPHA.test(char) || DIGIT.test(char))) {
          visible = false
          return char
        }
        if (!visible) {
          visible = true
          return char
        }
        return '*'
      })
      .join('')
  }
  // 영문 이름: 앞 2글자만 남긴다.
  let remaining = 2
  return chars(value)
    .map((char) => {
      if (!ALPHA.test(char)) return char
      if (remaining) {
        remaining -= 1
        return char
      }
      return '*'
    })
    .join('')
}

function maskEmail(value) {
  const at = value.lastIndexOf('@')
  if (at < 0) return value
  const local = chars(value.slice(0, at))
  const domain = value.slice(at + 1)
  const visible = local.length <= 3 ? 1 : 3
  return `${local.slice(0, visible).join('')}${'*'.repeat(Math.max(0, local.length - visible))}@${domain}`
}

function maskAddress(value) {
  const parts = value.split(/\s+/u).filter(Boolean) // 파이썬 str.split()과 같게 빈 조각을 버린다
  if (parts.length <= 3) return value
  return `${parts.slice(0, 3).join(' ')} ****`
}

function maskIp(value) {
  const parts = value.split('.')
  if (parts.length !== 4 || !parts.every((part) => part.length > 0 && chars(part).every((char) => DIGIT.test(char)))) {
    return value
  }
  parts[2] = '***'
  return parts.join('.')
}

function maskPassport(value) {
  let seen = 0
  return chars(value)
    .map((char) => {
      if (!ALNUM.test(char)) return char
      seen += 1
      return seen <= 6 ? char : '*'
    })
    .join('')
}

/**
 * 표준 부분 마스킹 결과. 규칙이 없는 유형이거나 가릴 게 없으면 전체 마스킹 문자열(fallback)을 돌려준다.
 * policy.py와 같이 "아무것도 못 가리는 부분 마스킹"은 전체 마스킹으로 떨어진다(fail closed).
 */
export function standardMask(riskType, value, fallback) {
  if (!value) return fallback

  let masked
  switch (riskType) {
    case 'person':
      masked = maskPerson(value)
      break
    case 'birth_date':
      masked = maskAfterNDigits(value, 4)
      break
    case 'phone': {
      const digitCount = chars(value).filter((char) => DIGIT.test(char)).length
      masked = maskDigitPositions(value, Math.max(0, digitCount - 4), digitCount)
      break
    }
    case 'address':
      masked = maskAddress(value)
      break
    case 'email':
      masked = maskEmail(value)
      break
    case 'rrn':
    case 'foreign_reg':
    case 'corp_reg':
      masked = maskAfterNDigits(value, 7)
      break
    case 'passport':
      masked = maskPassport(value)
      break
    case 'account':
      masked = maskAfterNDigits(value, 6)
      break
    case 'driver_license':
      masked = maskAfterNDigits(value, 4)
      break
    case 'card':
      masked = maskDigitPositions(value, 4, 12)
      break
    case 'ip':
      masked = maskIp(value)
      break
    default:
      return fallback
  }

  return masked !== value && masked.includes('*') ? masked : fallback
}

/**
 * 선택 마스킹 미리보기 조각. 서버 mask.build()와 같은 규칙으로 가릴 구간과 치환 글자를 정한다.
 *   - 가릴 구간은 **선택한 항목끼리만** 겹침을 정리한다. 서버도 선택한 항목만 넘겨받아 정리한다
 *     (선택하지 않은 항목이 섞이면 겹친 구간에서 서버와 다른 쪽이 남는다).
 *   - 선택하지 않은 항목은 가리지 않고, 가린 구간 밖에 온전히 있을 때만 "가리지 않음" 표시를 붙인다.
 *
 * selection: { [finding.id]: 'full' | 'standard' }
 * 반환: [{ text, start, end, kind?: 'full' | 'standard' | 'excluded', finding? }]
 *   text는 화면에 보일 글자, start/end는 원문(raw_text) 기준 위치 — 쪽 나누기(splitByPages)에 쓴다.
 */
export function buildSelectionSegments(text = '', findings = [], selection = {}) {
  const selected = findings.filter((finding) => selection[finding.id])
  const excluded = findings.filter((finding) => !selection[finding.id])
  const segments = []

  for (const segment of buildSegments(text, selected)) {
    const { finding } = segment
    if (finding) {
      const kind = selection[finding.id] === 'standard' ? 'standard' : 'full'
      const fallback = placeholderFor(finding)
      segments.push({
        finding,
        kind,
        start: segment.start,
        end: segment.end,
        text: kind === 'standard' ? standardMask(finding.type, finding.text, fallback) : fallback,
      })
      continue
    }

    const inside = excluded
      .filter((item) => item.start >= segment.start && item.end <= segment.end)
      .map((item) => ({ ...item, start: item.start - segment.start, end: item.end - segment.start }))
    for (const piece of buildSegments(segment.text, inside)) {
      const position = { start: segment.start + piece.start, end: segment.start + piece.end }
      segments.push(
        piece.finding
          ? { text: piece.text, kind: 'excluded', finding: piece.finding, ...position }
          : { text: piece.text, ...position },
      )
    }
  }
  return segments
}

/** 선택 마스킹을 적용한 텍스트 전체. 서버 /mask·/samples/mask 응답의 masked_text와 같아야 한다. */
export function maskedPreviewText(text, findings, selection) {
  return buildSelectionSegments(text, findings, selection)
    .map((segment) => segment.text)
    .join('')
}
