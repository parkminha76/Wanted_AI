import fontkit from '@pdf-lib/fontkit'
import { PDFDocument, rgb } from 'pdf-lib'
import { displayMaskedText, getRecommendedResponse } from './trainingPrivacyGuidance.js'

const PAGE = { width: 595.28, height: 841.89 }
// Layout knobs: keep all A4 spacing and typography adjustments in one place.
const MARGIN = 46
const CONTENT_WIDTH = PAGE.width - MARGIN * 2
const LAYOUT = {
  sectionGap: 18,
  cardPadding: 18,
  titleSize: 30,
  bodySize: 10.5,
  bodyLineHeight: 14.8,
  itemSize: 9.6,
  itemLineHeight: 13.6,
  wordGapRatio: 0.34,
}
const CONVERSATION_LAYOUT = {
  top: 666,
  bottom: 54,
  cardPadding: 14,
  labelSize: 9,
  labelHeight: 11,
  labelGap: 9,
  bodySize: 10.2,
  lineHeight: 15.2,
  cardGap: 12,
}
const COLORS = {
  navy: rgb(0.04, 0.08, 0.12),
  text: rgb(0.035, 0.055, 0.075),
  muted: rgb(0.31, 0.37, 0.43),
  green: rgb(0.18, 0.62, 0.72),
  cyanStrong: rgb(0.015, 0.37, 0.52),
  greenSoft: rgb(0.91, 0.97, 0.985),
  greenBorder: rgb(0.72, 0.88, 0.92),
  adviceGreen: rgb(0.14, 0.52, 0.30),
  adviceGreenSoft: rgb(0.92, 0.98, 0.93),
  adviceGreenBorder: rgb(0.62, 0.82, 0.67),
  red: rgb(0.82, 0.173, 0.235),
  redSoft: rgb(1, 0.945, 0.949),
  redBorder: rgb(0.965, 0.831, 0.847),
  border: rgb(0.86, 0.89, 0.92),
  surface: rgb(0.955, 0.975, 0.985),
  white: rgb(1, 1, 1),
}

const GRADE_TONE = {
  '안전': COLORS.green,
  '양호': COLORS.green,
  '주의': COLORS.red,
  '위험': COLORS.red,
}

function drawCenteredText(page, font, text, { centerX, y, size, color, bold = false }) {
  const value = String(text ?? '-')
  const options = { x: centerX - font.widthOfTextAtSize(value, size) / 2, y, size, font, color }
  page.drawText(value, options)
  // The embedded Korean font has a single weight. A subtle second pass gives
  // metric-heavy score values the visual hierarchy of a bold face.
  if (bold) {
    page.drawText(value, { ...options, x: options.x + 0.65 })
    page.drawText(value, { ...options, y: options.y + 0.18 })
  }
}

function drawRoundedRect(page, { x, y, width, height, radius = 10, color, borderColor, borderWidth = 0 }) {
  page.drawRectangle({ x: x + radius, y, width: width - radius * 2, height, color })
  page.drawRectangle({ x, y: y + radius, width, height: height - radius * 2, color })
  for (const [cx, cy] of [
    [x + radius, y + radius],
    [x + width - radius, y + radius],
    [x + radius, y + height - radius],
    [x + width - radius, y + height - radius],
  ]) {
    page.drawCircle({ x: cx, y: cy, size: radius, color })
  }
  if (borderWidth > 0) {
    page.drawRectangle({ x, y, width, height, borderColor, borderWidth, opacity: 0 })
  }
}

function wrapText(font, text, size, maxWidth) {
  const lines = []
  let line = ''
  // Keep Korean eojeol (word units) intact.  Character-by-character wrapping
  // caused endings such as "했 / 습니다" to split across lines.
  const safeWidth = maxWidth * 0.76
  const paragraphs = String(text ?? '').split('\n')
  for (const paragraph of paragraphs) {
    for (const word of paragraph.trim().split(/\s+/).filter(Boolean)) {
      const candidate = line ? `${line} ${word}` : word
      if (line && textWidth(font, candidate, size) > safeWidth) {
        lines.push(line)
        line = word
      } else {
        line = candidate
      }
    }
    if (line) lines.push(line)
    line = ''
  }
  if (!lines.length) lines.push('')
  return lines
}

