import { useEffect, useState } from 'react'
import { Button } from '../shared/components/index.js'
import {
  CHECKS,
  checkOf,
  explanationFor,
  formatPercent,
  lineNumberAt,
  placeholderFor,
} from '../shared/findings.js'
import DocumentPreview from './DocumentPreview.jsx'
import EmptyResult from './EmptyResult.jsx'
import FileSwitcher from './FileSwitcher.jsx'
import './scanner.css'

// 상세 화면. 왼쪽에서 "어디인지" 보고 오른쪽에서 "왜 문제고 어떻게 고치는지" 읽는다.
// 결과지(ResultsPage)가 ①②③을 맡고, 여기가 ④왜 ⑤어떻게를 맡는다.
//
// 오탐으로 제외한 항목은 탭이 아니라 이 화면의 거르개 하나로 들어와 있다. "가릴까 말까"를
// 판단하는 자리가 둘로 나뉘어 있을 이유가 없다.

// 검사 항목 -> 서버 action_guide의 조치 key. 조치 문구는 서버가 만든 것을 그대로 쓴다
// (schema.build_action_guide) — 화면과 다운로드 안내가 다른 말을 하지 않게.
const ACTION_KEY = { ai_command: 'ai-command' }

const FILTERS = [
  { key: 'all', label: '전체' },
  { key: 'high', label: '위험' },
  { key: 'medium', label: '주의' },
]
const SEARCH_PAGE_SIZE = 5
const SEARCH_PAGE_GROUP_SIZE = 10

const toneOf = (finding) => CHECKS[checkOf(finding.type)].tone

