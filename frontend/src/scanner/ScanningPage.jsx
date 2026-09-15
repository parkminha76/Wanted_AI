import { useEffect, useState } from 'react'
import { Button, Card } from '../shared/components/index.js'
import './scanner.css'

// 서버는 진행률을 알려주지 않는다. 가짜 퍼센트 대신 지난 시간과 검사 순서만 보여준다.
const STEPS = ['파일 읽기 · 숨은 서식 확인', '개인정보 · 민감정보 탐지', '숨은 AI 명령 판정', '오탐 제거 · 위험도 계산', '마스킹 사본 만들기']

export default function ScanningPage({ job, navigate }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!job) return undefined
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [job])

  if (!job) {
    return (
      <div className="container scanning-page">
        <Card title="진행 중인 검사가 없습니다" description="문서를 올려 검사를 시작해 주세요.">
          <Button onClick={() => navigate('')}>문서 올리러 가기</Button>
        </Card>
      </div>
    )
  }

  const elapsed = Math.max(0, Math.round((now - job.startedAt) / 1000))
  const target = job.kind === 'samples' ? '샘플 문서를' : `파일 ${job.fileCount}개를`

  return (
    <div className="container scanning-page">
      <header>
        <h1 className="page-title">문서를 검사하고 있습니다.</h1>
        <p className="page-desc">AI가 {target} 분석하는 중입니다.</p>
      </header>

      <div className="progress-ring" role="status" aria-live="polite">
        <div className="progress-ring__inner">
          <b>{elapsed}초</b>
          <small>분석 중…</small>
        </div>
      </div>

      <ol className="scan-steps" aria-label="검사 순서">
        {STEPS.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>

      <div className="wait-card">
        <span className="wait-card__icon" aria-hidden="true">
          ✦
        </span>
        <div>
          <b>잠시만 기다려 주세요!</b>
          <p>
            첫 검사는 AI 모델을 불러오느라 30초~1분 정도 걸릴 수 있습니다. 다른 화면으로 가도 검사는 계속되고, 끝나면 결과
            화면으로 이동합니다.
          </p>
        </div>
      </div>
    </div>
  )
}
