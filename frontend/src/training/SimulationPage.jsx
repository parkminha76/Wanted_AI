import { useEffect, useRef, useState } from 'react'
import { api } from '../shared/api.js'
import { Button, Card } from '../shared/components/index.js'
import './training.css'

const LEVEL_INFO = {
  1: {
    title: '일상형 사기',
    description: '일상에서 받을 법한 연락에 직접 대응해 보세요.',
  },
  2: {
    title: '사내 IT팀 사칭',
    description: '업무 중 받은 것처럼 보이는 요청에 직접 대응해 보세요.',
  },
  3: {
    title: '거래처 사칭',
    description: '거래처에서 온 것처럼 보이는 업무 요청에 대응해 보세요.',
  },
  4: {
    title: '임원 사칭',
    description: '상급자의 긴급한 업무 요청처럼 보이는 상황에 대응해 보세요.',
  },
  5: {
    title: 'AI·문서 공격',
    description: 'AI와 업무 문서를 이용한 공격 상황에 대응해 보세요.',
  },
}

const PRIVATE_FIELD_LABELS = {
  PHONE: '휴대전화 번호',
  EMAIL: '이메일 주소',
  ACCOUNT: '계좌번호',
  CARD: '카드 번호',
  RRN: '주민등록번호',
}

function displayAttackerMessage(text) {
  return text.replace(
    /\[(PHONE|EMAIL|ACCOUNT|CARD|RRN)\]/g,
    (_, field) => PRIVATE_FIELD_LABELS[field],
  )
}

