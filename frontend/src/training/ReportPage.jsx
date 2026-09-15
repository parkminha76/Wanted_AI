import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../shared/api.js'
import { Button, Card } from '../shared/components/index.js'
import './training.css'

// 훈련 결과 리포트. 하단에 스캐너로 넘어가는 전환 버튼이 있다.
export default function ReportPage({ training, navigate }) {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // 리포트 요청은 외부 AI(Defender)를 호출한다. 개발 모드(StrictMode)에서 effect가 두 번 돌아
  // 같은 리포트를 두 번 만드는 일이 없게, 이미 요청한 훈련 id를 기억한다.
  const requestedId = useRef(null)
  const trainingId = training?.id

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setReport(await api.trainingReport(trainingId))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [trainingId])

  useEffect(() => {
    if (trainingId == null || requestedId.current === trainingId) return
    requestedId.current = trainingId
    load()
  }, [trainingId, load])

  if (!training) {
    return (
      <div className="container report-page">
        <Card title="진행한 훈련이 없습니다" description="훈련 모드에서 레벨을 골라 먼저 진행해 주세요.">
          <Button onClick={() => navigate('training')}>훈련 시작하기</Button>
        </Card>
      </div>
    )
  }

  return (
    <div className="container report-page">
      <button type="button" className="back-link" onClick={() => navigate('training')}>
        ← 훈련 모드로 돌아가기
      </button>
      <header>
        <p className="eyebrow">TRAINING REPORT</p>
        <h1 className="page-title">훈련 결과</h1>
        <p className="page-desc">대화 원문은 저장하지 않고, 어떤 정보를 어떻게 다뤘는지만 기록해 분석합니다.</p>
      </header>

      {loading && (
        <Card tone="muted">
          <p className="report-loading" aria-live="polite">
            <span className="spinner" aria-hidden="true" /> 리포트를 만드는 중입니다… AI가 대화 기록을 분석하고 있어요.
          </p>
        </Card>
      )}

      {error && (
        <div className="stack stack--tight">
          <p className="alert alert--error" role="alert">
            {error}
          </p>
          <div className="row">
            <Button variant="secondary" onClick={load}>
              다시 시도
            </Button>
          </div>
        </div>
      )}

      {report && (
        <>
          <Card title="대응 점수" description={`Level ${report.level} · ${report.turns?.length ?? 0}번 주고받음`}>
            <p className="report-score">
              <b>{report.final_score}</b>
              <span>점</span>
            </p>
          </Card>
          <Card title="AI 대응 분석">
            <p className="report-text">{report.report}</p>
          </Card>
        </>
      )}

      <div className="cta-card">
        <div>
          <b>이제 내 문서도 검사해 보세요.</b>
          <p>보내기 전에 문서 속 개인정보와 숨은 명령을 DocX-ray가 찾아 드립니다.</p>
        </div>
        <div className="report-page__actions">
          <Button onClick={() => navigate('')}>스캐너로 내 문서 검사하기 →</Button>
          <Button variant="secondary" onClick={() => navigate('training')}>
            다시 훈련하기
          </Button>
        </div>
      </div>
    </div>
  )
}