function wrapConversationText(font, text, size, maxWidth) {
  const lines = []

  const pushLongWord = (word) => {
    let part = ''
    for (const character of word) {
      const candidate = `${part}${character}`
      if (part && font.widthOfTextAtSize(candidate, size) > maxWidth) {
        lines.push(part)
        part = character
      } else {
        part = candidate
      }
    }
    return part
  }

  String(text ?? '').split('\n').forEach((paragraph) => {
    const words = paragraph.trim().split(/\s+/).filter(Boolean)
    if (!words.length) {
      lines.push('')
      return
    }

    let line = ''
    words.forEach((word) => {
      const candidate = line ? `${line} ${word}` : word
      if (font.widthOfTextAtSize(candidate, size) <= maxWidth) {
        line = candidate
        return
      }
      if (line) lines.push(line)
      line = font.widthOfTextAtSize(word, size) <= maxWidth
        ? word
        : pushLongWord(word)
    })
    if (line) lines.push(line)
  })

  return lines.length ? lines : ['']
}

function textWidth(font, text, size) {
  const words = String(text).split(' ')
  return words.reduce((width, word, index) => (
    width + font.widthOfTextAtSize(word, size) + (index ? size * LAYOUT.wordGapRatio : 0)
  ), 0)
}

function drawWordSpacedText(page, font, text, { x, y, size, color }) {
  let cursorX = x
  String(text).split(' ').forEach((word, index) => {
    if (index) cursorX += size * LAYOUT.wordGapRatio
    page.drawText(word, { x: cursorX, y, size, font, color })
    cursorX += font.widthOfTextAtSize(word, size)
  })
}

function compactKoreanSpacing(text) {
  return String(text ?? '').replace(/[ \t]+/g, ' ')
}

function fittedText(font, text, maxWidth, maxHeight, preferredSize = 11, minSize = 8.5, lineRatio = 1.42) {
  for (let size = preferredSize; size >= minSize; size -= 0.5) {
    const lines = wrapText(font, text, size, maxWidth)
    const lineHeight = size * lineRatio
    if (lines.length * lineHeight <= maxHeight) return { lines, size, lineHeight }
  }
  const size = minSize
  return { lines: wrapText(font, text, size, maxWidth), size, lineHeight: size * lineRatio }
}

function drawLines(page, font, lines, { x, y, size, lineHeight, color = COLORS.text }) {
  lines.forEach((line, index) => {
    drawWordSpacedText(page, font, compactKoreanSpacing(line), { x, y: y - index * lineHeight, size, color })
  })
  return y - lines.length * lineHeight
}

function drawCardList(page, font, items, { x, y, width, height, tone, emptyMessage }) {
  const accent = tone === 'red' ? COLORS.red : COLORS.green
  const values = items?.length ? items : [emptyMessage]
  const rowHeight = Math.min(31, height / Math.max(values.length, 1))
  values.forEach((item, index) => {
    const cy = y - index * rowHeight
    drawCircleIcon(page, font, {
      x, y: cy, color: accent, symbol: tone === 'red' ? '!' : '✓', size: 7.5,
    })
    drawParagraph(page, font, item, {
      x: x + 18, y: cy - 3, width, height: rowHeight + 5,
      size: LAYOUT.itemSize, minSize: 7.5, lineRatio: LAYOUT.itemLineHeight / LAYOUT.itemSize, color: COLORS.text,
    })
  })
}

function drawCircleIcon(page, font, { x, y, color, symbol, size = 18 }) {
  page.drawCircle({ x, y, size, color })
  const symbolSize = size * 1.08
  const symbolWidth = font.widthOfTextAtSize(symbol, symbolSize)
  page.drawText(symbol, {
    x: x - symbolWidth / 2,
    y: y - symbolSize * 0.34,
    size: symbolSize,
    font,
    color: COLORS.white,
  })
}

