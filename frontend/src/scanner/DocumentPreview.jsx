import { useEffect, useMemo, useRef } from 'react'
import { buildSegments, groupOf } from '../shared/findings.js'

// 문서 미리보기. 원문(raw_text) 위에 탐지 구간을 칠하거나, 마스킹 사본(masked_text)을 보여준다.
// 오프셋은 raw_text 기준이라 칠하기는 원문에만 한다(schema.py: masked_text는 하이라이트에 쓰지 않는다).
export default function DocumentPreview({ title, text = '', findings = [], selectedId, masked = false, maskedText = '' }) {
  const bodyRef = useRef(null)
  const segments = useMemo(() => (masked ? [] : buildSegments(text, findings)), [masked, text, findings])

  // 항목을 고르면 그 위치로 미리보기 안에서만 스크롤한다(페이지 전체는 움직이지 않게).
  useEffect(() => {
    const box = bodyRef.current
    if (masked || !selectedId || !box) return
    const mark = box.querySelector(`[data-finding-id="${selectedId}"]`)
    if (mark) box.scrollTo({ top: Math.max(0, mark.offsetTop - box.clientHeight / 3), behavior: 'smooth' })
  }, [selectedId, masked])

  const content = masked ? maskedText : text
  if (!content) {
    return (
      <div className="paper-wrap">
        <p className="paper paper--empty">
          {masked
            ? '이 파일은 텍스트 사본을 만들지 못했습니다. 내려받은 사본 파일에서 확인해 주세요.'
            : '표시할 텍스트가 없습니다. 이미지만 있는 문서는 탐지 항목만 보여 드립니다.'}
        </p>
      </div>
    )
  }

  return (
    <div className="paper-wrap">
      <article className="paper">
        {title && <h2 className="paper__title">{title}</h2>}
        <div
          ref={bodyRef}
          className="paper__body"
          tabIndex={0}
          aria-label={masked ? '마스킹 사본 내용' : '문서 원문과 탐지 위치'}
        >
          {masked
            ? maskedText
            : segments.map((segment, i) =>
                segment.finding ? (
                  <mark
                    key={i}
                    data-finding-id={segment.finding.id}
                    className={`hit hit--${groupOf(segment.finding.type)}${
                      segment.finding.id === selectedId ? ' is-selected' : ''
                    }`}
                  >
                    {segment.text}
                  </mark>
                ) : (
                  <span key={i}>{segment.text}</span>
                ),
              )}
        </div>
      </article>
    </div>
  )
}
