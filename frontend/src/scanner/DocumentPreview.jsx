import { useEffect, useMemo, useRef } from 'react'
import { buildSegments, groupOf, splitByPages } from '../shared/findings.js'
import { buildSelectionSegments } from '../shared/maskingRules.js'

// 문서 미리보기. 세 가지 모양으로 그린다.
//   - masked=false                 원문(raw_text) 위에 탐지 구간을 칠한다.
//   - masked=true, selection 없음   전체 마스킹 사본. 쪽이 하나면 서버가 만든 masked_text를 그대로 보여주고,
//                                  쪽이 여럿이면 쪽별로 나누려고 화면에서 같은 규칙으로 계산한다(모든 항목을 [유형]으로).
//   - masked=true, selection 있음   선택 마스킹 미리보기 — 고른 항목만 [유형] 또는 부분 마스킹 모양(010-2310-****)으로 바꾼다.
// 오프셋은 raw_text 기준이라 칠하기와 마스킹 계산은 원문으로 만든다(schema.py: masked_text는 하이라이트에 쓰지 않는다).
//
// selection: { [finding.id]: 'full' | 'standard' } — 목록에 없는 항목은 가리지 않는다.
// pages: 서버 ScanResult.pages([{ page, start, end, label }]). 2개 이상이면 쪽 카드로 나누고 쪽 이동 버튼을 붙인다.
export default function DocumentPreview({
  title,
  text = '',
  findings = [],
  selectedId,
  masked = false,
  maskedText = '',
  selection = null,
  pages = [],
}) {
  const bodyRef = useRef(null)
  const hasPages = Array.isArray(pages) && pages.length > 1

  const fullSelection = useMemo(
    () => Object.fromEntries(findings.map((finding) => [finding.id, 'full'])),
    [findings],
  )
  const activeSelection = selection ?? (masked && hasPages ? fullSelection : null)
  const showServerMaskedText = masked && !activeSelection

  const segments = useMemo(() => {
    if (showServerMaskedText) return []
    return activeSelection ? buildSelectionSegments(text, findings, activeSelection) : buildSegments(text, findings)
  }, [showServerMaskedText, activeSelection, text, findings])

  const pagedSegments = useMemo(
    () => (hasPages && !showServerMaskedText ? splitByPages(segments, pages) : null),
    [hasPages, showServerMaskedText, segments, pages],
  )

  // 항목을 고르면 그 위치로 미리보기 안에서만 스크롤한다(페이지 전체는 움직이지 않게).
  useEffect(() => {
    const box = bodyRef.current
    if (masked || !selectedId || !box) return
    const mark = box.querySelector(`[data-finding-id="${selectedId}"]`)
    if (mark) box.scrollTo({ top: Math.max(0, mark.offsetTop - box.clientHeight / 3), behavior: 'smooth' })
  }, [selectedId, masked])

  function jumpToPage(pageNumber) {
    const box = bodyRef.current
    const section = box?.querySelector(`[data-page="${pageNumber}"]`)
    if (section) box.scrollTo({ top: section.offsetTop, behavior: 'smooth' })
  }

  const content = showServerMaskedText ? maskedText : text
  if (!content) {
    return (
      <div className="paper-wrap">
        <p className="paper paper--empty">
          {showServerMaskedText
            ? '이 파일은 텍스트 사본을 만들지 못했습니다. 내려받은 사본 파일에서 확인해 주세요.'
            : '표시할 텍스트가 없습니다. 이미지만 있는 문서는 탐지 항목만 보여 드립니다.'}
        </p>
      </div>
    )
  }

  function renderSegment(segment, index) {
    if (activeSelection) {
      if (segment.kind === 'full') {
        return (
          <mark key={index} className="mask-token">
            {segment.text}
          </mark>
        )
      }
      if (segment.kind === 'standard') {
        return (
          <mark key={index} className="hit hit--standard">
            {segment.text}
          </mark>
        )
      }
      if (segment.kind === 'excluded') {
        return (
          <span key={index} className="hit-excluded">
            {segment.text}
          </span>
        )
      }
      return <span key={index}>{segment.text}</span>
    }

    const { finding } = segment
    if (!finding) return <span key={index}>{segment.text}</span>
    return (
      <mark
        key={index}
        data-finding-id={finding.id}
        className={`hit hit--${groupOf(finding.type)}${finding.id === selectedId ? ' is-selected' : ''}`}
      >
        {segment.text}
      </mark>
    )
  }

  let label = '문서 원문과 탐지 위치'
  if (selection) label = '선택 마스킹 미리보기'
  else if (masked) label = '마스킹 사본 내용'

  return (
    <div className="paper-wrap">
      <article className="paper">
        {title && <h2 className="paper__title">{title}</h2>}
        {pagedSegments && (
          <nav className="page-nav" aria-label="쪽 이동">
            {pagedSegments.map((page, index) => (
              <button
                key={`${page.page}-${index}`}
                type="button"
                className="page-nav__item"
                onClick={() => jumpToPage(page.page)}
              >
                {page.label}
              </button>
            ))}
          </nav>
        )}
        <div ref={bodyRef} className="paper__body" tabIndex={0} aria-label={label}>
          {showServerMaskedText && maskedText}
          {!showServerMaskedText &&
            (pagedSegments
              ? pagedSegments.map((page, index) => (
                  <section
                    key={`${page.page}-${index}`}
                    className="paper-page"
                    data-page={page.page}
                    aria-label={page.label}
                  >
                    <p className="paper-page__label">
                      <span>{page.label}</span>
                      <span>
                        {index + 1} / {pagedSegments.length}
                      </span>
                    </p>
                    <div>{page.segments.map(renderSegment)}</div>
                  </section>
                ))
              : segments.map(renderSegment))}
        </div>
      </article>
    </div>
  )
}
