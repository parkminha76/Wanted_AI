import { useEffect, useMemo, useState } from 'react'
import { api } from '../shared/api.js'
import { Button } from '../shared/components/index.js'
import { GROUPS, GROUP_ORDER, countByGroup } from '../shared/findings.js'
import DocumentPreview from './DocumentPreview.jsx'
import EmptyResult from './EmptyResult.jsx'
import FileSwitcher from './FileSwitcher.jsx'
import SelectiveMaskPanel from './SelectiveMaskPanel.jsx'
import './scanner.css'

// 선택 마스킹은 모든 항목을 전체 마스킹으로 고른 상태에서 시작한다 — 사용자가 빼는 쪽이 안전하다.
function defaultChoices(findings = []) {
  return Object.fromEntries(findings.map((finding) => [finding.id, { checked: true, action: 'full' }]))
}

const IDLE = { loading: false, error: '', result: null }

export default function MaskPage({ batch, file, fileIndex, onSelectFile, navigate, uploads = [], batchSource = null }) {
  const [mode, setMode] = useState('full') // 'full' | 'select'
  const [showMasked, setShowMasked] = useState(true)
  const [options, setOptions] = useState(null)
  // 선택과 사본 결과는 파일마다 따로다. 다른 파일로 바꾸면 key가 달라져 처음 상태로 돌아간다.
  const fileKey = file ? file.file_id || `${fileIndex}-${file.filename}` : ''
  const [choiceState, setChoiceState] = useState({ key: '', items: {} })
  const [maskState, setMaskState] = useState({ key: '', ...IDLE })
  // 사본은 검사 후 30분이 지나면 서버에서 지워진다(main.py MASKED_FILE_TTL_SECONDS).
  const [expired, setExpired] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .maskingOptions()
      .then((value) => {
        if (!cancelled) setOptions(value)
      })
      .catch(() => {
        // 기준표를 못 받으면 부분 마스킹 선택지만 숨긴다. 전체 마스킹 선택은 그대로 된다.
        if (!cancelled) setOptions({ types: [] })
      })
    return () => {
      cancelled = true
    }
  }, [])

  const standard = useMemo(() => {
    const types = options?.types ?? []
    return {
      types: new Set(types.filter((item) => item.supports_standard).map((item) => item.type)),
      descriptions: Object.fromEntries(types.map((item) => [item.type, item.standard_description])),
    }
  }, [options])

  if (!batch || !file) return <EmptyResult navigate={navigate} />

  const choices = choiceState.key === fileKey ? choiceState.items : defaultChoices(file.findings)
  const masking = maskState.key === fileKey ? maskState : IDLE
  // 서버가 돌려주는 filename은 올린 파일 이름(경로 성분 제거)이라 File.name과 같다.
  const sourceFile = uploads.find((upload) => upload.name === file.filename) ?? null
  // 샘플 문서는 브라우저에 원본 File이 없어서 서버에 있는 샘플을 이름으로 지정한다(POST /samples/mask).
  const canCreateCopy = Boolean(sourceFile) || batchSource === 'samples'
  const selectMode = mode === 'select'

  function actionOf(finding) {
    const action = choices[finding.id]?.action ?? 'full'
    return action === 'standard' && standard.types.has(finding.type) ? 'standard' : 'full'
  }

  const selectedFindings = file.findings.filter((finding) => choices[finding.id]?.checked)
  const previewSelection = Object.fromEntries(selectedFindings.map((finding) => [finding.id, actionOf(finding)]))

  function updateChoices(updater) {
    setChoiceState({ key: fileKey, items: updater(choices) })
    // 선택이 바뀌면 전에 만든 사본은 지금 선택과 맞지 않으므로 지운다.
    setMaskState({ key: fileKey, ...IDLE })
  }

  const toggle = (id) =>
    updateChoices((items) => ({ ...items, [id]: { ...items[id], checked: !items[id]?.checked } }))

  const toggleMany = (ids, checked) =>
    updateChoices((items) => {
      const next = { ...items }
      for (const id of ids) next[id] = { ...next[id], checked }
      return next
    })

  const setTypeAction = (type, action) =>
    updateChoices((items) => {
      const next = { ...items }
      for (const finding of file.findings) {
        if (finding.type === type) next[finding.id] = { ...next[finding.id], action }
      }
      return next
    })

  async function applySelection() {
    const selections = selectedFindings.map((finding) => ({
      id: finding.id,
      type: finding.type,
      start: finding.start,
      end: finding.end,
      action: actionOf(finding),
    }))
    setMaskState({ key: fileKey, loading: true, error: '', result: null })
    try {
      const result = sourceFile
        ? await api.maskSelected(sourceFile, selections)
        : await api.maskSample(file.filename, selections)
      setMaskState({ key: fileKey, loading: false, error: '', result })
    } catch (err) {
      setMaskState({ key: fileKey, loading: false, error: err.message, result: null })
    }
  }

  // 다운로드를 <a href>로 바로 걸면, 보관 기간이 지났을 때 FastAPI가 돌려준 404 JSON이
  // 화면에 그대로 뜬다. 먼저 상태 코드만 확인하고 살아 있을 때만 브라우저에 넘긴다.
  // ponytail: 요청이 한 번 더 간다. 본문은 받지 않고 버리므로(cancel) 사실상 헤더 한 번이고,
  //           파일 이름은 서버가 붙인 Content-Disposition을 그대로 쓸 수 있다(CORS로는 못 읽는다).
  //           한 번에 끝내려면 blob으로 받아야 하는데 그러면 파일 이름 규칙을 화면이 베껴야 한다.
  async function downloadCopy(url) {
    try {
      const response = await fetch(url)
      response.body?.cancel()
      if (response.status === 404) {
        setExpired(true)
        return
      }
    } catch {
      // 서버에 닿지 못한 것은 만료가 아니다. 평소대로 브라우저에 맡긴다.
    }
    window.location.href = url
  }

  // 사본이 사라진 뒤에는 다시 받을 방법이 없다 — 파일을 다시 올려 검사하는 것이 유일한 재시도다.
  const expiredNotice = (
    <div className="stack stack--tight">
      <p className="alert alert--error" role="alert">
        사본이 만료되었습니다. 다시 시도하세요.
      </p>
      <Button size="lg" block onClick={() => navigate('')}>
        다시 시도하기
      </Button>
    </div>
  )

  const counts = countByGroup(file.findings)
  const summary = GROUP_ORDER.filter((key) => counts[key] > 0).map((key) =>
    key === 'hidden' ? `숨겨진 명령어 ${counts[key]}건을 [숨은 명령]으로 바꿈` : `${GROUPS[key].label} ${counts[key]}건 마스킹 완료`,
  )
  const downloadableCount = batch.results.filter((result) => result.file_id).length

  let previewTitle = '원문 (탐지 위치 표시)'
  // 선택 마스킹 미리보기는 사본을 만든 뒤에도 화면에서 계산한 값을 그대로 쓴다. 서버 사본 텍스트(masked_text)와
  // 글자 하나까지 같다는 것을 npm run check:masking으로 확인하고, 이렇게 해야 쪽 나누기가 유지된다.
  if (showMasked) {
    if (!selectMode) previewTitle = '마스킹 사본'
    else previewTitle = masking.result ? '선택 마스킹 사본' : '선택 마스킹 미리보기'
  }

  return (
    <div className="container mask-page">
      <button type="button" className="back-link" onClick={() => navigate('results')}>
        ← 분석 결과로 돌아가기
      </button>
      <div className="page-head">
        <div>
          <h1 className="page-title">안전하게 마스킹된 문서</h1>
          <p className="page-desc">
            {selectMode
              ? '가릴 항목과 방식을 직접 골라 사본을 만듭니다.'
              : '위험 요소를 [계좌번호]처럼 유형 이름으로 바꿔, AI 도구에 넣어도 문맥이 유지되게 했습니다.'}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={showMasked}
          className="switch"
          onClick={() => setShowMasked((value) => !value)}
        >
          <span className="switch__track" aria-hidden="true">
            <span className="switch__thumb" />
          </span>
          마스킹 적용
        </button>
      </div>

      <FileSwitcher results={batch.results} index={fileIndex} onSelect={onSelectFile} />

      <div className="tabs" role="tablist" aria-label="마스킹 방식">
        <button
          type="button"
          role="tab"
          id="mask-tab-full"
          aria-selected={!selectMode}
          aria-controls="mask-panel"
          className="tabs__tab"
          onClick={() => setMode('full')}
        >
          전체 마스킹
        </button>
        <button
          type="button"
          role="tab"
          id="mask-tab-select"
          aria-selected={selectMode}
          aria-controls="mask-panel"
          className="tabs__tab"
          onClick={() => setMode('select')}
        >
          선택 마스킹
        </button>
      </div>

      <section
        id="mask-panel"
        role="tabpanel"
        aria-labelledby={selectMode ? 'mask-tab-select' : 'mask-tab-full'}
        className="mask-grid rv"
      >
        <div className="panel">
          <div className="panel__heading">
            <b>{previewTitle}</b>
            <small>{file.filename || '텍스트'}</small>
          </div>
          {selectMode && showMasked && (
            <ul className="preview-legend" aria-label="미리보기 표시 설명">
              <li>
                <span className="mask-token">[유형]</span> 전체 마스킹
              </li>
              <li>
                <span className="hit hit--standard">010-****</span> 부분 마스킹
              </li>
              <li>
                <span className="hit-excluded">값</span> 가리지 않음
              </li>
            </ul>
          )}
          <DocumentPreview
            title={file.filename}
            text={file.raw_text}
            findings={file.findings}
            masked={showMasked}
            maskedText={file.masked_text}
            selection={selectMode && showMasked ? previewSelection : null}
            pages={file.pages}
          />
        </div>

        {selectMode ? (
          <aside className="panel mask-select" aria-label="선택 마스킹">
            <div>
              <h2 className="mask-select__title">가릴 항목을 고르세요</h2>
              <p className="mask-select__desc">
                체크한 항목만 가립니다. 이름·전화번호처럼 부분 마스킹을 지원하는 유형은 일부만 가릴 수도 있습니다.
              </p>
            </div>

            {file.findings.length === 0 ? (
              <p className="issues__empty">가릴 항목이 없습니다.</p>
            ) : (
              <SelectiveMaskPanel
                findings={file.findings}
                choices={choices}
                standardTypes={standard.types}
                descriptions={standard.descriptions}
                onToggle={toggle}
                onToggleMany={toggleMany}
                onActionChange={setTypeAction}
              />
            )}

            {!canCreateCopy && file.findings.length > 0 && (
              <p className="alert alert--info">
                올린 원본 파일이 브라우저에 없어 사본을 만들 수 없습니다. 새로고침한 뒤라면 파일을 다시 올려 주세요.
              </p>
            )}
            {masking.error && (
              <p className="alert alert--error" role="alert">
                {masking.error}
              </p>
            )}

            {expired ? (
              expiredNotice
            ) : masking.result ? (
              <div className="stack stack--tight">
                <p className="alert alert--info" role="status">
                  선택한 항목 {masking.result.selected_findings}개를 가린 사본을 만들었습니다. 미리보기와 같은 내용입니다.
                </p>
                <Button size="lg" block onClick={() => downloadCopy(api.downloadUrl(masking.result.file_id))}>
                  선택 마스킹 사본 다운로드
                </Button>
              </div>
            ) : (
              <Button
                size="lg"
                block
                disabled={!canCreateCopy || selectedFindings.length === 0 || masking.loading}
                onClick={applySelection}
              >
                {masking.loading ? (
                  <>
                    <span className="spinner" aria-hidden="true" /> 사본 만드는 중…
                  </>
                ) : (
                  `선택한 ${selectedFindings.length}개 가려서 사본 만들기`
                )}
              </Button>
            )}
            <p className="mask-summary__note">
              원본은 서버에 남기지 않습니다. 사본을 만들 때 올리신 파일을 한 번 더 보내 다시 검사하고, 끝나면 바로 지웁니다.
            </p>
          </aside>
        ) : (
          <aside className="panel mask-summary">
            <div className="mask-summary__shield" aria-hidden="true">
              ♢
            </div>
            <h2 className="mask-summary__title">
              {file.findings.length > 0 ? '중요한 정보가 안전하게 보호되었습니다.' : '가릴 위험 요소가 없었습니다.'}
            </h2>
            {summary.length > 0 && (
              <ul className="checklist">
                {summary.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}

            {expired ? (
              expiredNotice
            ) : (
              <>
                {file.file_id ? (
                  <Button size="lg" block onClick={() => downloadCopy(api.downloadUrl(file.file_id))}>
                    마스킹된 문서 다운로드
                  </Button>
                ) : (
                  <p className="alert alert--info">이 파일은 원본 형식의 사본을 만들지 못했습니다. 왼쪽 텍스트 사본을 참고해 주세요.</p>
                )}
                {batch.batch_id && downloadableCount > 1 && (
                  <Button variant="secondary" block onClick={() => downloadCopy(api.downloadAllUrl(batch.batch_id))}>
                    사본 {downloadableCount}개 한 번에 받기 (.zip)
                  </Button>
                )}
                <p className="mask-summary__note">원본은 서버에서 이미 삭제되었습니다. 사본은 검사 후 30분 동안만 받을 수 있습니다.</p>
              </>
            )}
          </aside>
        )}
      </section>
    </div>
  )
}