export default function FindingDetailPage({
  batch,
  file,
  fileIndex,
  sourceFile,
  batchSource,
  onSelectFile,
  findingId,
  onSelectFinding,
  navigate,
}) {
  // 결과지에서 "계좌·카드 정보" 카드를 눌러 왔는데 "132건 중 124번째"가 뜨면 내가 뭘 눌렀는지
  // 알 수 없다. 들어올 때 고른 항목의 심각도로 먼저 걸러 두고, 거르개는 사용자가 다시 바꾼다.
  const [filter, setFilter] = useState(() => {
    const entry = file?.findings?.find((finding) => finding.id === findingId)
    return entry ? toneOf(entry) : 'all'
  })
  const [query, setQuery] = useState('')
  const [searchPage, setSearchPage] = useState(1)
  const [maskedPreview, setMaskedPreview] = useState(false)

  if (!batch || !file) return <EmptyResult navigate={navigate} />

  const counts = {
    all: file.findings.length,
    high: file.findings.filter((finding) => toneOf(finding) === 'high').length,
    medium: file.findings.filter((finding) => toneOf(finding) === 'medium').length,
  }

  const excluded = filter === 'excluded'
  const list = excluded || filter === 'all' ? file.findings : file.findings.filter((finding) => toneOf(finding) === filter)
  const finding = excluded ? null : (list.find((item) => item.id === findingId) ?? list[0] ?? null)
  const index = finding ? list.indexOf(finding) : -1
  const normalizedQuery = query.trim().toLowerCase()
  const matches = normalizedQuery
    ? list.filter((item) => [item.label, item.text, locationOf(item)].join(' ').toLowerCase().includes(normalizedQuery))
    : []
  const searchPageCount = Math.max(1, Math.ceil(matches.length / SEARCH_PAGE_SIZE))
  const currentSearchPage = Math.min(searchPage, searchPageCount)
  const pageGroupStart = Math.floor((currentSearchPage - 1) / SEARCH_PAGE_GROUP_SIZE) * SEARCH_PAGE_GROUP_SIZE + 1
  const pageGroupEnd = Math.min(pageGroupStart + SEARCH_PAGE_GROUP_SIZE - 1, searchPageCount)
  const visiblePages = Array.from({ length: pageGroupEnd - pageGroupStart + 1 }, (_, index) => pageGroupStart + index)
  const visibleMatches = matches.slice(
    (currentSearchPage - 1) * SEARCH_PAGE_SIZE,
    currentSearchPage * SEARCH_PAGE_SIZE,
  )
  const typeCounts = list.reduce((result, item) => {
    result.set(item.label, (result.get(item.label) ?? 0) + 1)
    return result
  }, new Map())

  useEffect(() => {
    setSearchPage(1)
  }, [query, filter])

  const check = finding ? CHECKS[checkOf(finding.type)] : null
  const evidence = finding?.evidence ?? {}
  const where = finding
    ? finding.page != null
      ? `${finding.page}쪽`
      : `${lineNumberAt(file.raw_text, finding.start)}번째 줄`
    : ''
  const advice = finding
    ? file.action_guide?.actions?.find((action) => action.key === (ACTION_KEY[checkOf(finding.type)] ?? checkOf(finding.type)))
    : null

  function pick(step) {
    const next = list[index + step]
    if (next) onSelectFinding(next.id)
  }

  function locationOf(item) {
    if (item.page != null) return `${item.page}쪽`
    return `${lineNumberAt(file.raw_text, item.start)}번째 줄`
  }

  function changeFile(nextIndex) {
    setFilter('all')
    setQuery('')
    setSearchPage(1)
    setMaskedPreview(false)
    onSelectFile(nextIndex)
  }

  return (
    <div className="container detail-page">
      <button type="button" className="back-link" onClick={() => navigate('results')}>
        ← 검사 결과로 돌아가기
      </button>

      <div className="page-head rv">
        <div>
          <h1 className="page-title">검사 결과 상세보기</h1>
          <p className="page-desc break-anywhere">
            {file.filename || '텍스트'}
            {finding ? ` · 문제 ${list.length}건 중 ${index + 1}번째` : ''}
          </p>
        </div>
        <div className="page-head__actions">
          <Button onClick={() => navigate('results/mask')}>↓ 안전한 사본 받기</Button>
        </div>
      </div>

      <FileSwitcher results={batch.results} index={fileIndex} onSelect={changeFile} />

      <div className="detail-toolbar">
        <div className="detail-filters" role="group" aria-label="항목 거르기">
          <span className="detail-filters__label">탐지 결과</span>
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              className="chipbtn"
              aria-pressed={filter === item.key}
              onClick={() => setFilter(item.key)}
            >
              {item.label} <b>{counts[item.key]}</b>
            </button>
          ))}
          {file.filtered_count > 0 && (
            <button type="button" className="chipbtn" aria-pressed={excluded} onClick={() => setFilter('excluded')}>
              제외 <b>{file.filtered_count}</b>
            </button>
          )}
        </div>

      </div>

      {!excluded && list.length > 0 && (
        <section className="detail-finder" aria-label="탐지 항목 찾기">
          <div className="detail-finder__head">
            <label htmlFor="finding-search">항목 찾기</label>
            <span>{list.length}건 중 유형·내용·위치로 검색</span>
          </div>
          <input
            id="finding-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="예: 이메일, 1쪽, 홍길동"
          />
          {normalizedQuery ? (
            <ul className="finding-search-results" aria-label="검색 결과">
              {visibleMatches.map((item) => {
                const itemIndex = list.indexOf(item)
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      aria-current={item.id === finding?.id ? 'true' : undefined}
                      onClick={() => {
                        onSelectFinding(item.id)
                        setQuery('')
                      }}
                    >
                      <span>{itemIndex + 1}</span>
                      <b>{item.label}</b>
                      <em>{item.text}</em>
                      <small>{locationOf(item)}</small>
                    </button>
                  </li>
                )
              })}
              {matches.length === 0 && <li className="finding-search-results__empty">일치하는 항목이 없습니다.</li>}
            </ul>
          ) : (
            <div className="finding-type-jump" aria-label="유형별 빠른 이동">
              {[...typeCounts.entries()].map(([label, count]) => (
                <button key={label} type="button" onClick={() => setQuery(label)}>
                  {label} <b>{count}</b>
                </button>
              ))}
            </div>
          )}
          {normalizedQuery && searchPageCount > 1 && (
            <nav className="finding-pagination" aria-label="검색 결과 페이지">
              <button
                type="button"
                aria-label="이전 10페이지"
                disabled={pageGroupStart <= 1}
                onClick={() => setSearchPage(pageGroupStart - SEARCH_PAGE_GROUP_SIZE)}
              >
                ‹
              </button>
              {visiblePages.map((page) => (
                <button
                  key={page}
                  type="button"
                  aria-current={page === currentSearchPage ? 'page' : undefined}
                  onClick={() => setSearchPage(page)}
                >
                  {page}
                </button>
              ))}
              <button
                type="button"
                aria-label="다음 10페이지"
                disabled={pageGroupEnd >= searchPageCount}
                onClick={() => setSearchPage(pageGroupEnd + 1)}
              >
                ›
              </button>
            </nav>
          )}
        </section>
      )}

      <div className="detail-split">
        <div className="panel">
          <div className="panel__heading">
            <b>문서 미리보기</b>
            <Button
              variant="secondary"
              size="sm"
              className="detail-mask-toggle"
              aria-pressed={maskedPreview}
              onClick={() => setMaskedPreview((current) => !current)}
            >
              {maskedPreview ? '원문 보기' : '마스킹된 문서 보기'}
            </Button>
          </div>
          <DocumentPreview
            title={file.filename}
            text={file.raw_text}
            findings={file.findings}
            selectedId={finding?.id}
            masked={maskedPreview}
            maskedText={file.masked_text}
            pages={file.pages}
            fileType={file.file_type}
            sourceFile={sourceFile}
            // 샘플 문서는 브라우저에 File이 없다 — 파일 이름만 넘기면 DocumentPreview가
            // /samples/original로 원본을 받아 와서 PDF/DOCX를 실제 문서처럼 그린다. 마스킹 보기에서도
            // 같은 원본을 그대로 쓰고, 화면에서 탐지 텍스트만 [유형]으로 바꿔치기한다(원문 보기와 같은 형식).
            sampleFilename={batchSource === 'samples' ? file.filename : null}
          />
        </div>

        <aside className="panel detail-card" aria-label="항목 상세">
          {excluded ? (
            <>
              <div className="panel__heading">
                <b>검사했지만 제외한 항목 {file.filtered_count}건</b>
              </div>
              <p className="block__desc">
                형식은 맞았지만 문맥을 보고 개인정보가 아니라고 판단한 값입니다. 위험도 점수에 넣지 않았습니다.
              </p>
              {file.filtered_out.length === 0 ? (
                <p className="issues__empty">제외한 항목이 없습니다.</p>
              ) : (
                <ul className="finding-list">
                  {file.filtered_out.map((item) => (
                    <li key={item.id} className="finding-list__item">
                      <div className="finding-list__head">
                        <strong>{item.label}</strong>
                        {typeof item.evidence?.prob_positive === 'number' && (
                          <span className="chip">개인정보일 확률 {formatPercent(item.evidence.prob_positive)}</span>
                        )}
                      </div>
                      <p className="finding-list__value">{item.text}</p>
                      <p className="finding-list__reason">{item.reason}</p>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : !finding ? (
            <p className="issues__empty">이 조건에 맞는 항목이 없습니다.</p>
          ) : (
            <>
              <div className="detail-card__top">
                <span className={`state state--${check.tone}`}>{check.tone === 'high' ? '위험' : '주의'}</span>
                <div>
                  <b>{finding.label}</b>
                </div>
              </div>

              <div className="detail-card__nav detail-card__nav--top" aria-label="탐지 항목 이동">
                <span>
                  {index + 1} / {list.length}
                </span>
                <Button variant="secondary" disabled={index <= 0} onClick={() => pick(-1)}>
                  ← 이전
                </Button>
                <Button variant="secondary" disabled={index >= list.length - 1} onClick={() => pick(1)}>
                  다음 →
                </Button>
              </div>

              <h2 className="detail-section-title"><span>1</span> 탐지 내용</h2>
              <dl className="facts">
                <div>
                  <dt>위치</dt>
                  <dd>{where}</dd>
                </div>
                <div>
                  <dt>내용</dt>
                  <dd>
                    <code className="facts__value">{finding.text}</code>
                  </dd>
                </div>
              </dl>

              <div className="why">
                <h2><span>2</span> 왜 위험한가</h2>
                <p>{explanationFor(finding.type)}</p>
                {evidence.hidden_reason_text && <p>숨겨져 있던 방식: {evidence.hidden_reason_text}</p>}
              </div>

              <div className="why why--fix">
                <h2><span>3</span> 이렇게 조치하세요</h2>
                <p>{advice?.description ?? '원본 대신 아래처럼 가린 사본을 공유하세요. 문서 서식은 그대로 유지됩니다.'}</p>
                <div className="beforeafter">
                  <span className="beforeafter__before">{finding.text}</span>
                  <span className="beforeafter__after">{placeholderFor(finding)}</span>
                </div>
              </div>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