// PDF는 HTML 아이콘을 사용할 수 없으므로, 리포트 의미에 맞는 선 아이콘을
// pdf-lib 도형으로 직접 그린다. 원형 배경과 Icy Blue 색상은 기존과 동일하다.
function drawReportIcon(page, { x, y, color, kind, size = 16 }) {
  const stroke = COLORS.white
  const line = (start, end, thickness = 1.35) => page.drawLine({
    start, end, thickness, color: stroke, lineCap: 1,
  })

  page.drawCircle({ x, y, size, color })

  if (kind === 'clipboard-check') {
    const left = x - size * 0.31
    const bottom = y - size * 0.39
    const width = size * 0.62
    const height = size * 0.8
    page.drawRectangle({
      x: left, y: bottom, width, height,
      borderColor: stroke, borderWidth: 1.25, opacity: 0,
    })
    page.drawRectangle({
      x: x - size * 0.17, y: y + size * 0.28,
      width: size * 0.34, height: size * 0.16,
      borderColor: stroke, borderWidth: 1.15, opacity: 0,
    })
    line({ x: x - size * 0.2, y: y - size * 0.03 }, { x: x - size * 0.04, y: y - size * 0.2 })
    line({ x: x - size * 0.04, y: y - size * 0.2 }, { x: x + size * 0.26, y: y + size * 0.1 })
    return
  }

  if (kind === 'shield-check') {
    const top = y + size * 0.39
    const bottom = y - size * 0.38
    const left = x - size * 0.37
    const right = x + size * 0.37
    line({ x, y: top }, { x: right, y: y + size * 0.23 })
    line({ x: right, y: y + size * 0.23 }, { x: x + size * 0.26, y: bottom + size * 0.13 })
    line({ x: x + size * 0.26, y: bottom + size * 0.13 }, { x, y: bottom })
    line({ x, y: bottom }, { x: x - size * 0.26, y: bottom + size * 0.13 })
    line({ x: x - size * 0.26, y: bottom + size * 0.13 }, { x: left, y: y + size * 0.23 })
    line({ x: left, y: y + size * 0.23 }, { x, y: top })
    line({ x: x - size * 0.2, y: y - size * 0.01 }, { x: x - size * 0.04, y: y - size * 0.17 })
    line({ x: x - size * 0.04, y: y - size * 0.17 }, { x: x + size * 0.23, y: y + size * 0.11 })
  }
}

function drawVerticalDivider(page, x, y, height) {
  page.drawLine({
    start: { x, y }, end: { x, y: y + height },
    thickness: 0.9, color: COLORS.border,
  })
}

function drawParagraph(page, font, text, options) {
  const fitted = fittedText(
    font, text, options.width, options.height, options.size, options.minSize,
    options.lineRatio ?? LAYOUT.bodyLineHeight / LAYOUT.bodySize,
  )
  return drawLines(page, font, fitted.lines, {
    x: options.x,
    y: options.y,
    size: fitted.size,
    lineHeight: fitted.lineHeight,
    color: options.color,
  })
}

function drawHeader(page, font, logo) {
  // Keep the supplied logo's original 1513:1037 aspect ratio.
  const logoHeight = 94
  const logoWidth = logoHeight * (1513 / 1037)
  page.drawImage(logo, { x: MARGIN - 10, y: 744, width: logoWidth, height: logoHeight })
  const right = PAGE.width - MARGIN
  const lineOne = 'AI SECURITY'
  const lineTwo = 'TRAINING REPORT'
  const lineThree = '당신의 안전한 내일을 위한 한 걸음'
  page.drawText(lineOne, { x: right - font.widthOfTextAtSize(lineOne, 9.5), y: 795, size: 9.5, font, color: COLORS.text })
  page.drawText(lineTwo, { x: right - font.widthOfTextAtSize(lineTwo, 9.5), y: 778, size: 9.5, font, color: COLORS.text })
  drawWordSpacedText(page, font, lineThree, { x: right - textWidth(font, lineThree, 7.5), y: 760, size: 7.5, color: COLORS.muted })
  page.drawLine({ start: { x: MARGIN, y: 738 }, end: { x: PAGE.width - MARGIN, y: 738 }, thickness: 1.5, color: COLORS.green })
}

function drawFooter(page, font, pageNumber, pageCount) {
  const label = `${String(pageNumber).padStart(2, '0')} / ${String(pageCount).padStart(2, '0')}`
  page.drawText(label, {
    x: PAGE.width - MARGIN - font.widthOfTextAtSize(label, 8.5),
    y: 24,
    size: 8.5,
    font,
    color: COLORS.muted,
  })
}

