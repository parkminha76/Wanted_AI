import { useEffect, useMemo, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { renderAsync as renderDocx } from 'docx-preview'
import { buildSegments, groupOf, splitByPages } from '../shared/findings.js'
import { buildSelectionSegments } from '../shared/maskingRules.js'

GlobalWorkerOptions.workerSrc = pdfWorkerUrl

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
  fileType = '',
  sourceFile = null,
  sourceUrl = null,
}) {
  const bodyRef = useRef(null)
  const [sampleFile, setSampleFile] = useState(null)
  const hasPages = Array.isArray(pages) && pages.length > 1

  useEffect(() => {
    if (sourceFile || !sourceUrl) {
      setSampleFile(null)
      return undefined
    }
    let cancelled = false
    fetch(sourceUrl)
      .then((response) => {
        if (!response.ok) throw new Error('sample original unavailable')
        return response.blob()
      })
      .then((blob) => {
        if (!cancelled) setSampleFile(new File([blob], title || 'sample'))
      })
      .catch(() => {
        if (!cancelled) setSampleFile(null)
      })
    return () => { cancelled = true }
  }, [sourceFile, sourceUrl, title])

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
  const previewFile = sourceFile ?? sampleFile
  const isImagePreview = fileType === 'image' && previewFile

  if (isImagePreview) {
    return <ImagePreview title={title} file={previewFile} findings={findings} selectedId={selectedId} />
  }

  // 직접 업로드한 원본은 브라우저 메모리에만 보관한다. PDF/DOCX도 이 File을 바로
  // 렌더링하므로 서버에 원본이나 미리보기 이미지를 새로 저장하지 않는다.
  if (fileType === 'pdf' && previewFile && !masked) {
    return <PdfPreview title={title} file={previewFile} findings={findings} selectedId={selectedId} />
  }
  if (fileType === 'docx' && previewFile) {
    return <DocxPreview title={title} file={previewFile} findings={findings} selectedId={selectedId} masked={masked} />
  }

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

  // XLSX 원문은 탭, CSV 원문은 쉼표로 셀을 구분한다. segment를 셀 단위로 나누면
  // offset 기반 하이라이트를 잃지 않고 표 형태로 다시 그릴 수 있다.
  function spreadsheetRows(sourceSegments, isCsv = false) {
    const rows = []
    let row = []
    let cell = []

    function finishCell() {
      row.push(cell)
      cell = []
    }

    function finishRow() {
      finishCell()
      rows.push(row)
      row = []
    }

    let quoted = false
    sourceSegments.forEach((segment) => {
      let textPart = ''
      const flush = () => {
        if (textPart) cell.push({ ...segment, text: textPart })
        textPart = ''
      }
      for (let index = 0; index < segment.text.length; index += 1) {
        const character = segment.text[index]
        if (isCsv && character === '"') {
          textPart += character
          if (quoted && segment.text[index + 1] === '"') {
            textPart += segment.text[index + 1]
            index += 1
          } else quoted = !quoted
        } else if ((isCsv ? character === ',' : character === '\t') && !quoted) {
          flush()
          finishCell()
        } else if ((character === '\n' || character === '\r') && !quoted) {
          if (character === '\r' && segment.text[index + 1] === '\n') index += 1
          flush()
          finishRow()
        } else textPart += character
      }
      flush()
    })
    if (cell.length || row.length) finishRow()
    return rows.filter((rowItems) => rowItems.some((cellItems) => cellItems.some((item) => item.text.trim())))
  }

  function columnLabel(index) {
    let value = index + 1
    let label = ''
    while (value > 0) {
      value -= 1
      label = String.fromCharCode(65 + (value % 26)) + label
      value = Math.floor(value / 26)
    }
    return label
  }

  function renderSpreadsheetPage(page, pageIndex, isCsv = false) {
    const rows = spreadsheetRows(page.segments, isCsv)
    const columnCount = Math.max(1, ...rows.map((rowItems) => rowItems.length))
    return (
      <section
        key={`${page.page}-${pageIndex}`}
        className="paper-page paper-page--sheet"
        data-page={page.page}
        aria-label={page.label}
      >
        <p className="paper-page__label">
          <span>{page.label}</span>
          <span>{pageIndex + 1} / {pagedSegments?.length ?? 1}</span>
        </p>
        <div className="sheet-scroll">
          <table className="sheet-grid">
            <thead>
              <tr>
                <th aria-hidden="true" />
                {Array.from({ length: columnCount }, (_, columnIndex) => <th key={columnIndex}>{columnLabel(columnIndex)}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((rowItems, rowIndex) => (
                <tr key={rowIndex}>
                  <th scope="row">{rowIndex + 1}</th>
                  {Array.from({ length: columnCount }, (_, columnIndex) => (
                    <td key={columnIndex}>
                      {(rowItems[columnIndex] ?? []).map((segment, segmentIndex) =>
                        renderSegment(segment, `sheet-${pageIndex}-${rowIndex}-${columnIndex}-${segmentIndex}`),
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
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
        <div ref={bodyRef} className={`paper__body${fileType === 'xlsx' || fileType === 'csv' ? ' paper__body--sheet' : ''}`} tabIndex={0} aria-label={label}>
          {showServerMaskedText && renderMaskedText(maskedText)}
          {!showServerMaskedText &&
            (pagedSegments
              ? (fileType === 'xlsx'
                ? pagedSegments.map(renderSpreadsheetPage)
                : pagedSegments.map((page, index) => (
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
                )))
              : (fileType === 'csv'
                ? renderSpreadsheetPage({ page: 1, label: 'CSV 데이터', segments }, 0, true)
                : segments.map(renderSegment)))}
        </div>
      </article>
    </div>
  )
}

function PdfPreview({ title, file, findings, selectedId }) {
  const [pages, setPages] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    let task = null

    async function render() {
      try {
        const bytes = await file.arrayBuffer()
        task = getDocument({ data: bytes })
        const document = await task.promise
        const rendered = []
        for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
          const page = await document.getPage(pageNumber)
          const viewport = page.getViewport({ scale: 1.5 })
          const originalViewport = page.getViewport({ scale: 1 })
          const canvas = window.document.createElement('canvas')
          canvas.width = Math.ceil(viewport.width)
          canvas.height = Math.ceil(viewport.height)
          await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise
          rendered.push({
            pageNumber,
            image: canvas.toDataURL('image/png'),
            width: originalViewport.width,
            height: originalViewport.height,
          })
        }
        if (!cancelled) setPages(rendered)
      } catch (caught) {
        if (!cancelled) setError('PDF 원본을 화면에 표시하지 못했습니다.')
      }
    }

    setPages([])
    setError('')
    render()
    return () => {
      cancelled = true
      task?.destroy()
    }
  }, [file])

  return (
    <div className="paper-wrap rendered-preview-wrap">
      <article className="paper rendered-preview">
        {title && <h2 className="paper__title">{title}</h2>}
        {!pages.length && !error && <p className="paper--empty">PDF 페이지를 불러오는 중입니다.</p>}
        {error && <p className="paper--empty">{error}</p>}
        {pages.map((page) => {
          const boxes = findings.filter((finding) => finding.page === page.pageNumber && Array.isArray(finding.bbox))
          return (
            <section key={page.pageNumber} className="rendered-page" aria-label={`${page.pageNumber}쪽`}>
              <p className="paper-page__label"><span>{page.pageNumber}쪽</span><span>{page.pageNumber} / {pages.length}</span></p>
              <div className="rendered-page__stage">
                <img src={page.image} alt={`${page.pageNumber}쪽 원본`} />
                {boxes.map((finding) => {
                  const [x0, y0, x1, y1] = finding.bbox
                  return (
                    <mark
                      key={finding.id}
                      data-finding-id={finding.id}
                      className={`image-hit image-hit--${groupOf(finding.type)}${finding.id === selectedId ? ' is-selected' : ''}`}
                      style={{
                        left: `${(x0 / page.width) * 100}%`, top: `${(y0 / page.height) * 100}%`,
                        width: `${((x1 - x0) / page.width) * 100}%`, height: `${((y1 - y0) / page.height) * 100}%`,
                      }}
                      aria-label={`${finding.label} 탐지 위치`}
                    />
                  )
                })}
              </div>
            </section>
          )
        })}
        <p className="image-preview__note">색칠된 영역은 탐지된 정보이며, 진한 테두리는 현재 선택한 항목입니다.</p>
      </article>
    </div>
  )
}

function DocxPreview({ title, file, findings, selectedId, masked }) {
  const containerRef = useRef(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    async function render() {
      try {
        const container = containerRef.current
        if (!container) return
        container.replaceChildren()
        await renderDocx(file, container, undefined, {
          className: 'docx-preview', breakPages: true, ignoreLastRenderedPageBreak: false,
          renderHeaders: true, renderFooters: true, useBase64URL: true,
        })
        if (!cancelled) highlightDocxFindings(container, findings, selectedId, masked)
      } catch (caught) {
        if (!cancelled) setError('DOCX 원본을 화면에 표시하지 못했습니다.')
      }
    }
    setError('')
    render()
    return () => { cancelled = true }
  }, [file, findings, selectedId, masked])

  return (
    <div className="paper-wrap docx-preview-wrap">
      <article className="paper docx-preview-paper">
        {title && <h2 className="paper__title">{title}</h2>}
        {error && <p className="paper--empty">{error}</p>}
        <div ref={containerRef} className="docx-preview-host" aria-label="DOCX 문서 원문" />
        {!error && <p className="image-preview__note">색칠된 텍스트는 탐지된 정보이며, 현재 선택한 항목은 진한 테두리로 표시됩니다.</p>}
      </article>
    </div>
  )
}

function highlightDocxFindings(container, findings, selectedId, masked) {
  const walker = window.document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const nodes = []
  let node
  while ((node = walker.nextNode())) {
    if (node.nodeValue) nodes.push(node)
  }
  const text = nodes.map((item) => item.nodeValue).join('')
  const used = new Set()

  for (const finding of findings) {
    if (!finding.text || used.has(finding.text)) continue
    const start = text.indexOf(finding.text)
    if (start < 0) continue
    let remaining = finding.text.length
    let offset = 0
    for (const textNode of nodes) {
      const nextOffset = offset + textNode.nodeValue.length
      if (start >= nextOffset || start + remaining <= offset) {
        offset = nextOffset
        continue
      }
      const from = Math.max(0, start - offset)
      const to = Math.min(textNode.nodeValue.length, start + remaining - offset)
      if (from < to && textNode.parentElement) {
        const range = window.document.createRange()
        range.setStart(textNode, from)
        range.setEnd(textNode, to)
        const mark = window.document.createElement('mark')
        mark.dataset.findingId = finding.id
        mark.className = masked
          ? 'mask-token'
          : `hit hit--${groupOf(finding.type)}${finding.id === selectedId ? ' is-selected' : ''}`
        range.surroundContents(mark)
        if (masked) mark.textContent = `[${finding.label || '민감정보'}]`
      }
      remaining -= to - from
      offset = nextOffset
      if (remaining <= 0) break
    }
    used.add(finding.text)
  }
}

function renderMaskedText(text) {
  return String(text).split(/(\[[^\]\r\n]+\])/g).map((part, index) =>
    /^\[[^\]\r\n]+\]$/.test(part)
      ? <mark key={index} className="mask-token">{part}</mark>
      : <span key={index}>{part}</span>,
  )
}

// 이미지의 탐지 bbox는 원본 픽셀 좌표다. 원본의 가로·세로를 기준으로 %로 바꿔
// 브라우저 크기가 달라져도 같은 자리에 하이라이트가 남게 한다.
function ImagePreview({ title, file, findings, selectedId }) {
  const [imageUrl, setImageUrl] = useState('')
  const [size, setSize] = useState(null)

  useEffect(() => {
    const nextUrl = URL.createObjectURL(file)
    setImageUrl(nextUrl)
    return () => URL.revokeObjectURL(nextUrl)
  }, [file])

  const boxes = findings.filter((finding) => Array.isArray(finding.bbox) && finding.bbox.length === 4)

  return (
    <div className="paper-wrap image-preview-wrap">
      <article className="paper image-preview">
        {title && <h2 className="paper__title">{title}</h2>}
        <div className="image-preview__stage">
          {imageUrl && (
            <img
              src={imageUrl}
              alt={`${title || '업로드 이미지'} 원본`}
              onLoad={(event) => setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
            />
          )}
          {size && boxes.map((finding) => {
            const [x0, y0, x1, y1] = finding.bbox
            return (
              <mark
                key={finding.id}
                data-finding-id={finding.id}
                className={`image-hit image-hit--${groupOf(finding.type)}${finding.id === selectedId ? ' is-selected' : ''}`}
                style={{
                  left: `${(x0 / size.width) * 100}%`,
                  top: `${(y0 / size.height) * 100}%`,
                  width: `${((x1 - x0) / size.width) * 100}%`,
                  height: `${((y1 - y0) / size.height) * 100}%`,
                }}
                aria-label={`${finding.label} 탐지 위치`}
              />
            )
          })}
        </div>
        <p className="image-preview__note">색칠된 영역은 탐지된 정보이며, 진한 테두리는 현재 선택한 항목입니다.</p>
      </article>
    </div>
  )
}
