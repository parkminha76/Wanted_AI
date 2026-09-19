import { useEffect, useRef, useState } from 'react'
import { Button, SectionRail } from '../shared/components/index.js'
import { CHECKS, CHECK_ORDER, checkOf, countByCheck, lineNumberAt } from '../shared/findings.js'
import EmptyResult from './EmptyResult.jsx'
import FileSwitcher from './FileSwitcher.jsx'
import HiddenCommandModal from './HiddenCommandModal.jsx'
import './scanner.css'

// 검사 결과지. 답하는 순서가 화면 순서다.
//   ① 이 문서 괜찮나   — 한 줄 판정
//   ② 무엇을 검사했나   — 여섯 항목의 정상·주의·위험 (깨끗한 항목도 보여준다)
//   ③ 어디가 문제인가   — 항목별로 묶은 문제 카드
// ④왜 문제인가와 ⑤어떻게 고치나는 상세 화면(FindingDetailPage)이 맡는다. 한 화면에
// 다 넣으면 "그래서 괜찮은 거야?"에 답하기 전에 읽을 것이 너무 많아진다.
//
// ②에서 0건인 항목을 지우지 않는 이유: "주민등록번호는 확인했는데 없었습니다"가
// 보여야 검사받았다는 느낌이 난다. 찾은 것만 보여주면 목록이지 결과지가 아니다.

const TONE_LABEL = { high: '위험', medium: '주의' }

// 탐지 위치를 "12–13줄", "3쪽 외" 처럼 한 마디로. 쪽 정보가 있으면 쪽을 우선한다.
function whereOf(findings, rawText) {
  const pages = findings.map((finding) => finding.page).filter((page) => page != null)
  if (pages.length) {
    const min = Math.min(...pages)
    const max = Math.max(...pages)
    return min === max ? `${min}쪽` : `${min}–${max}쪽`
  }
  const lines = findings.map((finding) => lineNumberAt(rawText, finding.start))
  const min = Math.min(...lines)
  const max = Math.max(...lines)
  return min === max ? `${min}줄` : `${min}–${max}줄`
}

