import { useEffect, useRef, useState } from 'react'
import { api, UPLOAD_LIMITS } from '../shared/api.js'
import { Button, DecodeText, GlowCard, RiskBadge, SectionRail } from '../shared/components/index.js'
import { GROUPS, GROUP_ORDER, countByGroup, formatPercent, SOURCE_LABELS } from '../shared/findings.js'
import LandingScanMock from './LandingScanMock.jsx'
import './scanner.css'
import './landing.css'

// 스캐너가 읽는 확장자. backend/scanner/scan.py의 _FILE_TYPE_BY_EXTENSION(= parse.py의 표)과 같게 둔다.
const ACCEPTED_EXTENSIONS = [
  '.pdf', '.docx', '.xlsx', '.xlsm',
  '.txt', '.md', '.csv', '.log',
  '.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tif', '.tiff',
]

const SECTIONS = [
  { id: 'intro', label: '소개' },
  { id: 'risk', label: '숨은 위험' },
  { id: 'flow', label: '작동 방식' },
  { id: 'proof', label: '성능' },
  { id: 'privacy', label: '프라이버시' },
  { id: 'upload', label: '업로드' },
]

// 성능 수치의 출처는 저장소 루트 README의 "모델" 표(합성 데이터, 5-fold 그룹 교차검증)다. 모델을 다시 학습하면 같이 고친다.
// 0.9551은 개인정보 탐지 자체가 아니라 "오탐 제거 분류기"의 PR-AUC라서 라벨을 FP FILTER로 적는다.
const HERO_METRICS = [
  { value: '0.9551', label: 'FP FILTER PR-AUC' },
  { value: '0.8832', label: 'INJECTION F1' },
  { value: '8', label: 'FILE FORMATS' }, // PDF·DOCX·XLSX·TXT·MD·CSV·LOG·이미지
]

// 누적 검사 건수·이용자 수 같은 운영 실적은 아직 없으므로 적지 않는다. 네 값 모두 저장소에서 직접 셀 수 있는 숫자다.
//   20종  backend/scanner/detectors/hidden.py의 _REASONS
//   4.62% 루트 README 모델 표(오탐 제거 분류기, 합성 데이터 5-fold 그룹 교차검증)
//   13종  backend/scanner/masking/policy.py의 STANDARD_RULE_DESCRIPTIONS
//   543건 루트 README 모델 표의 합성 데이터 272건 + 271건
const PROOF_STATS = [
  { value: '20종', label: '숨은 위험 판정 근거' },
  { value: '4.62%', label: '개인정보 후보 누락률' },
  { value: '13종', label: '표준 부분 마스킹 유형' },
  { value: '543건', label: '합성 학습·평가 문장' },
]

// 숨은 위험 목록은 backend/scanner/parser/parse.py·detectors/hidden.py가 실제로 잡는 것만 적는다.
const HIDDEN_TRICKS = [
  '흰 배경 흰 글씨',
  '0PT · 투명 텍스트',
  'WORD 숨김 속성',
  'EXCEL VERYHIDDEN 시트',
  'PDF 페이지 밖 텍스트',
  '제로폭 · BIDI · UNICODE TAG',
  '이미지로 덮은 문장',
  '추적 삭제된 명령',
]

const RISKS = [
  { tag: 'HIDDEN TEXT', title: '보이지 않게 심은 문장', copy: '흰 배경의 흰 글씨, 0pt·투명 텍스트, Word 숨김 속성, 추적 삭제된 명령까지 복원합니다.' },
  { tag: 'STRUCTURE', title: '숨긴 시트와 페이지 밖', copy: <>Excel 숨긴 행·열과 <span className="landing-code">veryHidden</span> 시트, PDF 페이지 밖 텍스트와 이미지로 덮은 문장.</> },
  { tag: 'UNICODE', title: '제로폭으로 쓴 AI 지시', copy: '제로폭 문자·Bidi 제어·Unicode 태그로 숨긴 프롬프트 인젝션을 문장 단위로 분류합니다.' },
  { tag: 'CHECKSUM', title: '번호는 검증해서 판정', copy: '주민등록번호·외국인등록번호·사업자등록번호·카드번호를 체크섬으로 확인합니다.' },
  { tag: 'CONTEXT', title: '형태가 겹치는 값 구분', copy: '계좌번호·주문번호·사번처럼 모양이 같은 값을 문맥으로 걸러 오탐을 줄입니다.' },
  { tag: 'IMAGE · OCR', title: '신분증 사진 속 필드', copy: '이미지 문서는 신분증 필드 탐지 CNN이 영역 단위로 찾아 그 자리만 가립니다.' },
]

