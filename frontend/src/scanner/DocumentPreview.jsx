import { useEffect, useMemo, useRef } from 'react'
import { buildSegments, groupOf, placeholderFor } from '../shared/findings.js'

// 문서 미리보기. 세 가지 모양으로 그린다.
//   - masked=false                 원문(raw_text) 위에 탐지 구간을 칠한다.
//   - masked=true, selection 없음   서버가 만든 마스킹 사본 텍스트(masked_text)를 보여준다.
//   - masked=true, selection 있음   선택 마스킹 미리보기 — 원문에서 고른 항목만 [유형]으로 바꿔 보여준다.
// 오프셋은 raw_text 기준이라 칠하기와 선택 미리보기는 원문으로 만든다(schema.py: masked_text는 하이라이트에 쓰지 않는다).
//
// selection: { [finding.id]: 'full' | 'standard' } — 목록에 없는 항목은 가리지 않는다.
export default function DocumentPreview({
  title,
  text = '',
  findings = [],
  selectedId,
  masked = false,
  maskedText = '',
  selection = null,
}) {
  const bodyRef = useRef(null)
  const showServerMaskedText = masked && !selection
  const segments = useMemo(
    () => (showServerMaskedText ? [] : buildSegments(text, findings)),
    [showServerMaskedText, text, findings],
  )

  // 항목을 고르면 그 위치로 미리보기 안에서만 스크롤한다(페이지 전체는 움직이지 않게).
  useEffect(() => {
    const box = bodyRef.current
    if (masked || !selectedId || !box) return
    const mark = box.querySelector(`[data-finding-id="${selectedId}"]`)
    if (mark) box.scrollTo({ top: Math.max(0, mark.offsetTop - box.clientHeight / 3), behavior: 'smooth' })
  }, [selectedId, masked])

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
    const { finding } = segment
    if (!finding) return <span key={index}>{segment.text}</span>

    if (selection) {
      const action = selection[finding.id]
      if (action === 'full') {
        return (
          <mark key={index} className="mask-token">
            {placeholderFor(finding)}
          </mark>
        )
      }
      if (action === 'standard') {
        return (
          <mark key={index} className="hit hit--standard">
            {segment.text}
          </mark>
        )
      }
      return (
        <span key={index} className="hit-excluded">
          {segment.text}
        </span>
      )
    }

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

  const label = selection ? '선택 마스킹 미리보기' : masked ? '마스킹 사본 내용' : '문서 원문과 탐지 위치'

  return (
    <div className="paper-wrap">
      <article className="paper">
        {title && <h2 className="paper__title">{title}</h2>}
        <div ref={bodyRef} className="paper__body" tabIndex={0} aria-label={label}>
          {showServerMaskedText ? maskedText : segments.map(renderSegment)}
        </div>
      </article>
    </div>
  )
}
