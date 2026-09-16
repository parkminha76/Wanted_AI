import { Button, Card } from '../shared/components/index.js'
import { GROUPS, SOURCE_LABELS, explanationFor, formatPercent, groupOf, lineNumberAt } from '../shared/findings.js'
import EmptyResult from './EmptyResult.jsx'
import './scanner.css'

export default function FindingDetailPage({ batch, file, findingId, onSelectFinding, navigate }) {
  if (!batch || !file) return <EmptyResult navigate={navigate} />

  const findings = file.findings
  const finding = findings.find((item) => item.id === findingId) ?? findings[0]

  if (!finding) {
    return (
      <div className="container detail-page">
        <button type="button" className="back-link" onClick={() => navigate('results')}>
          ← 분석 결과로 돌아가기
        </button>
        <Card title="탐지된 항목이 없습니다" description="이 파일에서는 위험 요소를 찾지 못했습니다." />
      </div>
    )
  }

  const index = findings.indexOf(finding)
  const group = groupOf(finding.type)
  const evidence = finding.evidence ?? {}
  const location = finding.page != null ? `${finding.page}쪽` : `${lineNumberAt(file.raw_text, finding.start)}번째 줄`
  const howHidden = evidence.hidden_reason_text || evidence.hidden?.reason

  const rows = [
    ['탐지 유형', GROUPS[group].label],
    ['항목', finding.label],
    ['탐지 내용', <span className="detail-card__value">{finding.text}</span>],
    ['위치', location],
    ['탐지 방식', SOURCE_LABELS[finding.source] ?? finding.source],
  ]

  const basis = [
    finding.reason,
    evidence.checksum === 'pass' && '체크섬(검증 숫자) 계산을 통과한 형식입니다.',
    typeof evidence.prob_positive === 'number' &&
      `오탐 제거 분류기가 문맥을 보고 실제 개인정보일 확률을 ${formatPercent(evidence.prob_positive)}로 판단했습니다.`,
    howHidden && `숨겨진 방식: ${howHidden}`,
    evidence.restored && `복원한 문장: ${evidence.restored}`,
  ].filter(Boolean)

  return (
    <div className="container detail-page">
      <button type="button" className="back-link" onClick={() => navigate('results')}>
        ← 분석 결과로 돌아가기
      </button>
      <header>
        <h1 className="page-title">탐지 결과 상세</h1>
        <p className="page-desc break-anywhere">
          {file.filename || '텍스트'} · {index + 1} / {findings.length}번째 항목
        </p>
      </header>

      <Card className="rv">
        <div className="detail-card__title">
          <span className={`group-icon group-icon--${group}`} aria-hidden="true">
            ▣
          </span>
          <b>{GROUPS[group].label}</b>
          <span className="chip detail-card__confidence">확신도 {formatPercent(finding.confidence)}</span>
        </div>

        <dl className="detail-list">
          {rows.map(([term, value]) => (
            <div key={term} className="detail-list__row">
              <dt>{term}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>

        <hr className="detail-card__divider" />
        <h2 className="detail-card__heading">왜 위험한가요?</h2>
        <p className="detail-card__text">{explanationFor(finding.type)}</p>

        <hr className="detail-card__divider" />
        <h2 className="detail-card__heading">AI의 판단 근거</h2>
        <ul className="basis-list">
          {basis.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </Card>

      <div className="detail-page__nav">
        <Button variant="secondary" disabled={index <= 0} onClick={() => onSelectFinding(findings[index - 1].id)}>
          ← 이전 항목
        </Button>
        <Button
          variant="secondary"
          disabled={index >= findings.length - 1}
          onClick={() => onSelectFinding(findings[index + 1].id)}
        >
          다음 항목 →
        </Button>
      </div>
      <Button size="lg" block onClick={() => navigate('results/mask')}>
        안전하게 마스킹하기 →
      </Button>
    </div>
  )
}
