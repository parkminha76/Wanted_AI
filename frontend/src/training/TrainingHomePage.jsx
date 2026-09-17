import { useEffect, useState } from 'react'
import { FileChartColumn, MessageSquareText, ShieldCheck } from 'lucide-react'
import { api } from '../shared/api.js'
import { Badge, Button, SectionRail } from '../shared/components/index.js'
import TypingChatMock from './TypingChatMock.jsx'
import './training.css'

// TODO: 로그인 기능이 없어 임시 사용자 id를 쓴다. /training/start는 이 id로 DB에 훈련 기록을 만들므로
// backend/db의 사용자 테이블에 이 id가 있어야 한다 — C와 확인 필요.
const DEMO_USER_ID = 1

// TODO: 레벨 설명은 C의 인젝션 학습 데이터 레벨 주제를 옮긴 임시 문구다. 훈련 기획이 확정되면 바꾼다.
const LEVELS = [
  { level: 1, title: '일상형 사기', description: '공공기관·택배·지인을 사칭한 메시지' },
  { level: 2, title: '직장 내부 사칭', description: 'IT팀·인사팀·동료를 사칭한 업무 요청' },
  { level: 3, title: '거래·금전 요구', description: '계좌 변경·긴급 송금을 요구하는 거래처' },
  { level: 4, title: '임원 사칭', description: '대표·임원 이름으로 오는 긴급 지시' },
  { level: 5, title: 'AI 도구·문서 공격', description: '문서와 AI 도구를 이용한 정교한 공격' },
]

const FEATURES = [
  { Icon: MessageSquareText, title: '실전 대화 시뮬레이션', copy: 'AI가 연기하는 사기범의 메시지에 직접 답장하며 대응해 봅니다.' },
  { Icon: ShieldCheck, title: '개인정보 보호', copy: '명확한 개인정보 형식은 외부 AI에 전달하기 전에 자동으로 치환합니다.' },
  { Icon: FileChartColumn, title: 'AI 대응 리포트', copy: '대화가 끝나면 잘한 점과 위험했던 순간을 정리해 드립니다.' },
]

export default function TrainingHomePage({ onStarted }) {
  const [trainingMode, setTrainingMode] = useState(null) // 'on' | 'off' | null(확인 전·확인 실패)
  const [startingLevel, setStartingLevel] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    api
      .health()
      .then((health) => {
        if (!cancelled) setTrainingMode(health.training_mode ?? null)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  async function start(level) {
    setStartingLevel(level)
    setError('')
    try {
      const started = await api.startTraining({ userId: DEMO_USER_ID, level })
      onStarted({
        id: started.training_progress_id,
        level: started.level,
        turnNo: started.turn_no,
        firstMessage: started.attacker_message,
        scenarioId: started.scenario_id,
        scenarioTitle: started.scenario_title,
      })
    } catch (err) {
      setError(err.message)
      setStartingLevel(null)
    }
  }

  const unavailable = trainingMode === 'off'

  return (
    <div className="container training-page">
      <SectionRail
        sections={[
          { id: 'intro', label: '소개 및 기능', highlightIds: ['intro', 'features'] },
          { id: 'training-levels', label: '레벨 테스트' },
        ]}
      />
      <section id="intro" className="training-hero rv">
        <div>
          <Badge>SECURITY READINESS</Badge>
          <h1 className="training-hero__title">
            <em>AI</em> 보안 대응 훈련
          </h1>
          <p className="training-hero__desc">
            일상부터 실제 업무까지 마주할 수 있는 피싱·정보유출 상황을 AI 사기범과의 대화로 직접 경험하며, 실제 상황에 필요한 대응 감각을 길러 보세요.
          </p>
          <Button
            size="lg"
            onClick={() => document.getElementById('training-levels')?.scrollIntoView({ behavior: 'smooth' })}
          >
            훈련 시작하기 →
          </Button>
        </div>
        <TypingChatMock />
      </section>

      <ul id="features" className="feature-cards stagger">
        {FEATURES.map((feature) => (
          <li key={feature.title} className="feature-card rv">
            <span className="feature-card__icon" aria-hidden="true">
              <feature.Icon size={22} strokeWidth={1.8} />
            </span>
            <h2 className="feature-card__title">{feature.title}</h2>
            <p className="feature-card__copy">{feature.copy}</p>
          </li>
        ))}
      </ul>

      <section id="training-levels" className="stack" aria-labelledby="levels-title">
        <h2 id="levels-title" className="section-title">
          레벨을 골라 시작하세요
        </h2>
        {unavailable && (
          <p className="alert alert--info">지금은 훈련 서버가 연결되지 않아 훈련을 시작할 수 없습니다. 문서 검사는 그대로 쓸 수 있어요.</p>
        )}
        {error && (
          <p className="alert alert--error" role="alert">
            {error}
          </p>
        )}
        <div className="level-grid stagger">
          {LEVELS.map((item) => (
            <button
              key={item.level}
              type="button"
              className="level-card rv"
              onClick={() => start(item.level)}
              disabled={startingLevel !== null || unavailable}
            >
              <span className="level-card__level">Level {item.level}</span>
              <span className="level-card__title">{item.title}</span>
              <span className="level-card__desc">{item.description}</span>
              {startingLevel === item.level && (
                <span className="level-card__status">
                  <span className="spinner" aria-hidden="true" /> 시작하는 중…
                </span>
              )}
            </button>
          ))}
        </div>
      </section>

      <blockquote className="quote rv">
        “작은 경각심이
        <br />더 안전한 일상을 만듭니다.”
      </blockquote>
    </div>
  )
}