function drawList(page, font, items, options) {
  const values = items?.length ? items : [options.emptyMessage]
  const text = values.map((item) => `${options.marker} ${item}`).join('\n')
  return drawParagraph(page, font, text, options)
}

function drawSectionCard(page, font, { x, y, width, height, title, icon, items, tone, numbered = false, emptyMessage }) {
  const accent = tone === 'red' ? COLORS.red : COLORS.green
  const soft = tone === 'red' ? COLORS.redSoft : COLORS.greenSoft
  const border = tone === 'red' ? COLORS.redBorder : COLORS.greenBorder
  drawReportIcon(page, { x: x + 23, y: y + height + 20, color: accent, kind: icon, size: 16 })
  drawWordSpacedText(page, font, compactKoreanSpacing(title), { x: x + 48, y: y + height + 13, size: 14, color: COLORS.text })
  const guide = tone === 'red' ? '다음에는 이런 점을 더 주의하세요.' : numbered ? '이런 방법을 기억해보세요.' : '어떤 습관이 안전한 디지털 생활을 만듭니다.'
  const guideWidth = font.widthOfTextAtSize(guide, 8)
  drawWordSpacedText(page, font, compactKoreanSpacing(guide), { x: x + width - guideWidth, y: y + height + 15, size: 8, color: accent })
  drawRoundedRect(page, { x, y, width, height, radius: 11, color: soft, borderColor: border, borderWidth: 0 })
  const values = items?.length ? items : [emptyMessage]
  const rowHeight = Math.min(31, (height - 22) / Math.max(values.length, 1))
  values.forEach((item, index) => {
    const cy = y + height - 23 - index * rowHeight
    if (numbered) {
      page.drawCircle({ x: x + 27, y: cy + 1, size: 12, color: COLORS.greenBorder })
      page.drawText(String(index + 1), { x: x + 23.5, y: cy - 3.5, size: 10, font, color: COLORS.green })
    } else {
      drawCircleIcon(page, font, { x: x + 27, y: cy + 1, color: accent, symbol: tone === 'red' ? '!' : '✓', size: 8 })
    }
    drawParagraph(page, font, item, {
      x: x + 49, y: cy - 3, width: width - 68, height: rowHeight + 8,
      size: LAYOUT.itemSize, minSize: 7.5, lineRatio: LAYOUT.itemLineHeight / LAYOUT.itemSize, color: COLORS.text,
    })
  })
}

