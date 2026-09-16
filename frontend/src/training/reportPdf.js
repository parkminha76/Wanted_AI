import fontkit from '@pdf-lib/fontkit'
import { PDFDocument, rgb } from 'pdf-lib'

const PAGE = { width: 595.28, height: 841.89 }
const COLORS = {
  navy: rgb(0.063, 0.145, 0.29),
  text: rgb(0.12, 0.15, 0.18),
  muted: rgb(0.34, 0.41, 0.49),
  green: rgb(0.059, 0.541, 0.322),
  greenSoft: rgb(0.91, 0.965, 0.933),
  greenBorder: rgb(0.76, 0.902, 0.82),
  red: rgb(0.82, 0.173, 0.235),
  redSoft: rgb(1, 0.945, 0.949),
  redBorder: rgb(0.965, 0.831, 0.847),
  border: rgb(0.86, 0.89, 0.92),
  surface: rgb(0.975, 0.984, 0.98),
  white: rgb(1, 1, 1),
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
  // fontkit reports slightly narrower advances for this CJK font than PDF
  // viewers render. Keep a safety margin so long Korean sentences never clip.
  const safeWidth = maxWidth * 0.76
  for (const character of Array.from(compactKoreanSpacing(text))) {
    if (character === '\n') {
      lines.push(line.trimEnd())
      line = ''
      continue
    }
    const candidate = line + character
    if (line && font.widthOfTextAtSize(candidate, size) > safeWidth) {
      lines.push(line.trimEnd())
      line = character.trimStart()
    } else {
      line = candidate
    }
  }
  if (line || !lines.length) lines.push(line.trimEnd())
  return lines
}

function compactKoreanSpacing(text) {
  return String(text ?? '')
}

function fittedText(font, text, maxWidth, maxHeight, preferredSize = 11, minSize = 8.5, lineRatio = 1.55) {
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
    page.drawText(compactKoreanSpacing(line), { x, y: y - index * lineHeight, size, font, color })
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
      size: 8.3, minSize: 6.8, color: COLORS.text,
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

function drawVerticalDivider(page, x, y, height) {
  page.drawLine({
    start: { x, y }, end: { x, y: y + height },
    thickness: 0.9, color: COLORS.border,
  })
}

function drawParagraph(page, font, text, options) {
  const fitted = fittedText(font, text, options.width, options.height, options.size, options.minSize)
  return drawLines(page, font, fitted.lines, {
    x: options.x,
    y: options.y,
    size: fitted.size,
    lineHeight: fitted.lineHeight,
    color: options.color,
  })
}

function drawHeader(page, font) {
  page.drawText('DOCX-', { x: 46, y: 792, size: 22, font, color: COLORS.text })
  page.drawText('RAY', { x: 118, y: 792, size: 22, font, color: COLORS.green })
  page.drawText('Think Before You Share.', { x: 52, y: 773, size: 8.8, font, color: COLORS.muted })
  page.drawText('AI SECURITY', { x: 454, y: 795, size: 9.5, font, color: COLORS.text })
  page.drawText('TRAINING REPORT', { x: 430, y: 778, size: 9.5, font, color: COLORS.text })
  page.drawText(compactKoreanSpacing('당신의 안전한 내일을 위한 한 걸음'), { x: 420, y: 760, size: 7.5, font, color: COLORS.muted })
  page.drawLine({ start: { x: 46, y: 738 }, end: { x: 549, y: 738 }, thickness: 1.5, color: COLORS.green })
}

function drawFooter(page, font, pageNumber) {
  page.drawText(`${String(pageNumber).padStart(2, '0')} / 02`, { x: 512, y: 24, size: 8.5, font, color: COLORS.muted })
}

function drawList(page, font, items, options) {
  const values = items?.length ? items : [options.emptyMessage]
  const text = values.map((item) => `${options.marker} ${item}`).join('\n')
  return drawParagraph(page, font, text, options)
}

function drawSectionCard(page, font, { x, y, width, height, title, number, items, tone, numbered = false, emptyMessage }) {
  const accent = tone === 'red' ? COLORS.red : COLORS.green
  const soft = tone === 'red' ? COLORS.redSoft : COLORS.greenSoft
  const border = tone === 'red' ? COLORS.redBorder : COLORS.greenBorder
  drawCircleIcon(page, font, { x: x + 23, y: y + height + 20, color: accent, symbol: number, size: 16 })
  page.drawText(compactKoreanSpacing(title), { x: x + 48, y: y + height + 13, size: 14, font, color: COLORS.text })
  const guide = tone === 'red' ? '다음에는 이런 점을 더 주의하세요.' : numbered ? '이런 방법을 기억해보세요.' : '어떤 습관이 안전한 디지털 생활을 만듭니다.'
  const guideWidth = font.widthOfTextAtSize(guide, 8)
  page.drawText(compactKoreanSpacing(guide), { x: x + width - guideWidth, y: y + height + 15, size: 8, font, color: accent })
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
      size: 9.5, minSize: 7.5, color: COLORS.text,
    })
  })
}

