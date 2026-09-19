import { useState } from 'react'
import { Button } from '../shared/components/index.js'
import {
  CHECKS,
  SOURCE_LABELS,
  checkOf,
  explanationFor,
  formatPercent,
  lineNumberAt,
  placeholderFor,
} from '../shared/findings.js'
import DocumentPreview from './DocumentPreview.jsx'
import EmptyResult from './EmptyResult.jsx'
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

const toneOf = (finding) => CHECKS[checkOf(finding.type)].tone

export default function FindingDetailPage({ batch, file, findingId, onSelectFinding, navigate }) {
  // 결과지에서 "계좌·카드 정보" 카드를 눌러 왔는데 "132건 중 124번째"가 뜨면 내가 뭘 눌렀는지
  // 알 수 없다. 들어올 때 고른 항목의 심각도로 먼저 걸러 두고, 거르개는 사용자가 다시 바꾼다.
  const [filter, setFilter] = useState(() => {
    const entry = file?.findings?.find((finding) => finding.id === findingId)
    return entry ? toneOf(entry) : 'all'
  })

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

  return (
    <div className="container detail-page">
      <button type="button" className="back-link" onClick={() => navigate('results')}>
        ← 검사 결과로 돌아가기
      </button>

      <div className="page-head rv">
        <div>
          <h1 className="page-title">어디가, 왜 문제인가</h1>
          <p className="page-desc break-anywhere">
            {file.filename || '텍스트'}
            {finding ? ` · 문제 ${list.length}건 중 ${index + 1}번째` : ''}
          </p>
        </div>
        <div className="page-head__actions">
          <Button onClick={() => navigate('results/mask')}>↓ 안전한 사본 받기</Button>
        </div>
      </div>

      <div className="detail-filters" role="group" aria-label="항목 거르기">
        <span className="detail-filters__label">보기</span>
        {FILTERS.map((item) => (
          <button
            key={item.key}
            type="button"
            className="chipbtn"
            aria-pressed={filter === item.key}
            onClick={() => setFilter(item.key)}
          >
            {item.label} {counts[item.key]}
          </button>
        ))}
        {file.filtered_count > 0 && (
          <button type="button" className="chipbtn" aria-pressed={excluded} onClick={() => setFilter('excluded')}>
            제외한 항목 {file.filtered_count}
          </button>
        )}
      </div>

      <div className="detail-split">
        <div className="panel">
          <div className="panel__heading">
            <b>문서 원문</b>
            <small>진한 자리가 지금 보고 있는 곳입니다</small>
          </div>
          <DocumentPreview
            title={file.filename}
            text={file.raw_text}
            findings={file.findings}
            selectedId={finding?.id}
            pages={file.pages}
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
                <b>{finding.label}</b>
              </div>

              <dl className="facts">
                <div>
                  <dt>위치</dt>
                  <dd>{where}</dd>
                </div>
                <div>
                  <dt>검사 항목</dt>
                  <dd>{check.label}</dd>
                </div>
                <div>
                  <dt>내용</dt>
                  <dd>
                    <code className="facts__value">{finding.text}</code>
                  </dd>
                </div>
                <div>
                  <dt>찾은 방법</dt>
                  <dd>{SOURCE_LABELS[finding.source] ?? finding.source}</dd>
                </div>
              </dl>

              <div className="why">
                <h2>왜 문제인가</h2>
                <p>{explanationFor(finding.type)}</p>
                {evidence.hidden_reason_text && <p>숨겨져 있던 방식: {evidence.hidden_reason_text}</p>}
              </div>

              <div className="why why--fix">
                <h2>이렇게 고치세요</h2>
                <p>{advice?.description ?? '원본 대신 아래처럼 가린 사본을 공유하세요. 문서 서식은 그대로 유지됩니다.'}</p>
                <div className="beforeafter">
                  <span className="beforeafter__before">{finding.text}</span>
                  <span className="beforeafter__after">{placeholderFor(finding)}</span>
                </div>
              </div>

              <div className="detail-card__nav">
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
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