function drawPageOne(page, font, logo, report, generatedDate) {
  const scoreLabel = report.score == null ? '점수 없음' : `${report.score} / 100`
  drawHeader(page, font, logo)
  drawWordSpacedText(page, font, '사기 대응 훈련 결과', {
    x: MARGIN, y: 691, size: 25, color: COLORS.text,
  })
  drawWordSpacedText(page, font, 'AI가 만드는 더 안전한 일상, DocX-ray와 함께합니다.', { x: MARGIN, y: 660, size: 10.5, color: COLORS.muted })

  // Keep the compact training facts beside the title so the report remains
  // self-contained after the detailed second page is removed.
  const infoX = 390
  page.drawText('훈련 정보', { x: infoX, y: 699, size: 8.5, font, color: COLORS.text })
  const compactDate = generatedDate.replace(/\s/g, '')
  const trainingInfo = [
    `훈련 레벨 : Level ${report.level}`,
    `시나리오 : ${report.scenario_title || '-'}`,
    `점수 : ${scoreLabel}`,
    `등급 : ${report.grade || '-'}`,
    `리포트 생성일 : ${compactDate}`,
  ]
  trainingInfo.forEach((line, index) => {
    drawWordSpacedText(page, font, line, {
      x: infoX, y: 688 - index * 9, size: 7.2, color: COLORS.muted,
    })
  })

  drawRoundedRect(page, { x: MARGIN, y: 549, width: CONTENT_WIDTH, height: 96, radius: 13, color: COLORS.greenSoft, borderColor: COLORS.greenBorder, borderWidth: 0 })
  drawVerticalDivider(page, 220, 565, 58)
  drawVerticalDivider(page, 392, 565, 58)
  const centers = [133, 306, 470]
  const values = [`Level ${report.level}`, scoreLabel, report.grade || '-']
  const labels = ['훈련 레벨', '점수', '등급']
  values.forEach((value, index) => {
    const valueColor = index === 2 ? (GRADE_TONE[report.grade] || COLORS.muted) : index === 1 ? COLORS.cyanStrong : COLORS.text
    drawCenteredText(page, font, value, {
      centerX: centers[index], y: 591, size: index === 0 ? 20 : 26, color: valueColor, bold: true,
    })
    drawCenteredText(page, font, labels[index], { centerX: centers[index], y: 568, size: 10, color: COLORS.muted })
  })

  drawRoundedRect(page, { x: MARGIN, y: 420, width: CONTENT_WIDTH, height: 114, radius: 12, color: COLORS.surface, borderColor: COLORS.border, borderWidth: 0 })
  drawReportIcon(page, { x: 76, y: 504, color: COLORS.green, kind: 'clipboard-check', size: 14 })
  drawWordSpacedText(page, font, '종합 평가', { x: 102, y: 498, size: 16, color: COLORS.text })
  drawParagraph(page, font, report.summary || '분석 결과가 없습니다.', {
    x: 68, y: 465, width: 458, height: 52, size: LAYOUT.bodySize, minSize: 8.5, color: COLORS.text,
  })

  drawRoundedRect(page, { x: MARGIN, y: 232, width: 246, height: 172, radius: 12, color: COLORS.greenSoft, borderColor: COLORS.greenBorder, borderWidth: 0 })
  drawCircleIcon(page, font, { x: 76, y: 377, color: COLORS.green, symbol: '✓', size: 15 })
  drawWordSpacedText(page, font, '잘한 행동', { x: 103, y: 372, size: 14, color: COLORS.cyanStrong })
  drawWordSpacedText(page, font, '이런 대응이 안전한 선택입니다!', { x: 103, y: 355, size: 8, color: COLORS.cyanStrong })
  drawCardList(page, font, report.good_actions, {
    x: 72, y: 325, width: 188, height: 98, tone: 'green',
    emptyMessage: report.score == null ? '유효 답변 부족으로 평가하지 않았습니다.' : '확인된 항목이 없습니다.',
  })
  drawRoundedRect(page, { x: 303, y: 232, width: 246, height: 172, radius: 12, color: COLORS.redSoft, borderColor: COLORS.redBorder, borderWidth: 0 })
  drawCircleIcon(page, font, { x: 333, y: 377, color: COLORS.red, symbol: '!', size: 15 })
  drawWordSpacedText(page, font, '주의가 필요한 행동', { x: 360, y: 372, size: 13.5, color: COLORS.red })
  drawWordSpacedText(page, font, '다음에는 이렇게 주의하세요!', { x: 360, y: 355, size: 8, color: COLORS.muted })
  drawCardList(page, font, report.risky_actions, {
    x: 330, y: 325, width: 188, height: 98, tone: 'red',
    emptyMessage: report.score == null ? '유효 답변 부족으로 평가하지 않았습니다.' : '확인된 위험 행동이 없습니다.',
  })

  drawSectionCard(page, font, {
    x: MARGIN, y: 58, width: CONTENT_WIDTH, height: 122, title: '다음 훈련에서 이렇게 대응하세요', icon: 'shield-check',
    items: report.improvements, tone: 'green', numbered: true, emptyMessage: '추가 개선 권고가 없습니다.',
  })
}

function drawConversationHeader(page, font, logo, report) {
  const logoHeight = 54
  const logoWidth = logoHeight * (1513 / 1037)
  page.drawImage(logo, { x: MARGIN - 5, y: 757, width: logoWidth, height: logoHeight })
  page.drawText('AI SECURITY TRAINING REPORT', {
    x: PAGE.width - MARGIN - font.widthOfTextAtSize('AI SECURITY TRAINING REPORT', 8.5),
    y: 789,
    size: 8.5,
    font,
    color: COLORS.muted,
  })
  page.drawLine({
    start: { x: MARGIN, y: 744 },
    end: { x: PAGE.width - MARGIN, y: 744 },
    thickness: 1.5,
    color: COLORS.green,
  })
  drawWordSpacedText(page, font, 'AI와 나의 실전 대화 기록', {
    x: MARGIN,
    y: 704,
    size: 22,
    color: COLORS.text,
  })
  const scenario = report.scenario_title || '시나리오 정보 없음'
  drawWordSpacedText(page, font, `Level ${report.level} · ${scenario}`, {
    x: MARGIN,
    y: 679,
    size: 9.5,
    color: COLORS.muted,
  })
}