function drawPageOne(page, font, report) {
  drawHeader(page, font)
  page.drawText(compactKoreanSpacing('사기 대응 훈련 결과'), { x: 46, y: 690, size: 26, font, color: COLORS.text })
  page.drawText(compactKoreanSpacing('AI가 만드는 더 안전한 일상, DocX-ray와 함께합니다.'), { x: 46, y: 661, size: 10.5, font, color: COLORS.muted })

  drawRoundedRect(page, { x: 46, y: 551, width: 503, height: 92, radius: 13, color: COLORS.greenSoft, borderColor: COLORS.greenBorder, borderWidth: 0 })
  drawVerticalDivider(page, 220, 569, 57)
  drawVerticalDivider(page, 392, 569, 57)
  const columns = [76, 256, 446]
  const values = [`Level ${report.level}`, `${report.score} / 100`, report.grade]
  const labels = ['훈련 레벨', '점수', '등급']
  values.forEach((value, index) => {
    page.drawText(value, { x: columns[index], y: 592, size: index === 0 ? 17 : 20, font, color: index === 0 ? COLORS.text : COLORS.green })
    page.drawText(compactKoreanSpacing(labels[index]), { x: columns[index] + 14, y: 568, size: 9, font, color: COLORS.muted })
  })

  drawRoundedRect(page, { x: 46, y: 413, width: 503, height: 116, radius: 12, color: COLORS.surface, borderColor: COLORS.border, borderWidth: 0 })
  drawCircleIcon(page, font, { x: 74, y: 501, color: COLORS.green, symbol: '✓', size: 12 })
  page.drawText(compactKoreanSpacing('종합 평가'), { x: 96, y: 496, size: 14, font, color: COLORS.text })
  drawParagraph(page, font, report.summary || '분석 결과가 없습니다.', {
    x: 66, y: 466, width: 463, height: 42, size: 10, minSize: 8, color: COLORS.text,
  })

  drawRoundedRect(page, { x: 46, y: 223, width: 242, height: 169, radius: 12, color: COLORS.greenSoft, borderColor: COLORS.greenBorder, borderWidth: 0 })
  drawCircleIcon(page, font, { x: 75, y: 365, color: COLORS.green, symbol: '✓', size: 14 })
  page.drawText(compactKoreanSpacing('잘한 행동'), { x: 101, y: 361, size: 13, font, color: COLORS.green })
  page.drawText(compactKoreanSpacing('이런 대응이 안전한 선택입니다!'), { x: 101, y: 345, size: 7.5, font, color: COLORS.green })
  drawCardList(page, font, report.good_actions, {
    x: 70, y: 317, width: 179, height: 84, tone: 'green', emptyMessage: '확인된 항목이 없습니다.',
  })
  drawRoundedRect(page, { x: 307, y: 223, width: 242, height: 169, radius: 12, color: COLORS.redSoft, borderColor: COLORS.redBorder, borderWidth: 0 })
  drawCircleIcon(page, font, { x: 336, y: 365, color: COLORS.red, symbol: '!', size: 14 })
  page.drawText(compactKoreanSpacing('주의가 필요한 행동'), { x: 362, y: 361, size: 12.5, font, color: COLORS.red })
  page.drawText(compactKoreanSpacing('다음에는 이렇게 주의하세요!'), { x: 362, y: 345, size: 7.5, font, color: COLORS.muted })
  drawCardList(page, font, report.risky_actions, {
    x: 331, y: 317, width: 179, height: 84, tone: 'red', emptyMessage: '확인된 위험 행동이 없습니다.',
  })

  drawRoundedRect(page, { x: 46, y: 116, width: 503, height: 86, radius: 12, color: COLORS.greenSoft, borderColor: COLORS.greenBorder, borderWidth: 0 })
  page.drawText('“', { x: 66, y: 163, size: 24, font, color: COLORS.green })
  page.drawText(compactKoreanSpacing('작은 의심이 큰 피해를 막습니다.'), { x: 92, y: 159, size: 11, font, color: COLORS.text })
  page.drawText(compactKoreanSpacing('언제나 한 번 더 확인하는 습관이 안전한 나를 만듭니다.'), { x: 92, y: 137, size: 9, font, color: COLORS.muted })
  page.drawText('”', { x: 514, y: 127, size: 24, font, color: COLORS.green })
  page.drawText('DOCX-RAY', { x: 46, y: 79, size: 12, font, color: COLORS.text })
  page.drawText(compactKoreanSpacing('AI로 더 안전한 문서, 더 안전한 일상'), { x: 46, y: 64, size: 7.5, font, color: COLORS.muted })
  page.drawText(new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()), { x: 477, y: 79, size: 8, font, color: COLORS.muted })
  page.drawText('DocX-ray Training Report', { x: 438, y: 64, size: 7.5, font, color: COLORS.muted })
  drawFooter(page, font, 1)
}