export default function ResultsPage({ batch, file, fileIndex, onSelectFile, onSelectFinding, navigate, onCancelFile }) {
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

  if (!batch || !file) return <EmptyResult navigate={navigate} />

  const counts = countByCheck(file.findings)
  const rows = CHECK_ORDER.map((key) => ({ key, ...CHECKS[key], count: counts[key] }))
  const tally = {
    high: rows.filter((row) => row.count > 0 && row.tone === 'high').length,
    medium: rows.filter((row) => row.count > 0 && row.tone === 'medium').length,
    ok: rows.filter((row) => row.count === 0).length,
  }

  // ③ 문제 카드 — 건별로 늘어놓지 않고 검사 항목별로 묶는다. 전화번호 4건이 각각
  // 한 줄을 차지할 이유가 없다.
  const problems = rows
    .filter((row) => row.count > 0)
    .map((row) => {
      const found = file.findings.filter((finding) => checkOf(finding.type) === row.key)
      const kinds = [...new Set(found.map((finding) => finding.label))]
      return { ...row, found, kinds, where: whereOf(found, file.raw_text) }
    })

  const guide = file.action_guide ?? null
  const clean = file.findings.length === 0

  function openProblem(problem) {
    onSelectFinding(problem.found[0].id)
    navigate('results/detail')
  }

  return (
    <div className="container results-page">
      <SectionRail
        sections={[
          { id: 'verdict', label: '판정' },
          { id: 'checks', label: '검사 항목' },
          { id: 'issues', label: '발견된 문제' },
        ]}
      />

      <div className="page-head rv">
        <div>
          <h1 className="page-title">검사 결과</h1>
          <p className="page-desc break-anywhere">
            {file.filename || '텍스트'}
            {batch.total_files > 1 ? ` · 파일 ${batch.total_files}개 중 ${fileIndex + 1}번째` : ''}
          </p>
        </div>
        <div className="page-head__actions">
          <Button variant="secondary" onClick={() => navigate('')}>
            다른 문서 검사하기
          </Button>
          <Button onClick={() => navigate('results/mask')}>↓ 안전한 사본 받기</Button>
        </div>
      </div>

      {batch.note && <p className="alert alert--info">{batch.note}</p>}
      <FileSwitcher results={batch.results} index={fileIndex} onSelect={onSelectFile} />
      {file.error && (
        <p className="alert alert--error" role="alert">
          {file.error}
        </p>
      )}

      {/* ① 판정. 문구는 서버가 만든다(schema.build_action_guide) — 화면마다 다른 말을 하지 않게. */}
      <section id="verdict" className={`verdict verdict--${clean ? 'low' : file.level} rv`} aria-label="검사 판정">
        <span className="verdict__mark" aria-hidden="true">
          {clean ? '✓' : '!'}
        </span>
        <div className="verdict__say">
          <p className="verdict__title">{guide?.title ?? (clean ? '바로 공유할 수 있는 상태입니다' : '공유 전에 먼저 조치하세요')}</p>
          <p className="verdict__desc">
            {/* 총평(guide.description)은 "132건을 바탕으로 정리했습니다"처럼 건수만 센다.
                우선 조치 첫 줄이 무엇이 문제인지 실제로 말해 주므로 그쪽을 먼저 쓴다. */}
            {guide?.actions?.[0]?.description ?? guide?.description ?? '검사 결과를 아래에서 확인하세요.'}
          </p>
        </div>
      </section>

      <dl className="tally rv">
        <div>
          <dt>검사 항목</dt>
          <dd>{CHECK_ORDER.length}</dd>
        </div>
        <div className="tally--high">
          <dt>위험</dt>
          <dd>{tally.high}</dd>
        </div>
        <div className="tally--mid">
          <dt>주의</dt>
          <dd>{tally.medium}</dd>
        </div>
        <div className="tally--ok">
          <dt>정상</dt>
          <dd>{tally.ok}</dd>
        </div>
      </dl>

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

      {/* ② 무엇을 검사했나 */}
      <section id="checks" className="block rv" aria-labelledby="checks-title">
        <h2 id="checks-title" className="block__title">
          무엇을 검사했나
        </h2>
        <p className="block__desc">문서 한 건에 대해 여섯 가지를 확인했습니다.</p>
        <ul className="checks">
          {rows.map((row) => (
            <li key={row.key} className={row.count === 0 ? 'is-clean' : undefined}>
              <span className="checks__name">{row.label}</span>
              <span className="checks__covers">{row.covers}</span>
              <span className={`state state--${row.count === 0 ? 'ok' : row.tone}`}>
                {row.count === 0 ? '정상' : `${TONE_LABEL[row.tone]} ${row.count}건`}
              </span>
            </li>
          ))}
        </ul>
        {file.filtered_count > 0 && (
          <p className="checks__aside">
            이 밖에 {file.filtered_count}건은 검사했지만 개인정보가 아니라고 판단해 제외했습니다. 상세 화면에서 볼 수 있습니다.
          </p>
        )}
      </section>

      {/* ③ 어디가 문제인가 */}
      <section id="issues" className="block rv" aria-labelledby="issues-title">
        <h2 id="issues-title" className="block__title">
          어디가 문제인가
        </h2>
        {problems.length === 0 ? (
          <p className="block__desc">가려야 할 항목을 찾지 못했습니다.</p>
        ) : (
          <>
            <p className="block__desc">심각한 순서대로 놓았습니다. 누르면 문서에서 그 자리를 펴 보여줍니다.</p>
            <ol className="problems">
              {problems.map((problem, index) => (
                <li key={problem.key}>
                  <button type="button" className={`problem problem--${problem.tone}`} onClick={() => openProblem(problem)}>
                    <span className="problem__no">{index + 1}</span>
                    <span className="problem__main">
                      <b>{problem.lead}</b>
                      <span className="problem__kinds">{problem.kinds.join(' · ')}</span>
                    </span>
                    <span className="problem__where">
                      {problem.where} · {problem.count}건
                    </span>
                    <span className="problem__go" aria-hidden="true">
                      →
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </>
        )}
      </section>

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