function drawConversationCard(page, font, { role, label, lines, top }) {
  const layout = CONVERSATION_LAYOUT
  const height = layout.cardPadding * 2 + layout.labelHeight + layout.labelGap + lines.length * layout.lineHeight
  const y = top - height
  const isAttacker = role === 'assistant'
  const fill = isAttacker ? COLORS.surface : COLORS.greenSoft
  const accent = isAttacker ? COLORS.red : COLORS.cyanStrong

  drawRoundedRect(page, {
    x: MARGIN,
    y,
    width: CONTENT_WIDTH,
    height,
    radius: 10,
    color: fill,
    borderColor: isAttacker ? COLORS.redBorder : COLORS.greenBorder,
    borderWidth: 0,
  })
  page.drawRectangle({
    x: MARGIN,
    y: y + 10,
    width: 3.5,
    height: height - 20,
    color: accent,
  })
  drawWordSpacedText(page, font, compactKoreanSpacing(label), {
    x: MARGIN + layout.cardPadding,
    y: top - layout.cardPadding - layout.labelHeight + 2,
    size: layout.labelSize,
    color: accent,
  })
  drawLines(page, font, lines, {
    x: MARGIN + layout.cardPadding,
    y: top - layout.cardPadding - layout.labelHeight - layout.labelGap,
    size: layout.bodySize,
    lineHeight: layout.lineHeight,
    color: COLORS.text,
  })
  return y
}

function recommendationHeight(font, text) {
  const lines = wrapConversationText(
    font,
    text,
    CONVERSATION_LAYOUT.bodySize,
    CONTENT_WIDTH - CONVERSATION_LAYOUT.cardPadding * 2,
  )
  return {
    lines,
    height: CONVERSATION_LAYOUT.cardPadding * 2
      + CONVERSATION_LAYOUT.labelHeight
      + CONVERSATION_LAYOUT.labelGap
      + lines.length * CONVERSATION_LAYOUT.lineHeight,
  }
}

function drawRecommendationCard(page, font, { lines, top }) {
  const layout = CONVERSATION_LAYOUT
  const height = layout.cardPadding * 2 + layout.labelHeight + layout.labelGap + lines.length * layout.lineHeight
  const y = top - height
  drawRoundedRect(page, {
    x: MARGIN,
    y,
    width: CONTENT_WIDTH,
    height,
    radius: 10,
    color: COLORS.adviceGreenSoft,
    borderColor: COLORS.adviceGreenBorder,
    borderWidth: 0,
  })
  drawWordSpacedText(page, font, '적절한 대응', {
    x: MARGIN + layout.cardPadding,
    y: top - layout.cardPadding - layout.labelHeight + 2,
    size: layout.labelSize,
    color: COLORS.adviceGreen,
  })
  drawLines(page, font, lines, {
    x: MARGIN + layout.cardPadding,
    y: top - layout.cardPadding - layout.labelHeight - layout.labelGap,
    size: layout.bodySize,
    lineHeight: layout.lineHeight,
    color: COLORS.text,
  })
  return y
}