function drawPageTwo(page, font, report, generatedDate) {
  drawHeader(page, font)
  drawSectionCard(page, font, {
    x: 46, y: 548, width: 503, height: 119, title: '잘한 대응', number: '01',
    items: report.good_actions, tone: 'green', emptyMessage: '확인된 항목이 없습니다.',
  })
  drawSectionCard(page, font, {
    x: 46, y: 378, width: 503, height: 119, title: '주의가 필요한 행동', number: '02',
    items: report.risky_actions, tone: 'red', emptyMessage: '확인된 위험 행동이 없습니다.',
  })
  drawSectionCard(page, font, {
    x: 46, y: 183, width: 503, height: 143, title: '다음 훈련에서 이렇게 대응하세요', number: '03',
    items: report.improvements, tone: 'green', numbered: true, emptyMessage: '추가 개선 권고가 없습니다.',
  })

  page.drawLine({ start: { x: 46, y: 161 }, end: { x: 549, y: 161 }, thickness: 0.7, color: COLORS.border })
  drawRoundedRect(page, { x: 46, y: 54, width: 275, height: 92, radius: 9, color: COLORS.surface, borderColor: COLORS.border, borderWidth: 0 })
  drawCircleIcon(page, font, { x: 68, y: 126, color: COLORS.navy, symbol: '✓', size: 10 })
  page.drawText(compactKoreanSpacing('훈련 정보'), { x: 88, y: 121, size: 11, font, color: COLORS.text })
  const info = [
    ['훈련 레벨', `Level ${report.level}`], ['점수', `${report.score} / 100`],
    ['등급', report.grade], ['리포트 생성일', generatedDate],
  ]
  info.forEach(([label, value], index) => {
    const rowY = 98 - index * 16
    page.drawText(compactKoreanSpacing(label), { x: 64, y: rowY, size: 7.7, font, color: COLORS.muted })
    page.drawText(String(value), { x: 145, y: rowY, size: 8.5, font, color: COLORS.text })
  })
  page.drawText('DOCX-RAY', { x: 444, y: 78, size: 13, font, color: COLORS.text })
  page.drawText('Think Before You Share.', { x: 433, y: 61, size: 7.5, font, color: COLORS.muted })
  drawFooter(page, font, 2)
}

export async function createTrainingReportPdf(report, fontBytes) {
  const pdfDoc = await PDFDocument.create()
  pdfDoc.registerFontkit(fontkit)
  // CJK glyphs can be mapped incorrectly when this font is subset by fontkit.
  // Embed the static font as-is so Korean text remains intact in every viewer.
  const font = await pdfDoc.embedFont(fontBytes, { subset: false })
  const pageOne = pdfDoc.addPage([PAGE.width, PAGE.height])
  const pageTwo = pdfDoc.addPage([PAGE.width, PAGE.height])
  const generatedDate = new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date())

  drawPageOne(pageOne, font, report)
  drawPageTwo(pageTwo, font, report, generatedDate)

  pdfDoc.setTitle(`DocX-ray Training Level ${report.level} Result`)
  pdfDoc.setAuthor('DocX-ray')
  pdfDoc.setSubject('AI Security Training Report')

  return pdfDoc.save()
}

export async function downloadTrainingReportPdf(report) {
  const response = await fetch(`${import.meta.env.BASE_URL}fonts/NotoSansKR-Compact.ttf`)
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