export default function SimulationPage({ training, navigate }) {
  const [thread, setThread] = useState(() =>
    training?.firstMessage
      ? [{ id: 1, role: 'attacker', text: training.firstMessage }]
      : [],
  )

  const [turnNo, setTurnNo] = useState(training?.turnNo ?? 1)
  const [draft, setDraft] = useState('')
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')
  const [finished, setFinished] = useState(false)
  const [evaluationStatus, setEvaluationStatus] = useState(null)

  const nextId = useRef(2)
  const threadRef = useRef(null)

  useEffect(() => {
    const box = threadRef.current

    if (box) {
      box.scrollTop = box.scrollHeight
    }
  }, [thread, status])

  if (!training) {
    return (
      <div className="container simulation-page">
        <Card
          title="진행 중인 훈련이 없습니다"
          description="훈련 모드에서 상황을 선택해 시작해 주세요."
        >
          <Button onClick={() => navigate('training')}>
            상황 고르러 가기
          </Button>
        </Card>
      </div>
    )
  }

  const busy = status !== 'idle'
  const levelInfo = LEVEL_INFO[training.level] ?? LEVEL_INFO[1]

  const progress = finished
    ? 100
    : Math.min((turnNo / 5) * 100, 95)

  async function handleSubmit(event) {
    event.preventDefault()

    const text = draft.trim()

    if (!text || busy || finished) return

    setError('')
    await send(text)
  }

  async function send(text) {
    setError('')
    setStatus('sending')

    const id = nextId.current++

    setThread((prev) => [
      ...prev,
      {
        id,
        role: 'user',
        text,
      },
    ])

    setDraft('')

    try {
      const response = await api.replyTraining(
        training.id,
        text,
      )

      const done = Boolean(response.is_finished)

      setTurnNo(response.turn_no)
      setEvaluationStatus(response.evaluation_status ?? null)

      if (!done && response.attacker_message) {
        setThread((prev) => [
          ...prev,
          {
            id: nextId.current++,
            role: 'attacker',
            text: response.attacker_message,
          },
        ])
      }

      setFinished(done)
    } catch (err) {
      setThread((prev) =>
        prev.filter((message) => message.id !== id),
      )

      setDraft(text)
      setError(err.message)
    } finally {
      setStatus('idle')
    }
  }

  return (
    <div className="container simulation-page">
      <button
        type="button"
        className="back-link"
        onClick={() => navigate('training')}
      >
        ← 훈련 모드로 돌아가기
      </button>

      <div className="sim-head rv">
        <div>
          <p className="eyebrow">AI SECURITY TRAINING</p>

          <h1 className="page-title">
            Case {training.level} · {levelInfo.title}
          </h1>

          <p className="page-desc">
            {levelInfo.description}
          </p>

          {training.scenarioTitle && (
            <p className="scenario-chip">
              <span>이번 시나리오</span>
              <b>{training.scenarioTitle}</b>
            </p>
          )}
        </div>

        <div className="sim-progress">
          <p>
            <b>Case {training.level}</b> / 5
          </p>

          <p>
            <b>{finished ? '훈련 종료' : '진행 중'}</b>
            {' · '}
            {turnNo}번째 대화
          </p>

          <div
            className="sim-progress__bar"
            role="progressbar"
            aria-label="훈련 진행도"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress)}
          >
            <i style={{ width: `${progress}%` }} />
          </div>
        </div>
      </div>

      <div className="sim-chat-layout">
        <section
          className="message-panel message-panel--chat"
          aria-label="AI 사기 대응 훈련"
        >
          <div className="mailbar">
            <div className="mailbar__intro">
              <b>메시지</b>
              <small>
                실제 상황이라고 생각하고 직접 대응해 보세요.
              </small>
            </div>

            <span className="training-live">
              <i />
              TRAINING
            </span>
          </div>

          <ol
            ref={threadRef}
            className="thread thread--chat"
            aria-live="polite"
          >
            {thread.map((message) => (
              <li
                key={message.id}
                className={`thread__item thread__item--${message.role}`}
              >
                <span className="thread__sender">
                  {message.role === 'attacker'
                    ? '상대방'
                    : '나'}
                </span>

                <p className="thread__text">
                  {message.role === 'attacker'
                    ? displayAttackerMessage(message.text)
                    : message.text}
                </p>

              </li>
            ))}

            {status === 'sending' && (
              <li className="thread__item thread__item--typing">
                <span
                  className="spinner"
                  aria-hidden="true"
                />

                상대방이 답장을 작성하고 있습니다…
              </li>
            )}
          </ol>

          {error && (
            <p
              className="alert alert--error thread__error"
              role="alert"
            >
              {error}
            </p>
          )}

          {finished ? (
            <div className="sim-complete">
              <span
                className="sim-complete__icon"
                aria-hidden="true"
              >
                ✓
              </span>

              <h2 className="sim-complete__title">
                {evaluationStatus === 'insufficient_responses'
                  ? '훈련을 평가할 수 없습니다.'
                  : '훈련이 종료되었습니다.'}
              </h2>

              <p>
                {evaluationStatus === 'insufficient_responses'
                  ? '의미 있는 답변이 충분하지 않아 점수를 산정하지 않습니다.'
                  : '방금 대화에서 어떤 판단을 했는지 AI 분석 결과를 확인해 보세요.'}
              </p>

              <Button
                size="lg"
                onClick={() =>
                  navigate('training/report')
                }
              >
                대응 분석 보기
              </Button>
            </div>
          ) : (
            <form
              className="response response--chat"
              onSubmit={handleSubmit}
            >
              <div className="response__guide">
                <span aria-hidden="true">●</span>

                <p>
                  <b>직접 답장해 보세요.</b>
                  <small>
                    정답은 표시되지 않습니다. 실제 상황처럼
                    판단해 주세요.
                  </small>
                </p>
              </div>

              <label
                htmlFor="reply-input"
                className="visually-hidden"
              >
                답장 입력
              </label>

              <textarea
                id="reply-input"
                className="response__input response__input--chat"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === 'Enter' &&
                    !event.shiftKey
                  ) {
                    event.preventDefault()
                    handleSubmit(event)
                  }
                }}
                placeholder="상대방에게 직접 답장해 보세요..."
                maxLength={10000}
                disabled={busy}
              />

              <div className="response__actions">
                <span className="text-muted text-sm">
                  Enter 전송 · Shift+Enter 줄바꿈
                </span>

                <Button
                  type="submit"
                  disabled={busy || !draft.trim()}
                >
                  전송
                </Button>
              </div>
            </form>
          )}
        </section>

        <aside className="training-tip">
          <p className="eyebrow">MISSION</p>

          <h3>직접 판단하세요</h3>

          <p>
            이 연락이 정상인지 의심스러운지 화면에서는
            알려주지 않습니다.
          </p>

          <div className="training-tip__rule">
            <span>01</span>
            <p>
              상대방의 말과 요청이 자연스러운지 판단하세요.
            </p>
          </div>

          <div className="training-tip__rule">
            <span>02</span>
            <p>
              실제 상황에서 할 법한 답변을 직접 입력하세요.
            </p>
          </div>

          <div className="training-tip__rule">
            <span>03</span>
            <p>
              훈련이 끝난 뒤 AI가 대응 과정을 분석합니다.
            </p>
          </div>

          <div className="privacy-note">
            <span aria-hidden="true">◆</span>
            <p>
              명확한 개인정보 형식은 외부 AI 전달 전에 자동으로 치환됩니다.
            </p>
          </div>
        </aside>
      </div>
    </div>
  )
}