const STEPS = [
  {
    title: '올립니다',
    copy: `PDF · DOCX · XLSX · TXT · MD · CSV · LOG · 이미지를 한 번에 최대 ${UPLOAD_LIMITS.maxFiles}개. 업로드 원본은 검사 성공 여부와 무관하게 즉시 폐기됩니다.`,
  },
  {
    title: '투시합니다',
    copy: '규칙·체크섬·NER·CNN·숨은 텍스트 탐지 결과를 하나의 Finding 스키마로 통합하고, 판정 근거와 확신도를 함께 남깁니다.',
  },
  {
    title: '가립니다',
    copy: '원본 서식과 배치를 그대로 유지한 마스킹 사본을 만들고, 파일을 위험도 순으로 정렬해 보여줍니다.',
  },
]

const PRIVACY = [
  { tag: 'DELETE ON FINALLY', copy: '업로드 원본은 검사 성공·실패와 관계없이 즉시 삭제합니다.' },
  { tag: 'TTL 30 MIN', copy: '마스킹 사본은 임시 경로에 두고 기본 30분 뒤 삭제합니다.' },
  { tag: 'NO RAW VALUES', copy: '원문 대화와 탐지된 개인정보 값은 DB에 저장하지 않습니다.' },
  { tag: 'SYNTHETIC ONLY', copy: '학습·테스트 데이터는 실제 개인정보 없이 합성 생성기로 만듭니다.' },
]

// 서버가 받는 최대 길이. backend/main.py의 MAX_TEXT_LENGTH와 같게 둔다(더 길면 422가 돌아온다).
const MAX_TEXT_LENGTH = 100000

function extensionOf(name) {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot).toLowerCase() : ''
}

// 탐지된 값은 붙여 넣은 본인의 글이지만, 목록이 길어지지 않게 앞부분만 보여준다.
function shorten(value = '', limit = 48) {
  const chars = Array.from(value)
  return chars.length > limit ? `${chars.slice(0, limit).join('')}…` : value
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  const megabytes = bytes / 1024 / 1024
  return `${Number.isInteger(megabytes) ? megabytes : megabytes.toFixed(1)} MB`
}

function scrollToSection(id, block = 'start') {
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  document.getElementById(id)?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block })
}

