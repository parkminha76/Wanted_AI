import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { PDFDocument } from 'pdf-lib'
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs'
import { createTrainingReportPdf } from '../src/training/reportPdf.js'
import { getRecommendedResponse } from '../src/training/trainingPrivacyGuidance.js'

const root = fileURLToPath(new URL('../', import.meta.url))
const fontBytes = await readFile(`${root}public/fonts/NotoSansKR-Report.ttf`)
const logoBytes = await readFile(`${root}public/docxray-logo.png`)

globalThis.fetch = async () => new Response(logoBytes, {
  status: 200,
  headers: { 'content-type': 'image/png' },
})

const baseReport = {
  level: 2,
  scenario_title: '사내 IT팀 계정 점검 사칭',
  score: 82,
  grade: '양호',
  summary: '발신자를 확인하고 공식 채널을 이용해 대응했습니다.',
  risky_actions: ['긴급 요청에 잠시 흔들렸습니다.'],
  good_actions: ['공식 채널을 통해 재확인했습니다.'],
  improvements: ['인증정보는 어떤 경우에도 전달하지 마세요.'],
  conversation: [
    { role: 'assistant', content: '계정 확인을 위해 인증번호를 알려주세요.' },
    { role: 'user', content: '제 전화번호는 [PHONE]이며 공식 채널로 확인하겠습니다.' },
  ],
}

const shortBytes = await createTrainingReportPdf(baseReport, fontBytes)
const shortPdf = await PDFDocument.load(shortBytes)
if (shortPdf.getPageCount() !== 2) {
  throw new Error(`짧은 대화 PDF는 2페이지여야 합니다: ${shortPdf.getPageCount()}`)
}
const parsedShortPdf = await getDocument({ data: new Uint8Array(shortBytes) }).promise
const extractedPages = []
for (let pageNumber = 1; pageNumber <= parsedShortPdf.numPages; pageNumber += 1) {
  const page = await parsedShortPdf.getPage(pageNumber)
  const textContent = await page.getTextContent()
  extractedPages.push(textContent.items.map((item) => item.str).join(' '))
}
const extractedText = extractedPages.join('\n')
const compactExtractedText = extractedText.replace(/\s+/g, '')
for (const expected of ['AI와 나의 실전 대화 기록', 'AI 사기범', 'TURN 01', '[전화번호]']) {
  if (!compactExtractedText.includes(expected.replace(/\s+/g, ''))) {
    throw new Error(`PDF 대화 기록에서 문구를 찾지 못했습니다: ${expected}`)
  }
}
if (extractedText.includes('010-1234-5678')) {
  throw new Error('PDF에 원본 전화번호가 노출되었습니다.')
}
const attackerIndex = compactExtractedText.indexOf('계정확인을위해인증번호를알려주세요.')
const userIndex = compactExtractedText.indexOf('제전화번호는[전화번호]이며공식채널로확인하겠습니다.')
if (attackerIndex < 0 || userIndex <= attackerIndex) {
  throw new Error('PDF의 실제 대화 순서가 올바르지 않습니다.')
}

const nameAddressAdvice = '이름·주소 등 개인정보는 제공하지 말고, 요청한 기관이나 배송사의 공식 앱·대표번호를 통해 요청 사실을 확인하세요.'
if (getRecommendedResponse('이름은 고남희고 경기도 수원이에요') !== nameAddressAdvice) {
  throw new Error('이름·주소 제공에 대한 적절한 대응 안내가 생성되지 않았습니다.')
}
const nameAddressBytes = await createTrainingReportPdf({
  ...baseReport,
  conversation: [
    { role: 'assistant', content: '배송 확인을 위해 성함과 주소를 알려주세요.' },
    { role: 'user', content: '이름은 고남희고 경기도 수원이에요.' },
  ],
}, fontBytes)
const nameAddressPdf = await PDFDocument.load(nameAddressBytes)
if (nameAddressPdf.getPageCount() !== 2) {
  throw new Error(`이름·주소 안내 PDF는 2페이지여야 합니다: ${nameAddressPdf.getPageCount()}`)
}

if (process.env.DOCXRAY_PDF_QA_OUTPUT) {
  const outputUrl = new URL(`file:///${process.env.DOCXRAY_PDF_QA_OUTPUT.replace(/\\/g, '/')}`)
  await mkdir(new URL('./', outputUrl), { recursive: true })
  await writeFile(outputUrl, nameAddressBytes)
}

const longMessage = Array.from(
  { length: 450 },
  (_, index) => `긴메시지${index + 1} 한글과 특수문자 !@#를 포함한 대응 내용입니다.`,
).join(' ')
const longBytes = await createTrainingReportPdf({
  ...baseReport,
  conversation: [
    ...baseReport.conversation,
    { role: 'assistant', content: longMessage },
    { role: 'user', content: `확인했습니다. ${longMessage}` },
  ],
}, fontBytes)
const longPdf = await PDFDocument.load(longBytes)
if (longPdf.getPageCount() <= 2) {
  throw new Error(`긴 대화 PDF에 자동 페이지가 추가되지 않았습니다: ${longPdf.getPageCount()}`)
}
if (process.env.DOCXRAY_PDF_QA_LONG_OUTPUT) {
  const longOutputUrl = new URL(`file:///${process.env.DOCXRAY_PDF_QA_LONG_OUTPUT.replace(/\\/g, '/')}`)
  await mkdir(new URL('./', longOutputUrl), { recursive: true })
  await writeFile(longOutputUrl, longBytes)
}

console.log(JSON.stringify({
  shortReportPages: shortPdf.getPageCount(),
  longReportPages: longPdf.getPageCount(),
  koreanConversationTextVerified: true,
  maskedPhoneVerified: true,
  nameAddressGuidanceVerified: true,
  shortReportBytes: shortBytes.length,
  longReportBytes: longBytes.length,
}))