function drawConversationPages(pdfDoc, font, logo, report) {
  const conversation = Array.isArray(report.conversation) ? report.conversation : []
  if (!conversation.length) return

  const roleTurns = { assistant: 0, user: 0 }
  let page = pdfDoc.addPage([PAGE.width, PAGE.height])
  drawConversationHeader(page, font, logo, report)
  let cursorY = CONVERSATION_LAYOUT.top

  conversation.forEach((message) => {
    const role = message.role === 'user' ? 'user' : 'assistant'
    roleTurns[role] += 1
    const speaker = role === 'assistant' ? 'AI 사기범' : '나의 대응'
    const turn = String(roleTurns[role]).padStart(2, '0')
    const baseLabel = `${speaker} · TURN ${turn}`
    let remainingLines = wrapConversationText(
      font,
      displayMaskedText(message.content),
      CONVERSATION_LAYOUT.bodySize,
      CONTENT_WIDTH - CONVERSATION_LAYOUT.cardPadding * 2,
    )
    let continuation = false

    while (remainingLines.length) {
      const fixedHeight = CONVERSATION_LAYOUT.cardPadding * 2
        + CONVERSATION_LAYOUT.labelHeight
        + CONVERSATION_LAYOUT.labelGap
      let availableHeight = cursorY - CONVERSATION_LAYOUT.bottom
      let maxLines = Math.floor((availableHeight - fixedHeight) / CONVERSATION_LAYOUT.lineHeight)

      if (maxLines < 1) {
        page = pdfDoc.addPage([PAGE.width, PAGE.height])
        drawConversationHeader(page, font, logo, report)
        cursorY = CONVERSATION_LAYOUT.top
        availableHeight = cursorY - CONVERSATION_LAYOUT.bottom
        maxLines = Math.floor((availableHeight - fixedHeight) / CONVERSATION_LAYOUT.lineHeight)
      }

      const chunk = remainingLines.slice(0, maxLines)
      remainingLines = remainingLines.slice(chunk.length)
      cursorY = drawConversationCard(page, font, {
        role,
        label: continuation ? `${baseLabel} · 계속` : baseLabel,
        lines: chunk,
        top: cursorY,
      }) - CONVERSATION_LAYOUT.cardGap
      continuation = true

      if (remainingLines.length) {
        page = pdfDoc.addPage([PAGE.width, PAGE.height])
        drawConversationHeader(page, font, logo, report)
        cursorY = CONVERSATION_LAYOUT.top
      }
    }

    const recommendation = role === 'user' ? getRecommendedResponse(message.content) : null
    if (recommendation) {
      const recommendationCard = recommendationHeight(font, recommendation)
      if (cursorY - CONVERSATION_LAYOUT.bottom < recommendationCard.height) {
        page = pdfDoc.addPage([PAGE.width, PAGE.height])
        drawConversationHeader(page, font, logo, report)
        cursorY = CONVERSATION_LAYOUT.top
      }
      cursorY = drawRecommendationCard(page, font, {
        lines: recommendationCard.lines,
        top: cursorY,
      }) - CONVERSATION_LAYOUT.cardGap
    }
  })
}

export async function createTrainingReportPdf(report, fontBytes) {
  const pdfDoc = await PDFDocument.create()
  pdfDoc.registerFontkit(fontkit)
  // CJK glyphs can be mapped incorrectly when this font is subset by fontkit.
  // Embed the static font as-is so Korean text remains intact in every viewer.
  const font = await pdfDoc.embedFont(fontBytes, { subset: false })
  const baseUrl = import.meta.env?.BASE_URL ?? '/'
  const logoResponse = await fetch(`${baseUrl}docxray-logo.png`)
  if (!logoResponse.ok) throw new Error('PDF용 DocX-ray 로고를 불러오지 못했습니다.')
  const logo = await pdfDoc.embedPng(await logoResponse.arrayBuffer())
  const pageOne = pdfDoc.addPage([PAGE.width, PAGE.height])
  const generatedDate = new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date())

  drawPageOne(pageOne, font, logo, report, generatedDate)
  drawConversationPages(pdfDoc, font, logo, report)

  const pages = pdfDoc.getPages()
  pages.forEach((page, index) => drawFooter(page, font, index + 1, pages.length))

  pdfDoc.setTitle(`DocX-ray Training Level ${report.level} Result`)
  pdfDoc.setAuthor('DocX-ray')
  pdfDoc.setSubject('AI Security Training Report')

  return pdfDoc.save()
}

export async function downloadTrainingReportPdf(report) {
  const response = await fetch(`${import.meta.env.BASE_URL}fonts/NotoSansKR-Report.ttf`)
  if (!response.ok) throw new Error('PDF용 한글 글꼴을 불러오지 못했습니다.')

  const bytes = await createTrainingReportPdf(report, await response.arrayBuffer())
  const blob = new Blob([bytes], { type: 'application/pdf' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `DocX-ray_Training_Level${report.level}_Result.pdf`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}