// 첫 화면(랜딩). 소개 → 숨은 위험 → 작동 방식 → 성능 → 프라이버시 → 업로드 순서다.
// 업로드 상자는 맨 아래 CTA 자리에 있고, 위의 "무료로 스캔 시작"이 그곳으로 데려간다.
// 업로드 상자의 주 버튼(CTA)은 상태에 따라 바뀐다.
//   파일 고르기 전  "파일 선택하기"          — 업로드 영역이 크게 보인다.
//   파일 고른 뒤    "AI 보안 검사 시작"      — 업로드 영역은 "파일 추가하기" 한 줄로 줄어든다.
// 샘플 문서 체험은 파일이 없는 사람(심사위원 시연 등)을 위한 보조 버튼으로, 소개의 "데모 결과 보기"와 업로드 상자 아래에 둔다.
export default function UploadPage({ onScan, error, busy, navigate }) {
  const inputRef = useRef(null)
  const [files, setFiles] = useState([])
  const [dragging, setDragging] = useState(false)
  const [problems, setProblems] = useState([])
  // 텍스트 붙여넣기 검사 — 파일 없이 문장만 검사한다(POST /scan/text). 붙여 넣은 글은 메모리에만 두고
  // 브라우저 저장소에 남기지 않는다(검사 결과와 같은 기준).
  const [mode, setMode] = useState('file') // 'file' | 'text'
  const [draft, setDraft] = useState('')
  const [textResult, setTextResult] = useState(null)
  const [textScanning, setTextScanning] = useState(false)
  const [textError, setTextError] = useState('')
  const [copied, setCopied] = useState(false)
  const hasFiles = files.length > 0

  // 검사가 실패해 이 화면으로 돌아오면 오류 문구가 있는 업로드 상자를 보여준다(맨 아래라 안 보일 수 있다).
  useEffect(() => {
    if (error) scrollToSection('upload', 'center')
  }, [error])
  function openPicker() {
    if (!busy) inputRef.current?.click()
  }


  function goToUpload() {
    scrollToSection('upload')
    document.querySelector('#upload .dropzone .btn')?.focus({ preventScroll: true })
  }

  function addFiles(fileList) {
    const next = [...files]
    const found = []
    for (const file of Array.from(fileList)) {
      if (!ACCEPTED_EXTENSIONS.includes(extensionOf(file.name))) {
        found.push(`${file.name}: 지원하지 않는 형식입니다.`)
        continue
      }
      if (file.size > UPLOAD_LIMITS.maxFileBytes) {
        found.push(`${file.name}: 파일당 ${formatBytes(UPLOAD_LIMITS.maxFileBytes)}까지 올릴 수 있습니다.`)
        continue
      }
      if (next.some((picked) => picked.name === file.name && picked.size === file.size)) continue
      if (next.length >= UPLOAD_LIMITS.maxFiles) {
        found.push(`한 번에 ${UPLOAD_LIMITS.maxFiles}개까지 올릴 수 있습니다.`)
        break
      }
      next.push(file)
    }
    setFiles(next)
    setProblems(found)
  }

  async function runTextScan() {
    const text = draft.trim()
    if (!text || textScanning) return
    setTextScanning(true)
    setTextError('')
    setTextResult(null)
    setCopied(false)
    try {
      setTextResult(await api.scanText(text))
    } catch (err) {
      setTextError(err.message)
    } finally {
      setTextScanning(false)
    }
  }

  function clearText() {
    setDraft('')
    setTextResult(null)
    setTextError('')
    setCopied(false)
  }

  async function copyMasked() {
    try {
      await navigator.clipboard.writeText(textResult.masked_text)
      setCopied(true)
    } catch {
      setTextError('브라우저가 복사를 막았습니다. 아래 상자에서 직접 선택해 복사해 주세요.')
    }
  }

  const textCounts = textResult ? countByGroup(textResult.findings) : null
  const messages = [...problems, ...(error ? [error] : [])]

  return (
    <div className="landing">
      <div className="landing__backdrop" aria-hidden="true">
        <div className="landing__grid" />
        <div className="landing__glow" />
      </div>
      <SectionRail sections={SECTIONS} />

      <section id="intro" className="container landing-hero">
        <div className="landing-hero__copy rv">
          <p className="landing-badge">
            <span className="landing-badge__dot" aria-hidden="true" />
            DOCUMENT X-RAY SCANNER
          </p>
          <h1 className="landing-hero__title">
            문서를
            <br />
            <span className="landing-glow">투시</span>합니다.
          </h1>
          <p className="landing-hero__lead">
            눈에 보이는 개인정보부터 흰 글씨·0pt·제로폭 문자로 문서 안에 숨겨진 AI 명령까지 — 보내기 전에 찾아내고, 원본
            서식을 지킨 채 가립니다.
          </p>
          <div className="landing-actions">
            <Button size="lg" onClick={goToUpload}>
              무료로 스캔 시작
            </Button>
            <Button size="lg" variant="secondary" disabled={busy} onClick={() => onScan('samples')}>
              데모 결과 보기
            </Button>
          </div>
          <dl className="landing-metrics">
            {HERO_METRICS.map((metric) => (
              <div key={metric.label}>
                <dt>{metric.label}</dt>
                <dd>
                  <DecodeText text={metric.value} />
                </dd>
              </div>
            ))}
          </dl>
          <p className="landing-metrics__note">합성 데이터 5-fold 그룹 교차검증 기준</p>
        </div>
        <LandingScanMock />
      </section>

      <div className="landing-marquee">
        <div className="landing-marquee__track">
          <ul className="landing-marquee__group" aria-label="검사하는 숨은 위험">
            {HIDDEN_TRICKS.map((trick) => (
              <li key={trick}>{trick}</li>
            ))}
          </ul>
          {/* 끊김 없이 흐르게 같은 목록을 한 번 더 붙인다. 화면 읽기 프로그램에는 한 번만 읽힌다. */}
          <ul className="landing-marquee__group" aria-hidden="true">
            {HIDDEN_TRICKS.map((trick) => (
              <li key={trick}>{trick}</li>
            ))}
          </ul>
        </div>
      </div>

      <section id="risk" className="container landing-section">
        <div className="rv">
          <p className="landing-eyebrow">01 — THE BLIND SPOT</p>
          <h2 className="landing-h2">
            문서는 멀쩡해 보여도
            <br />
            안전하지 않습니다.
          </h2>
          <p className="landing-lead">
            일반적인 검사는 화면에 보이는 텍스트만 읽습니다. DocX-ray는 문서 내부의 렌더링 속성·서식·유니코드 층까지
            열어봅니다.
          </p>
        </div>
        <ul className="landing-cards landing-cards--risk stagger">
          {RISKS.map((risk) => (
            <GlowCard as="li" key={risk.tag} className="landing-card rv">
              <p className="landing-card__tag">{risk.tag}</p>
              <h3 className="landing-card__title">{risk.title}</h3>
              <p className="landing-card__copy">{risk.copy}</p>
            </GlowCard>
          ))}
        </ul>
      </section>

      <section id="flow" className="landing-band">
        <div className="container">
          <div className="rv">
            <p className="landing-eyebrow">02 — ONE PASS</p>
            <h2 className="landing-h2">한 번의 검사로 끝나는 세 단계</h2>
          </div>
          <ol className="landing-steps stagger">
            {STEPS.map((step, index) => (
              <GlowCard
                as="li"
                key={step.title}
                className={`landing-step rv${index === 1 ? ' landing-step--active' : ''}`}
              >
                <span className="landing-step__num" aria-hidden="true">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <h3 className="landing-step__title">{step.title}</h3>
                <p className="landing-step__copy">{step.copy}</p>
              </GlowCard>
            ))}
          </ol>
        </div>
      </section>

      <section id="proof" className="container landing-proof">
        <div className="rv">
          <p className="landing-eyebrow">03 — MEASURED</p>
          <h2 className="landing-h2">놓치는 쪽을 먼저 줄였습니다</h2>
          <p className="landing-lead">
            개인정보 후보 누락률(FNR) 5% 이하를 먼저 만족하도록 운영 임계값(0.3534)을 정했습니다. 같은{' '}
            <span className="landing-code">group_id</span>의 문장 변형이 학습·평가 fold에 나뉘지 않게 측정했습니다.
          </p>
          <p className="landing-proof__caveat">
            후보 누락률 4.62%는 분류기 단계의 성능이며(오탐 제거 Precision 0.7750, 인젝션 분류 ROC-AUC 0.9350),
            정규식·OCR를 포함한 전체 서비스 유출률은 아닙니다. 독립된 실문서 평가셋 성능은 아직 확인하지 않았습니다.
          </p>
        </div>
        <GlowCard as="ul" className="landing-statstrip rv">
          {PROOF_STATS.map((stat) => (
            <li key={stat.label}>
              <b>
                <DecodeText text={stat.value} />
              </b>
              <span>{stat.label}</span>
            </li>
          ))}
        </GlowCard>
      </section>

      <section id="privacy" className="landing-band landing-band--plain">
        <div className="container">
          <div className="rv">
            <p className="landing-eyebrow">04 — PRIVACY FIRST</p>
            <h2 className="landing-h2">찾기 위해 보관하지 않습니다</h2>
          </div>
          <ul className="landing-cards landing-cards--privacy stagger">
            {PRIVACY.map((item) => (
              <GlowCard as="li" key={item.tag} className="landing-card rv">
                <p className="landing-card__tag">{item.tag}</p>
                <p className="landing-card__copy landing-card__copy--bright">{item.copy}</p>
              </GlowCard>
            ))}
          </ul>
        </div>
      </section>

      <div className="container landing-cta-wrap">
        <section id="upload" className="landing-cta rv" aria-labelledby="upload-title">
          <i className="landing-cta__glow" aria-hidden="true" />
          <div className="landing-cta__inner">
            <h2 id="upload-title" className="landing-cta__title">
              보내기 전에, 한 번 투시하세요.
            </h2>
            <p className="landing-cta__lead">
              문서를 끌어다 놓으면 개인정보와 숨은 AI 명령을 찾아, 형식을 지킨 마스킹 사본으로 돌려드립니다.
            </p>

            <div className="dropzone-card">
              {/* 파일을 올리거나, 문장을 붙여 넣어 바로 검사한다 */}
              <div className="tabs" role="tablist" aria-label="검사 방법">
                <button
                  type="button"
                  role="tab"
                  className="tabs__tab"
                  aria-selected={mode === 'file'}
                  onClick={() => setMode('file')}
                >
                  파일 올리기
                </button>
                <button
                  type="button"
                  role="tab"
                  className="tabs__tab"
                  aria-selected={mode === 'text'}
                  onClick={() => setMode('text')}
                >
                  텍스트 붙여넣기
                </button>
              </div>

              {mode === 'text' && (
                <div className="text-scan">
                  <label htmlFor="text-scan-input" className="visually-hidden">
                    검사할 텍스트
                  </label>
                  <textarea
                    id="text-scan-input"
                    className="text-scan__input"
                    value={draft}
                    maxLength={MAX_TEXT_LENGTH}
                    placeholder="메일 초안, 메시지, 표에서 복사한 내용을 붙여 넣으세요. 개인정보와 숨은 AI 명령을 바로 찾습니다."
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) runTextScan()
                    }}
                  />

                  <div className="text-scan__row">
                    <span className="text-scan__count">
                      {draft.length.toLocaleString()} / {MAX_TEXT_LENGTH.toLocaleString()}자
                    </span>
                    <span className="row">
                      {draft && (
                        <Button variant="ghost" size="sm" disabled={textScanning} onClick={clearText}>
                          지우기
                        </Button>
                      )}
                      <Button disabled={textScanning || !draft.trim()} onClick={runTextScan}>
                        {textScanning ? '검사 중…' : '텍스트 검사하기'}
                      </Button>
                    </span>
                  </div>

                  {textError && (
                    <p className="alert alert--error" role="alert">
                      {textError}
                    </p>
                  )}

                  {textResult && (
                    <div className="text-scan__result" aria-live="polite">
                      {textResult.findings.length === 0 ? (
                        <p className="text-scan__clean">찾은 개인정보가 없습니다. 그래도 보내기 전에 한 번 더 읽어 보세요.</p>
                      ) : (
                        <>
                          <div className="text-scan__summary">
                            <RiskBadge level={textResult.level} score={textResult.risk_score} />
                            <ul className="text-scan__counts">
                              {GROUP_ORDER.filter((key) => textCounts[key] > 0).map((key) => (
                                <li key={key}>
                                  {GROUPS[key].label} <b>{textCounts[key]}건</b>
                                </li>
                              ))}
                            </ul>
                          </div>

                          <ul className="text-scan__list">
                            {textResult.findings.map((finding) => (
                              <li key={finding.id}>
                                <span className="text-scan__type">{finding.label}</span>
                                <span className="text-scan__value">{shorten(finding.text)}</span>
                                <span className="text-scan__meta">
                                  확신도 {formatPercent(finding.confidence)} · {SOURCE_LABELS[finding.source] ?? finding.source}
                                </span>
                              </li>
                            ))}
                          </ul>

                          {textResult.filtered_count > 0 && (
                            <p className="text-scan__filtered">
                              형태는 비슷하지만 개인정보가 아니라고 판단해 {textResult.filtered_count}건은 제외했습니다.
                            </p>
                          )}

                          <div className="text-scan__masked">
                            <p className="text-scan__masked-head">
                              <span>가린 문장</span>
                              <Button variant="secondary" size="sm" onClick={copyMasked}>
                                {copied ? '복사했습니다' : '복사하기'}
                              </Button>
                            </p>
                            <p className="text-scan__masked-body">{textResult.masked_text}</p>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}

              {mode === 'file' && (
                <>
              {/* 파일 선택 창은 버튼으로 연다. 영역 빈 곳을 눌러도 열리지만 키보드 사용자는 버튼을 쓴다. */}
              <div
                className={`dropzone${hasFiles ? ' dropzone--compact' : ''}${dragging ? ' is-dragging' : ''}`}
                onClick={(event) => {
                  if (!event.target.closest('button')) openPicker()
                }}
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragging(false)
                  if (!busy) addFiles(event.dataTransfer.files)
                }}
              >
                <input
                  ref={inputRef}
                  type="file"
                  multiple
                  accept={ACCEPTED_EXTENSIONS.join(',')}
                  className="visually-hidden"
                  tabIndex={-1}
                  aria-hidden="true"
                  disabled={busy}
                  onChange={(event) => {
                    addFiles(event.target.files)
                    event.target.value = '' // 같은 파일을 빼고 다시 고를 수 있게
                  }}
                />

                {hasFiles ? (
                  <>
                    <p className="dropzone__compact-text">파일을 더 올리려면 이곳에 드롭해주세요</p>
                    <Button variant="secondary" size="sm" disabled={busy} onClick={openPicker}>
                      파일 추가하기
                    </Button>
                  </>
                ) : (
                  <>
                    <span className="dropzone__icon" aria-hidden="true">
                      ⌑
                    </span>
                    <h3 className="dropzone__title">문서를 업로드하세요</h3>
                    <p className="dropzone__hint">
                      PDF · Word · Excel · 텍스트 · 이미지 (최대 {UPLOAD_LIMITS.maxFiles}개, 파일당{' '}
                      {formatBytes(UPLOAD_LIMITS.maxFileBytes)})
                    </p>
                    <Button size="lg" disabled={busy} onClick={openPicker}>
                      파일 올려서 스캔
                    </Button>
                    <p className="dropzone__drop">또는 파일을 이곳에 드롭</p>
                  </>
                )}
              </div>

              {messages.length > 0 && (
                <p className="alert alert--error" role="alert">
                  {messages.map((message) => (
                    <span key={message} className="alert__line">
                      {message}
                    </span>
                  ))}
                </p>
              )}

              {hasFiles && (
                <>
                  <ul className="file-list" aria-label="선택한 파일">
                    {files.map((file) => (
                      <li key={`${file.name}-${file.size}`} className="file-list__item">
                        <span className="file-list__icon" aria-hidden="true">
                          ⌑
                        </span>
                        <span className="file-list__info">
                          <span className="file-list__name">{file.name}</span>
                          <span className="file-list__size">{formatBytes(file.size)}</span>
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="file-list__remove"
                          disabled={busy}
                          aria-label={`${file.name} 삭제`}
                          onClick={() => setFiles((prev) => prev.filter((picked) => picked !== file))}
                        >
                          삭제
                        </Button>
                      </li>
                    ))}
                  </ul>
                  <Button size="lg" block disabled={busy} onClick={() => onScan('files', files)}>
                    AI 보안 검사 시작{files.length > 1 ? ` (${files.length}개)` : ''} →
                  </Button>
                </>
              )}

                </>
              )}

              <p className="dropzone-card__note">
                {mode === 'text'
                  ? '붙여 넣은 텍스트는 검사에만 쓰고 서버에 저장하지 않습니다. 사본 파일도 만들지 않습니다.'
                  : '올린 원본은 검사가 끝나면 서버에서 바로 삭제되고, 가린 사본은 30분 동안만 내려받을 수 있습니다.'}
              </p>

              <div className="sample-cta">
                <p className="sample-cta__text">문서가 없어도 바로 체험해 보세요</p>
                <Button variant="ghost" disabled={busy} onClick={() => onScan('samples')}>
                  샘플 문서로 검사해보기 →
                </Button>
              </div>
            </div>

            <p className="landing-cta__foot">NO ACCOUNT · ORIGINAL DELETED IMMEDIATELY</p>
          </div>
          <i className="landing-cta__sweep" aria-hidden="true" />
        </section>
      </div>

      {/* 전환 띠 — 바닥글 바로 위에서 다음 행동 세 가지를 고르게 한다 */}
      <section className="landing-outro rv" aria-labelledby="outro-title">
        <p className="landing-outro__stack" aria-hidden="true">
          SAFER DOCUMENTS
          <br />
          BRIGHTER TOMORROW
        </p>

        <div className="landing-outro__center">
          <h2 id="outro-title" className="landing-outro__title">
            <span className="landing-outro__accent">개인에서 조직으로,</span> 더 안전한 문서 환경을 만듭니다.
          </h2>
          <p className="landing-outro__lead">
            개인·직장인의 문서 보안에서 시작해, 팀과 회사가 함께 쓰는 보안 습관까지 넓혀 갑니다.
          </p>
          <div className="landing-outro__actions">
            <button type="button" className="landing-pill" onClick={() => scrollToSection('upload')}>
              <span aria-hidden="true">▣</span>
              문서 보안 검사
            </button>
            <button type="button" className="landing-pill" onClick={() => navigate('training')}>
              <span aria-hidden="true">◫</span>
              사기 대응 훈련
            </button>
            <button type="button" className="landing-pill" onClick={() => navigate('guide')}>
              <span aria-hidden="true">◍</span>
              이용 가이드
            </button>
          </div>
        </div>

        <div className="landing-outro__art" aria-hidden="true">
          <svg className="landing-outro__wave" viewBox="0 0 400 200" preserveAspectRatio="none">
            {[0, 1, 2, 3, 4, 5, 6].map((line) => (
              <path
                key={line}
                d={`M400 ${196 - line * 12} C 320 ${170 - line * 18}, 210 ${150 - line * 16}, 0 ${54 - line * 7}`}
              />
            ))}
          </svg>
          <p className="landing-outro__stack landing-outro__stack--right">
            YOUR DOCUMENTS,
            <br />
            SAFER WITH AI
          </p>
        </div>
      </section>

      {/* 바닥글 — 링크는 이 앱 안에서 실제로 동작하는 것만 둔다(없는 페이지로 가는 링크는 누르면 바로 드러난다) */}
      <footer className="container landing-footer">
        <div className="landing-footer__top">
          <div className="landing-footer__brand">
            <p className="landing-footer__logo">
              <svg className="landing-footer__mark" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 2.5l7.5 2.8v6.4c0 4.7-3.2 8-7.5 9.3-4.3-1.3-7.5-4.6-7.5-9.3V5.3L12 2.5z" />
                <path d="M9 9.5h6M9 12.5h6M9 15.5h4" />
              </svg>
              DocX-ray
            </p>
            <p className="landing-footer__tagline">
              AI가 문서 속 개인정보와
              <br />
              숨겨진 위험 요소를 탐지합니다.
            </p>
            <p className="landing-footer__stack" aria-hidden="true">
              SAFER DOCUMENTS
              <br />
              BRIGHTER TOMORROW
            </p>
          </div>

          <nav className="landing-footer__col" aria-label="서비스">
            <p className="landing-footer__title">서비스</p>
            <ul>
              <li>
                <button type="button" className="landing-footer__link" onClick={() => scrollToSection('upload')}>
                  문서 보안 검사
                </button>
              </li>
              <li>
                <button type="button" className="landing-footer__link" disabled={busy} onClick={() => onScan('samples')}>
                  샘플 문서로 검사
                </button>
              </li>
              <li>
                <button type="button" className="landing-footer__link" onClick={() => navigate('training')}>
                  사기 대응 훈련
                </button>
              </li>
            </ul>
          </nav>

          <nav className="landing-footer__col" aria-label="보안과 프라이버시">
            <p className="landing-footer__title">Security &amp; Privacy</p>
            <ul>
              <li>
                <button type="button" className="landing-footer__link" onClick={() => scrollToSection('privacy')}>
                  프라이버시 원칙
                </button>
              </li>
              <li>
                <button type="button" className="landing-footer__link" onClick={() => scrollToSection('risk')}>
                  숨은 위험 탐지
                </button>
              </li>
              <li>
                <button type="button" className="landing-footer__link" onClick={() => scrollToSection('proof')}>
                  성능 측정 결과
                </button>
              </li>
            </ul>
          </nav>

          <nav className="landing-footer__col" aria-label="안내">
            <p className="landing-footer__title">About</p>
            <ul>
              <li>
                <button type="button" className="landing-footer__link" onClick={() => scrollToSection('intro')}>
                  DocX-ray 소개
                </button>
              </li>
              <li>
                <button type="button" className="landing-footer__link" onClick={() => scrollToSection('flow')}>
                  작동 방식
                </button>
              </li>
              <li>
                <button type="button" className="landing-footer__link" onClick={() => navigate('guide')}>
                  이용 가이드
                </button>
              </li>
            </ul>
          </nav>

          <div className="landing-footer__aside">
            <svg className="landing-footer__lock" viewBox="0 0 24 24" aria-hidden="true">
              <rect x="4.5" y="10" width="15" height="10.5" rx="2.5" />
              <path d="M8 10V7a4 4 0 0 1 8 0v3" />
            </svg>
            <p className="landing-footer__aside-text">
              당신의 문서가 더 안전한 세상을 위해, <b>DocX-ray</b>가 함께합니다.
            </p>
            <p className="landing-footer__stack" aria-hidden="true">
              SAFE DOCUMENTS
              <br />
              SAFE BUSINESS
            </p>
          </div>
        </div>

        <div className="landing-footer__meta">
          <span>© 2026 DocX-ray 팀 · 2026 원티드 AI Championship 제안 프로젝트</span>
          <span>문서 보안, 더 안전한 오늘을 만듭니다.</span>
        </div>
      </footer>
    </div>
  )
}
