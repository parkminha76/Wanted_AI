import { useEffect, useMemo, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { renderAsync as renderDocx } from 'docx-preview'
import { api } from '../shared/api.js'
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
  sampleFilename = null,
  // 오탐으로 제외한 항목(위험도 점수엔 안 넣는 값들). 원문 보기(칠하기)에는 안 쓰지만, 마스킹
  // 사본은 서버가 이 값들도 같이 가려서 만든다 — 미리보기도 다운로드 사본과 같아지도록 마스킹
  // 대상에는 findings와 함께 포함한다.
  filteredOut = [],
}) {
  const bodyRef = useRef(null)
  const hasPages = Array.isArray(pages) && pages.length > 1
  const maskCandidates = useMemo(() => [...findings, ...filteredOut], [findings, filteredOut])

  // 샘플 문서는 검사할 때 브라우저에 원본 File을 안 올린다(서버가 이미 갖고 있어서). PDF/DOCX/이미지를
  // 실제 문서처럼 그리려면 그 File이 있어야 해서, 없을 때만 /samples/original로 원본을 따로 받아 온다.
  const [fetchedSample, setFetchedSample] = useState(null)
  const needsRealFile = fileType === 'pdf' || fileType === 'docx' || fileType === 'image'
  useEffect(() => {
    setFetchedSample(null)
    if (sourceFile || !sampleFilename || !needsRealFile) return
    let cancelled = false
    fetch(api.sampleOriginalUrl(sampleFilename))
      .then((res) => (res.ok ? res.blob() : Promise.reject(new Error('sample fetch failed'))))
      .then((blob) => {
        if (!cancelled) setFetchedSample(blob)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [sourceFile, sampleFilename, needsRealFile])

  const effectiveSourceFile = sourceFile || fetchedSample

  const fullSelection = useMemo(
    () => Object.fromEntries(maskCandidates.map((finding) => [finding.id, 'full'])),
    [maskCandidates],
  )
  // 쪽이 여러 개일 때만 화면에서 계산하던 것을 쪽이 하나일 때도 똑같이 적용한다 — 안 그러면
  // CSV/XLSX 표나 TXT/MD 같은 홑쪽 문서는 마스킹 보기에서 서버가 만든 밋밋한 문자열(maskedText)로
  // 떨어져서 원문 보기와 모양(표 칸 나눔 등)이 달라진다. buildSelectionSegments는 findings 오프셋으로
  // [유형] 자리표시자를 넣으므로 서버 masked_text와 값은 같고, 표/쪽 구조만 그대로 유지된다.
  const activeSelection = selection ?? (masked ? fullSelection : null)
  const showServerMaskedText = masked && !activeSelection

  const segments = useMemo(() => {
    if (showServerMaskedText) return []
    return activeSelection
      ? buildSelectionSegments(text, maskCandidates, activeSelection)
      : buildSegments(text, findings)
  }, [showServerMaskedText, activeSelection, text, findings, maskCandidates])

  const pagedSegments = useMemo(
    () => (hasPages && !showServerMaskedText ? splitByPages(segments, pages) : null),
    [hasPages, showServerMaskedText, segments, pages],
  )

  // "‹ 1 / N ›" 인디케이터가 가리키는 위치 — 배열 순서(0부터)로 센다. 쪽 번호(page.page)는
  // 꼭 1,2,3...으로 이어진다는 보장이 없어서(서버가 주는 값) 인덱스로 다뤄야 화살표 이동이 안전하다.
  const [currentPageIndex, setCurrentPageIndex] = useState(0)
  // 보던 쪽을 유지하고, 새 문서에 그 쪽이 없을 때만 첫 쪽으로 되돌린다.
  //
  // 그냥 0으로 초기화하면 원문↔마스킹 토글 때마다 맨 위로 튄다 — 토글은 내용을
  // (raw_text ↔ maskedText) 갈아 끼우므로 pagedSegments가 매번 새 배열이 되고,
  // 이 효과가 같이 돈다. 3쪽을 보다가 "원문 보기"를 누르면 3쪽의 원문이 아니라
  // 1쪽으로 돌아가 버렸다.
  useEffect(() => {
    setCurrentPageIndex((current) =>
      pagedSegments && current < pagedSegments.length ? current : 0,
    )
  }, [pagedSegments])

  // 항목을 고르면 그 위치로 미리보기 안에서만 스크롤한다(페이지 전체는 움직이지 않게).
  useEffect(() => {
    const box = bodyRef.current
    if (masked || !selectedId || !box) return
    const mark = box.querySelector(`[data-finding-id="${selectedId}"]`)
    if (mark) box.scrollTo({ top: Math.max(0, mark.offsetTop - box.clientHeight / 3), behavior: 'smooth' })
  }, [selectedId, masked])

  function jumpToPageIndex(index) {
    if (!pagedSegments || index < 0 || index >= pagedSegments.length) return
    const box = bodyRef.current
    const section = box?.querySelector(`[data-page="${pagedSegments[index].page}"]`)
    if (box && section) {
      // getBoundingClientRect() 기준 — DOCX 쪽 이동과 같은 이유로 offsetTop 대신 쓴다.
      const boxRect = box.getBoundingClientRect()
      const sectionRect = section.getBoundingClientRect()
      box.scrollTo({ top: box.scrollTop + (sectionRect.top - boxRect.top), behavior: 'smooth' })
    }
    setCurrentPageIndex(index)
  }

  const content = showServerMaskedText ? maskedText : text
  const isImagePreview = fileType === 'image' && effectiveSourceFile

  if (isImagePreview) {
    return (
      <ImagePreview
        title={title}
        file={effectiveSourceFile}
        findings={findings}
        filteredOut={filteredOut}
        selectedId={selectedId}
        masked={masked}
      />
    )
  }

  // 직접 업로드한 원본은 브라우저 메모리에만 보관한다. 샘플 문서는 sampleFilename으로 받아 온
  // Blob이 여기 들어온다. PDF/DOCX도 이 File을 바로 렌더링하므로 서버에 미리보기 이미지를
  // 새로 저장하지 않는다. masked=true일 때도 같은 원본을 그대로 그리고, 탐지 위치만 다르게
  // 표시한다(PDF는 검게 칠하고, DOCX는 텍스트를 [유형]으로 바꿔 끼운다) — 원문 보기와 같은
  // 문서 형태를 유지하기 위해서다.
  if (fileType === 'pdf' && effectiveSourceFile) {
    return (
      <PdfPreview
        title={title}
        file={effectiveSourceFile}
        findings={findings}
        filteredOut={filteredOut}
        selectedId={selectedId}
        masked={masked}
      />
    )
  }
  if (fileType === 'docx' && effectiveSourceFile) {
    return (
      <DocxPreview
        title={title}
        file={effectiveSourceFile}
        findings={findings}
        filteredOut={filteredOut}
        selectedId={selectedId}
        masked={masked}
      />
    )
  }
  // 샘플 원본을 받아 오는 중 — 검은 글자 화면으로 잠깐 바뀌었다가 다시 실제 문서로 바뀌는
  // 깜빡임을 막는다.
  if (sampleFilename && needsRealFile && !effectiveSourceFile) {
    return (
      <div className="paper-wrap">
        <p className="paper paper--empty">문서를 불러오는 중입니다.</p>
      </div>
    )
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
        {/* DOCX/PDF와 같은 "‹ 1 / N ›" 인디케이터. 쪽(시트) 이름은 각 쪽 위의 라벨에서 계속 보인다. */}
        {pagedSegments && (
          <nav className="doc-page-nav" aria-label="쪽 이동">
            <button
              type="button"
              className="doc-page-nav__arrow"
              disabled={currentPageIndex <= 0}
              onClick={() => jumpToPageIndex(currentPageIndex - 1)}
              aria-label="이전 쪽"
            >
              ‹
            </button>
            <span className="doc-page-nav__count">
              {currentPageIndex + 1} / {pagedSegments.length}
            </span>
            <button
              type="button"
              className="doc-page-nav__arrow"
              disabled={currentPageIndex >= pagedSegments.length - 1}
              onClick={() => jumpToPageIndex(currentPageIndex + 1)}
              aria-label="다음 쪽"
            >
              ›
            </button>
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

function PdfPreview({ title, file, findings, filteredOut = [], selectedId, masked = false }) {
  // 마스킹 사본은 서버가 오탐 제외 항목까지 가려서 만든다 — 미리보기도 같은 자리를 검게
  // 칠하도록 마스킹 대상에는 filteredOut을 같이 넣는다. 원문 보기(색칠)는 findings만 쓴다.
  const boxSource = masked ? [...findings, ...filteredOut] : findings
  const [pages, setPages] = useState([])
  const [error, setError] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const articleRef = useRef(null)

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
    setCurrentPage(1)
    render()
    return () => {
      cancelled = true
      task?.destroy()
    }
  }, [file])

  function jumpToPdfPage(pageNumber) {
    const host = articleRef.current
    const section = host?.querySelector(`[data-page-number="${pageNumber}"]`)
    if (!host || !section) return
    // getBoundingClientRect() 기준 — DOCX 쪽 이동과 같은 이유로 offsetTop 대신 쓴다.
    const hostRect = host.getBoundingClientRect()
    const sectionRect = section.getBoundingClientRect()
    host.scrollTo({ top: host.scrollTop + (sectionRect.top - hostRect.top), behavior: 'smooth' })
    setCurrentPage(pageNumber)
  }

  return (
    <div className="paper-wrap rendered-preview-wrap">
      <article className="paper rendered-preview">
        {title && <h2 className="paper__title">{title}</h2>}
        {/* DOCX·XLSX와 같은 "‹ 1 / N ›" 인디케이터. 여러 쪽이면 아래 rendered-preview-host가
            자기 스크롤 상자를 가져서, 쪽을 넘겨도 페이지 전체가 아니라 이 상자 안에서만 움직인다. */}
        {pages.length > 1 && (
          <nav className="doc-page-nav" aria-label="쪽 이동">
            <button
              type="button"
              className="doc-page-nav__arrow"
              disabled={currentPage <= 1}
              onClick={() => jumpToPdfPage(currentPage - 1)}
              aria-label="이전 쪽"
            >
              ‹
            </button>
            <span className="doc-page-nav__count">
              {currentPage} / {pages.length}
            </span>
            <button
              type="button"
              className="doc-page-nav__arrow"
              disabled={currentPage >= pages.length}
              onClick={() => jumpToPdfPage(currentPage + 1)}
              aria-label="다음 쪽"
            >
              ›
            </button>
          </nav>
        )}
        {!pages.length && !error && <p className="paper--empty">PDF 페이지를 불러오는 중입니다.</p>}
        {error && <p className="paper--empty">{error}</p>}
        {pages.length > 0 && (
          <div ref={articleRef} className="rendered-preview-host">
            {pages.map((page) => {
              const boxes = boxSource.filter((finding) => finding.page === page.pageNumber && Array.isArray(finding.bbox))
              return (
                <section
                  key={page.pageNumber}
                  className="rendered-page"
                  data-page-number={page.pageNumber}
                  aria-label={`${page.pageNumber}쪽`}
                >
                  <p className="paper-page__label"><span>{page.pageNumber}쪽</span><span>{page.pageNumber} / {pages.length}</span></p>
                  <div className="rendered-page__stage">
                    <img src={page.image} alt={`${page.pageNumber}쪽 원본`} />
                    {boxes.map((finding) => {
                      const [x0, y0, x1, y1] = finding.bbox
                      const boxStyle = {
                        left: `${(x0 / page.width) * 100}%`, top: `${(y0 / page.height) * 100}%`,
                        width: `${((x1 - x0) / page.width) * 100}%`, height: `${((y1 - y0) / page.height) * 100}%`,
                      }
                      // masked일 때는 실제 마스킹 사본처럼 위치만 검게 칠한다(유형별 색·선택 강조는
                      // 원문 보기에서만 의미가 있다 — 가린 자리에는 "무엇인지"를 다시 드러내지 않는다).
                      return masked ? (
                        <span key={finding.id} className="image-hit image-hit--redacted" style={boxStyle} aria-label="가려진 영역" />
                      ) : (
                        <mark
                          key={finding.id}
                          data-finding-id={finding.id}
                          className={`image-hit image-hit--${groupOf(finding.type)}${finding.id === selectedId ? ' is-selected' : ''}`}
                          style={boxStyle}
                          aria-label={`${finding.label} 탐지 위치`}
                        />
                      )
                    })}
                  </div>
                </section>
              )
            })}
          </div>
        )}
        <p className="image-preview__note">
          {masked ? '검게 칠해진 영역이 가려진 개인정보입니다.' : '색칠된 영역은 탐지된 정보이며, 진한 테두리는 현재 선택한 항목입니다.'}
        </p>
      </article>
    </div>
  )
}

function DocxPreview({ title, file, findings, filteredOut = [], selectedId, masked = false }) {
  const containerRef = useRef(null)
  const [error, setError] = useState('')
  const [pageCount, setPageCount] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)

  useEffect(() => {
    let cancelled = false
    let resizeObserver = null
    async function render() {
      const container = containerRef.current
      if (!container) return
      // renderDocx()는 completion까지 시간이 걸리는데(개발 모드 StrictMode는 effect를 두 번
      // 돌리기도 하고, selectedId가 마운트 직후 한 번 더 바뀌기도 한다), 그 사이 이 effect가
      // cleanup되고 새 실행이 같은 container에 또 렌더링을 시작할 수 있다. container를 바로
      // 쓰면 두 실행이 끝나는 순서에 따라 옛 실행의 결과(칠하기 전 원문)가 새 실행의 결과 뒤에
      // 끼어들어 "가끔 칠해지지 않은 것처럼" 보이는 화면 전용 경쟁 상태가 생긴다. 그래서 각
      // 실행은 자기만의 조각(scratch)에 렌더링해 두고, 끝까지 취소되지 않은 실행만 그 조각을
      // container에 옮겨 붙인다 — 쪽 나누기 계산에 실제 레이아웃이 필요해서 scratch도 화면에
      // 붙여 두되(다른 형제 뒤에 조용히 쌓인다), 최종 결과가 갈리는 그 짧은 순간은 다음 페인트
      // 전에 정리되어 눈에 보이지 않는다.
      const scratch = window.document.createElement('div')
      container.appendChild(scratch)
      try {
        await renderDocx(file, scratch, undefined, {
          className: 'docx-preview', breakPages: true, ignoreLastRenderedPageBreak: false,
          renderHeaders: true, renderFooters: true, useBase64URL: true,
        })
        if (cancelled) {
          scratch.remove()
          return
        }
        // 이 실행이 이겼다 — 같은 container 안에 남아 있을 수 있는 다른(취소됐거나 옛) 조각을 치운다.
        for (const child of Array.from(container.children)) {
          if (child !== scratch) child.remove()
        }
        // masked일 때는 실제 마스킹 사본에 있는 텍스트(binary)가 브라우저에 없어서(서버만 갖고
        // 있다) 원본 문서를 그대로 그린 다음 탐지된 텍스트만 [유형]으로 바꿔 끼운다 — 표·글꼴 등
        // 문서 형태는 원문 보기와 같게 유지된다.
        // 마스킹 사본은 서버가 오탐 제외 항목까지 가려서 만든다 — 미리보기도 같은 자리를
        // [유형]으로 바꾸도록 마스킹 대상에는 filteredOut을 같이 넣는다.
        if (masked) maskDocxFindings(scratch, [...findings, ...filteredOut])
        else highlightDocxFindings(scratch, findings, selectedId)
        // docx-preview는 실제 A4 폭(고정 px)으로 그려서, 좁은 상자 안에서는 한쪽이 잘려
        // 줌인한 것처럼 보인다. 상자 너비에 맞춰 페이지 전체를 축소해 한눈에 보이게 한다.
        fitDocxToContainer(container)
        resizeObserver = new ResizeObserver(() => fitDocxToContainer(container))
        resizeObserver.observe(container)
        setPageCount(container.querySelectorAll('.docx-preview').length)
        setCurrentPage(1)
      } catch (caught) {
        scratch.remove()
        if (!cancelled) setError('DOCX 원본을 화면에 표시하지 못했습니다.')
      }
    }
    setError('')
    setPageCount(0)
    render()
    return () => {
      cancelled = true
      resizeObserver?.disconnect()
    }
  }, [file, findings, filteredOut, selectedId, masked])

  function jumpToDocxPage(pageNumber) {
    const container = containerRef.current
    const page = container?.querySelectorAll('.docx-preview')[pageNumber - 1]
    if (!container || !page) return
    // offsetTop은 안 쓴다 — zoom으로 축소한 요소 안에서는 축소 전 좌표를 돌려줘서(브라우저마다
    // 다를 수 있는 zoom 고유 동작) 뒤 페이지로 갈수록 실제 스크롤 위치와 어긋난다.
    // getBoundingClientRect()는 항상 화면에 실제로 그려진(zoom 적용된) 좌표라 정확하다.
    const containerRect = container.getBoundingClientRect()
    const pageRect = page.getBoundingClientRect()
    container.scrollTo({ top: container.scrollTop + (pageRect.top - containerRect.top), behavior: 'smooth' })
    setCurrentPage(pageNumber)
  }

  return (
    <div className="paper-wrap docx-preview-wrap">
      <article className="paper docx-preview-paper">
        {title && <h2 className="paper__title">{title}</h2>}
        {/* 여러 쪽이면 위쪽 가운데에 쪽 이동 인디케이터 — DOCX는 PDF와 달리 쪽 나누기가 서버 없이
            docx-preview가 화면에서 직접 계산해서(breakPages:true), 실제로 몇 쪽인지는
            렌더링이 끝나야 안다(pageCount). */}
        {pageCount > 1 && (
          <nav className="doc-page-nav" aria-label="쪽 이동">
            <button
              type="button"
              className="doc-page-nav__arrow"
              disabled={currentPage <= 1}
              onClick={() => jumpToDocxPage(currentPage - 1)}
              aria-label="이전 쪽"
            >
              ‹
            </button>
            <span className="doc-page-nav__count">
              {currentPage} / {pageCount}
            </span>
            <button
              type="button"
              className="doc-page-nav__arrow"
              disabled={currentPage >= pageCount}
              onClick={() => jumpToDocxPage(currentPage + 1)}
              aria-label="다음 쪽"
            >
              ›
            </button>
          </nav>
        )}
        {error && <p className="paper--empty">{error}</p>}
        <div ref={containerRef} className="docx-preview-host" aria-label="DOCX 문서 원문" />
        {!error && (
          <p className="image-preview__note">
            {masked
              ? '[유형]으로 바뀐 부분이 가려진 개인정보입니다.'
              : '색칠된 텍스트는 탐지된 정보이며, 현재 선택한 항목은 진한 테두리로 표시됩니다.'}
          </p>
        )}
      </article>
    </div>
  )
}

// docx-preview가 만든 .docx-preview-wrapper(실제 A4 폭 고정, 렌더 옵션 className:'docx-preview'가
// 접두어를 정한다)를 상자 너비에 맞춰 축소한다. transform: scale()은 화면에 그려지는 크기만
// 줄이고 실제 레이아웃 크기(스크롤 영역 계산 기준)는 원래 크기 그대로 남겨서, 진입하자마자
// 스크롤 상자가 그 원래 크기를 기준으로 가운데를 잡아 화면이 한쪽으로 쏠려 보였다. zoom은
// 레이아웃 크기 자체를 줄여 스크롤 영역도 같이 작아지므로 처음부터 왼쪽 위, 즉 페이지 전체가
// 딱 맞게 보인다.
function fitDocxToContainer(container) {
  const wrapper = container.querySelector('.docx-preview-wrapper')
  const page = container.querySelector('.docx-preview')
  if (!wrapper || !page) return
  wrapper.style.zoom = ''
  const availableWidth = container.clientWidth
  const pageWidth = page.offsetWidth
  if (!availableWidth || !pageWidth) return
  const scale = Math.min(1, (availableWidth - 4) / pageWidth)
  wrapper.style.zoom = String(scale)
}

// 렌더된 문서 텍스트 안에서 각 finding이 실제로 나온 자리를 찾는다. finding.start(raw_text
// 오프셋) 순서로 훑으면서, 같은 문자열 값별로 "다음에는 어디서부터 찾을지" 커서를 따로 들고
// 있는다 — text.indexOf(value)만 쓰면 같은 값(반복되는 연락처·이메일 등)은 findings에 항목이
// 몇 개 있든 매번 문서의 첫 자리만 찾아서, 두 번째부터는 원문 그대로 노출되는 화면 전용 버그가
// 있었다(다운로드 사본은 서버가 오프셋으로 처리해서 문제없었다). finding 배열 순서가 뒤섞여
// 와도 정확히 대응하도록 start로 다시 정렬한 뒤 커서를 진행한다.
// docx-preview는 서식이 있는 런(run)마다 인라인 style(배경색·글자색·밑줄)이 붙은 <span>으로
// 감싸서 그린다. 우리가 만든 <mark>가 그 span 안에 들어가면 span의 배경·글자색·밑줄이 우리
// 강조색 위에 그대로 남아 "검게 칠해진 것처럼" 보이거나 밑줄만 도드라져 보인다 — 특히 원본이
// "흰 글자 + 검은 배경"처럼 숨김 트릭을 쓴 자리일수록 더 두드러진다. 개인정보를 가리키는 우리
// 강조색이 항상 또렷이 보이도록, mark를 감싼 런 span의 배경·글자색·밑줄만 지운다(굵게 등 다른
// 서식은 남긴다). 문단(<p>) 이상은 건드리지 않는다 — 런 단위 서식이 아니라 문단·표 배경이라
// 훨씬 넓은 범위에 영향을 줄 수 있어서다.
function clearConflictingRunStyle(mark) {
  let ancestor = mark.parentElement
  while (ancestor && ancestor.tagName === 'SPAN' && ancestor.hasAttribute('style')) {
    ancestor.style.removeProperty('background-color')
    ancestor.style.removeProperty('background')
    ancestor.style.removeProperty('color')
    ancestor.style.removeProperty('text-decoration')
    ancestor.style.removeProperty('text-decoration-color')
    ancestor = ancestor.parentElement
  }
}

function locateDocxMatches(text, findings) {
  const sorted = [...findings].filter((finding) => finding.text).sort((a, b) => (a.start ?? 0) - (b.start ?? 0))
  const cursors = new Map()
  const matches = []
  for (const finding of sorted) {
    const from = cursors.get(finding.text) ?? 0
    const start = text.indexOf(finding.text, from)
    if (start < 0) continue
    matches.push({ start, finding })
    cursors.set(finding.text, start + finding.text.length)
  }
  return matches
}

function highlightDocxFindings(container, findings, selectedId) {
  const walker = window.document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const nodes = []
  let node
  while ((node = walker.nextNode())) {
    if (node.nodeValue) nodes.push(node)
  }
  const text = nodes.map((item) => item.nodeValue).join('')

  // 뒤(오른쪽) 자리부터 칠한다 — surroundContents()가 텍스트 노드를 쪼개서, 앞에서부터 칠하면
  // 그 뒤에 있는 자리를 찾을 때 쓰는 좌표(nodes 배열의 길이 합산)가 이미 쪼개진 노드 기준이라
  // 어긋난다. maskDocxFindings와 같은 이유다.
  const matches = locateDocxMatches(text, findings).sort((a, b) => b.start - a.start)

  for (const { start, finding } of matches) {
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
        mark.className = `hit hit--${groupOf(finding.type)}${finding.id === selectedId ? ' is-selected' : ''}`
        range.surroundContents(mark)
        clearConflictingRunStyle(mark)
      }
      remaining -= to - from
      offset = nextOffset
      if (remaining <= 0) break
    }
  }
}

// highlightDocxFindings와 같은 방식으로 탐지 텍스트가 걸친 문서 노드를 찾되, 칠하는 대신
// 그 자리를 "[유형]" 자리표시자로 바꿔 끼운다. 실제 마스킹된 DOCX 파일은 브라우저에 없고
// (서버만 만든다) masked_text는 오프셋이 raw_text와 어긋나 표·글꼴 구조에 맞춰 넣을 수 없어서,
// 화면에서 원본 레이아웃 위에 직접 바꿔치기하는 방법을 쓴다.
// 겹치는 두 탐지가 같은 노드 안에 있는 드문 경우까지 완벽히 보장하진 않지만(뒤에서부터 바꿔서
// 대부분은 맞는다), highlightDocxFindings와 같은 수준의 정확도로 충분하다.
function maskDocxFindings(container, findings) {
  const walker = window.document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const nodes = []
  let node
  while ((node = walker.nextNode())) {
    if (node.nodeValue) nodes.push(node)
  }
  const text = nodes.map((item) => item.nodeValue).join('')

  // 뒤(오른쪽)에 있는 항목부터 바꾼다 — 앞에서부터 바꾸면 자리표시자로 글자 수가 달라져서
  // 그 뒤 항목을 찾을 때 쓰는 좌표(text.indexOf 결과)가 이미 어긋난 상태가 된다.
  const ordered = locateDocxMatches(text, findings).sort((a, b) => b.start - a.start)

  for (const { start, finding } of ordered) {
    let remaining = finding.text.length
    let offset = 0
    let placed = false
    for (const textNode of nodes) {
      const nextOffset = offset + textNode.nodeValue.length
      if (start >= nextOffset || start + finding.text.length <= offset) {
        offset = nextOffset
        continue
      }
      const from = Math.max(0, start - offset)
      const to = Math.min(textNode.nodeValue.length, start + remaining - offset)
      if (from < to && textNode.parentElement) {
        const range = window.document.createRange()
        range.setStart(textNode, from)
        range.setEnd(textNode, to)
        range.deleteContents()
        // 여러 조각(런)에 걸친 탐지는 첫 조각에만 자리표시자를 넣는다 — 조각마다 넣으면
        // "[이름][이름]"처럼 중복돼 보인다.
        if (!placed) {
          const placeholder = window.document.createElement('mark')
          placeholder.className = 'mask-token'
          placeholder.textContent = `[${finding.label}]`
          range.insertNode(placeholder)
          clearConflictingRunStyle(placeholder)
          placed = true
        }
      }
      remaining -= to - from
      offset = nextOffset
      if (remaining <= 0) break
    }
  }
}

// 이미지의 탐지 bbox는 원본 픽셀 좌표다. 원본의 가로·세로를 기준으로 %로 바꿔
// 브라우저 크기가 달라져도 같은 자리에 하이라이트가 남게 한다.
function ImagePreview({ title, file, findings, filteredOut = [], selectedId, masked = false }) {
  const [imageUrl, setImageUrl] = useState('')
  const [size, setSize] = useState(null)

  useEffect(() => {
    const nextUrl = URL.createObjectURL(file)
    setImageUrl(nextUrl)
    return () => URL.revokeObjectURL(nextUrl)
  }, [file])

  // 마스킹 사본은 서버가 오탐 제외 항목까지 가려서 만든다 — 미리보기도 같은 자리를 검게
  // 칠하도록 마스킹 대상에는 filteredOut을 같이 넣는다. 원문 보기(색칠)는 findings만 쓴다.
  const boxSource = masked ? [...findings, ...filteredOut] : findings
  const boxes = boxSource.filter((finding) => Array.isArray(finding.bbox) && finding.bbox.length === 4)

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
            const boxStyle = {
              left: `${(x0 / size.width) * 100}%`,
              top: `${(y0 / size.height) * 100}%`,
              width: `${((x1 - x0) / size.width) * 100}%`,
              height: `${((y1 - y0) / size.height) * 100}%`,
            }
            // masked일 때는 실제 마스킹 사본처럼 위치만 검게 칠한다(유형별 색·선택 강조는
            // 원문 보기에서만 의미가 있다 — 가린 자리에는 "무엇인지"를 다시 드러내지 않는다).
            return masked ? (
              <span key={finding.id} className="image-hit image-hit--redacted" style={boxStyle} aria-label="가려진 영역" />
            ) : (
              <mark
                key={finding.id}
                data-finding-id={finding.id}
                className={`image-hit image-hit--${groupOf(finding.type)}${finding.id === selectedId ? ' is-selected' : ''}`}
                style={boxStyle}
                aria-label={`${finding.label} 탐지 위치`}
              />
            )
          })}
        </div>
        <p className="image-preview__note">
          {masked ? '검게 칠해진 영역이 가려진 개인정보입니다.' : '색칠된 영역은 탐지된 정보이며, 진한 테두리는 현재 선택한 항목입니다.'}
        </p>
      </article>
    </div>
  )
}
