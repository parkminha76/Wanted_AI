import { useEffect, useRef, useState } from 'react'
import { Button, RiskBadge } from '../shared/components/index.js'
import { GROUPS, GROUP_ORDER, countByGroup, formatPercent, groupOf } from '../shared/findings.js'
import DocumentPreview from './DocumentPreview.jsx'
import EmptyResult from './EmptyResult.jsx'
import FileSwitcher from './FileSwitcher.jsx'
import HiddenCommandModal from './HiddenCommandModal.jsx'
import './scanner.css'

export default function ResultsPage({ batch, file, fileIndex, onSelectFile, findingId, onSelectFinding, navigate, onCancelFile }) {
  const [tab, setTab] = useState('preview')
  const [filter, setFilter] = useState('all')
  const [modalOpen, setModalOpen] = useState(false)
  const shownHidden = useRef(new Set())

  // 숨은 명령이 있는 파일은 처음 볼 때 한 번 팝업을 띄운다.
  const fileKey = file ? file.file_id || `${fileIndex}-${file.filename}` : ''
  const hasHidden = Boolean(file?.has_hidden_command)
  useEffect(() => {
    if (hasHidden && !shownHidden.current.has(fileKey)) {
      shownHidden.current.add(fileKey)
      setModalOpen(true)
    }
  }, [fileKey, hasHidden])

  useEffect(() => {
    setFilter('all')
    setTab('preview')
  }, [fileKey])

  if (!batch || !file) return <EmptyResult navigate={navigate} />

  const counts = countByGroup(file.findings)
  const visible = filter === 'all' ? file.findings : file.findings.filter((finding) => groupOf(finding.type) === filter)
  const selected = file.findings.find((finding) => finding.id === findingId) ?? null

  return (
    <div className="container results-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">분석이 완료되었습니다.</h1>
          <p className="page-desc">
            파일 {batch.total_files}개에서 위험 요소 {batch.total_findings}건을 찾았습니다. 위험도가 높은 파일부터 보여 드립니다.
          </p>
        </div>
        <div className="page-head__actions">
          <Button variant="secondary" onClick={() => navigate('')}>
            다시 검사하기
          </Button>
          <Button onClick={() => navigate('results/mask')}>↓ 마스킹 사본 받기</Button>
        </div>
      </div>

      {batch.note && <p className="alert alert--info">{batch.note}</p>}
      <FileSwitcher results={batch.results} index={fileIndex} onSelect={onSelectFile} />
      {file.error && (
        <p className="alert alert--error" role="alert">
          {file.error}
        </p>
      )}

      <section className={`risk-card risk-card--${file.level}`} aria-label="위험도 요약">
        <div className="risk-card__score">
          <span className="risk-card__icon" aria-hidden="true">
            !
          </span>
          <div>
            <small>위험도</small>
            <p className="risk-card__number">
              <b>{Math.round(file.risk_score)}</b>
              <span>/100</span>
            </p>
            <RiskBadge level={file.level} />
          </div>
        </div>
        <ul className="risk-card__list">
          {GROUP_ORDER.map((key) => (
            <li key={key} className={counts[key] === 0 ? 'is-zero' : undefined}>
              <span>{GROUPS[key].label}</span>
              <b>{counts[key]}건</b>
            </li>
          ))}
        </ul>
      </section>

      {hasHidden && (
        <div className="hidden-banner">
          <div>
            <b>숨은 AI 명령이 발견되었습니다</b>
            <p>이 문서를 AI 도구에 넣기 전에 어떤 명령인지 확인하세요.</p>
          </div>
          <Button variant="danger" onClick={() => setModalOpen(true)}>
            숨은 명령 확인
          </Button>
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="결과 보기">
        <button
          type="button"
          role="tab"
          id="tab-preview"
          aria-selected={tab === 'preview'}
          aria-controls="panel-preview"
          className="tabs__tab"
          onClick={() => setTab('preview')}
        >
          문서 미리보기
        </button>
        <button
          type="button"
          role="tab"
          id="tab-filtered"
          aria-selected={tab === 'filtered'}
          aria-controls="panel-filtered"
          className="tabs__tab"
          onClick={() => setTab('filtered')}
        >
          오탐으로 제외한 항목 {file.filtered_count}
        </button>
      </div>

      {tab === 'preview' ? (
        <section id="panel-preview" role="tabpanel" aria-labelledby="tab-preview" className="analysis-grid">
          <div className="panel">
            <div className="panel__heading">
              <b>문서 미리보기</b>
              <small>{file.filename || '텍스트'}</small>
            </div>
            <DocumentPreview
              title={file.filename}
              text={file.raw_text}
              findings={file.findings}
              selectedId={findingId}
              pages={file.pages}
            />
          </div>

          <aside className="panel issues" aria-label="탐지된 항목">
            <div className="panel__heading">
              <b>탐지된 항목 {file.findings.length}건</b>
              <label className="visually-hidden" htmlFor="issue-filter">
                항목 종류로 거르기
              </label>
              <select id="issue-filter" className="select" value={filter} onChange={(event) => setFilter(event.target.value)}>
                <option value="all">전체</option>
                {GROUP_ORDER.map((key) => (
                  <option key={key} value={key}>
                    {GROUPS[key].label} ({counts[key]})
                  </option>
                ))}
              </select>
            </div>

            {visible.length === 0 ? (
              <p className="issues__empty">{file.findings.length === 0 ? '탐지된 위험 요소가 없습니다.' : '이 종류의 항목은 없습니다.'}</p>
            ) : (
              <ul className="issues__list">
                {visible.map((finding) => {
                  const group = groupOf(finding.type)
                  const isSelected = finding.id === findingId
                  return (
                    <li key={finding.id}>
                      <button
                        type="button"
                        className={`issue${isSelected ? ' is-selected' : ''}`}
                        aria-pressed={isSelected}
                        onClick={() => onSelectFinding(finding.id)}
                      >
                        <span className={`issue__dot issue__dot--${group}`} aria-hidden="true" />
                        <span className="issue__body">
                          <b>
                            [{GROUPS[group].label}] {finding.label}
                          </b>
                          <span className="issue__value">{finding.text}</span>
                        </span>
                        <span className="issue__confidence">{formatPercent(finding.confidence)}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}

            <Button variant="secondary" block disabled={!selected} onClick={() => navigate('results/detail')}>
              {selected ? '선택 항목 상세 보기 →' : '항목을 고르면 상세를 볼 수 있어요'}
            </Button>
          </aside>
        </section>
      ) : (
        <section id="panel-filtered" role="tabpanel" aria-labelledby="tab-filtered" className="panel filtered-panel">
          <div className="panel__heading">
            <b>오탐으로 제외한 항목 {file.filtered_count}건</b>
          </div>
          <p className="filtered-panel__desc">
            직접 학습한 오탐 제거 분류기가 문맥을 보고 개인정보가 아니라고 판단한 값입니다. 위험도 점수에 들어가지 않습니다.
          </p>
          {file.filtered_out.length === 0 ? (
            <p className="issues__empty">제외한 항목이 없습니다.</p>
          ) : (
            <ul className="finding-list">
              {file.filtered_out.map((finding) => (
                <li key={finding.id} className="finding-list__item">
                  <div className="finding-list__head">
                    <strong>{finding.label}</strong>
                    {typeof finding.evidence?.prob_positive === 'number' && (
                      <span className="chip">실제 개인정보일 확률 {formatPercent(finding.evidence.prob_positive)}</span>
                    )}
                  </div>
                  <p className="finding-list__value">{finding.text}</p>
                  <p className="finding-list__reason">{finding.reason}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <HiddenCommandModal
        open={modalOpen}
        result={file}
        onClose={() => setModalOpen(false)}
        onRemove={() => {
          setModalOpen(false)
          navigate('results/mask')
        }}
        onIgnore={() => setModalOpen(false)}
        onCancelFile={() => {
          setModalOpen(false)
          onCancelFile(file)
        }}
      />
    </div>
  )
}
