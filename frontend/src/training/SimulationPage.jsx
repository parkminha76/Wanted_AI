import { useEffect, useRef, useState } from 'react'
import { api } from '../shared/api.js'
import { Button, Card } from '../shared/components/index.js'
import './training.css'

// 서버 상태 머신(backend/training/state_machine.py)의 단계. 대화가 몇 번 오갈지는 정해져 있지 않아서
// 진행 막대는 답장 횟수가 아니라 이 단계로 채운다.
const STAGES = {
  S1_APPROACH: { step: 1, label: '접근' },
  S2_INFO_REQUEST: { step: 2, label: '정보 요구' },
  S3_URGENCY_PRESSURE: { step: 3, label: '긴급 압박' },
  END: { step: 4, label: '종료' },
}

const QUICK_REPLIES = ['어느 부서 누구신지 먼저 확인할게요.', '공식 연락처로 직접 확인한 뒤 답드리겠습니다.', '이 요청에는 응할 수 없습니다.']

// Attacker AI 대화. 답장을 보내기 전에 스캐너(/scan/text)로 먼저 검사하고, 개인정보가 있으면 경고를 띄운다.
//
// 서버의 /training/{id}/reply도 같은 스캐너로 답장을 다시 검사해 기록하지만, 그 결과는 이미 보낸 뒤에
// 오므로 사용자가 고칠 기회가 없다. 그래서 경고는 보내기 전 검사로 띄우고, reply 응답에서는
// 다음 단계(state)·대화 종료 여부만 쓴다.
export default function SimulationPage({ training, navigate }) {
  const [thread, setThread] = useState(() =>
    training?.firstMessage ? [{ id: 1, role: 'attacker', text: training.firstMessage }] : [],
  )
  const [stage, setStage] = useState(training?.state ?? 'S1_APPROACH')
  const [turnNo, setTurnNo] = useState(training?.turnNo ?? 1)
  const [draft, setDraft] = useState('')
  const [warning, setWarning] = useState(null) // { text, result }
  const [status, setStatus] = useState('idle') // idle | checking | sending
  const [error, setError] = useState('')
  const [finished, setFinished] = useState(false)
  const nextId = useRef(2)
  const threadRef = useRef(null)

  // 새 메시지가 오면 대화 상자 안에서만 맨 아래로 내린다(페이지 전체는 움직이지 않게).
  useEffect(() => {
    const box = threadRef.current
    if (box) box.scrollTop = box.scrollHeight
  }, [thread, status])

  if (!training) {
    return (
      <div className="container simulation-page">
        <Card title="진행 중인 훈련이 없습니다" description="훈련 모드에서 레벨을 골라 시작해 주세요.">
          <Button onClick={() => navigate('training')}>레벨 고르러 가기</Button>
        </Card>
      </div>
    )
  }

  const busy = status !== 'idle'
  const current = STAGES[stage] ?? STAGES.S1_APPROACH
  const progress = finished ? 100 : (current.step / 4) * 100

  async function handleSubmit(event) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || busy || finished) return

    setError('')
    setStatus('checking')
    try {
      const checked = await api.scanText(text)
      if (checked.findings.length > 0) {
        setWarning({ text, result: checked })
        setStatus('idle')
        return
      }
    } catch (err) {
      setError(err.message)
      setStatus('idle')
      return
    }
    await send(text, false)
  }

  async function send(text, flagged) {
    setWarning(null)
    setError('')
    setStatus('sending')

    // 내 답장은 바로 보여주고, 실패하면 되돌린 뒤 입력칸에 글을 돌려준다.
    const id = nextId.current++
    setThread((prev) => [...prev, { id, role: 'user', text, flagged }])
    setDraft('')

    try {
      const response = await api.replyTraining(training.id, text)
      const done = Boolean(response.scan_result?.is_finished) || response.state === 'END'
      setStage(response.state)
      setTurnNo(response.turn_no)
      if (!done && response.attacker_message) {
        setThread((prev) => [...prev, { id: nextId.current++, role: 'attacker', text: response.attacker_message }])
      }
      setFinished(done)
    } catch (err) {
      setThread((prev) => prev.filter((message) => message.id !== id))
      setDraft(text)
      setError(err.message)
    } finally {
      setStatus('idle')
    }
  }

  const warningLabels = warning ? [...new Set(warning.result.findings.map((finding) => finding.label))].join(', ') : ''

  return (
    <div className="container simulation-page">
      <button type="button" className="back-link" onClick={() => navigate('training')}>
        ← 훈련 모드로 돌아가기
      </button>

      <div className="sim-head">
        <div>
          <p className="eyebrow">SECURITY TRAINING</p>
          <h1 className="page-title">보안 대응 훈련</h1>
          <p className="page-desc">상대는 AI가 연기하는 사기범입니다. 실제 개인정보는 입력하지 마세요.</p>
        </div>
        <div className="sim-progress">
          <p>
            <b>Level {training.level}</b> / 5
          </p>
          <p>
            <b>{finished ? '종료' : current.label}</b> · {turnNo}번째 답장
          </p>
          <div
            className="sim-progress__bar"
            role="progressbar"
            aria-label="훈련 단계"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress)}
          >
            <i style={{ width: `${progress}%` }} />
          </div>
        </div>
      </div>

      <div className="sim-layout">
        <aside className="scenario-note">
          <span className="scenario-note__icon" aria-hidden="true">
            ▣
          </span>
          <b>상황 안내</b>
          <p>
            발신자와 요청의 맥락을 먼저 확인하세요. 계좌·비밀번호·인증번호를 요구하면 멈추고 공식 채널로 확인하는 것이 가장
            안전합니다.
          </p>
          <hr />
          <small>현재 훈련</small>
          <strong>
            Level {training.level} · {finished ? '종료' : current.label}
          </strong>
        </aside>

        <section className="message-panel" aria-label="대화">
          <div className="mailbar">
            <span aria-hidden="true">✉</span>
            <b>업무 메시지</b>
            <small>보낸 사람: 확인되지 않은 발신자</small>
          </div>

          <ol ref={threadRef} className="thread" aria-live="polite">
            {thread.map((message) => (
              <li key={message.id} className={`thread__item thread__item--${message.role}`}>
                <span className="thread__sender">{message.role === 'attacker' ? '상대' : '나'}</span>
                <p className="thread__text">{message.text}</p>
                {message.flagged && <span className="thread__flag">⚠ 개인정보가 포함된 채로 보냄</span>}
              </li>
            ))}
            {status === 'sending' && (
              <li className="thread__item thread__item--typing">
                <span className="spinner" aria-hidden="true" /> 상대가 답장을 쓰는 중…
              </li>
            )}
          </ol>

          {error && (
            <p className="alert alert--error thread__error" role="alert">
              {error}
            </p>
          )}

          {finished ? (
            <div className="sim-complete">
              <span className="sim-complete__icon" aria-hidden="true">
                ✓
              </span>
              <h2 className="sim-complete__title">대화가 끝났습니다.</h2>
              <p>어떻게 대응했는지 AI가 분석한 리포트를 확인해 보세요.</p>
              <Button size="lg" onClick={() => navigate('training/report')}>
                결과 리포트 보기
              </Button>
            </div>
          ) : (
            <form className="response" onSubmit={handleSubmit}>
              <p id="response-prompt" className="response__prompt">
                이 상황에서 어떻게 답장하시겠습니까?
              </p>
              <div className="response__quick">
                {QUICK_REPLIES.map((reply) => (
                  <Button
                    key={reply}
                    variant="secondary"
                    size="sm"
                    disabled={busy}
                    onClick={() => {
                      setDraft(reply)
                      setWarning(null)
                    }}
                  >
                    {reply}
                  </Button>
                ))}
              </div>

              {warning && (
                <div className="reply-warning" role="alert">
                  <p className="reply-warning__title">보내기 전에 확인하세요</p>
                  <p className="text-sm">답장에 개인정보가 들어 있습니다: {warningLabels}</p>
                  <p className="reply-warning__preview">{warning.result.masked_text}</p>
                  <div className="response__actions response__actions--end">
                    <Button variant="secondary" onClick={() => setWarning(null)}>
                      다시 쓰기
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setDraft(warning.result.masked_text)
                        setWarning(null)
                      }}
                    >
                      가린 문장으로 바꾸기
                    </Button>
                    <Button variant="danger" onClick={() => send(warning.text, true)}>
                      그대로 보내기
                    </Button>
                  </div>
                </div>
              )}

              <label htmlFor="reply-input" className="visually-hidden">
                답장 입력
              </label>
              <textarea
                id="reply-input"
                className="response__input"
                aria-describedby="response-prompt"
                value={draft}
                onChange={(event) => {
                  setDraft(event.target.value)
                  setWarning(null)
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) handleSubmit(event)
                }}
                placeholder="답장을 입력하세요"
                maxLength={10000}
                disabled={busy}
              />
              <div className="response__actions">
                <span className="text-muted text-sm">
                  {status === 'checking' ? '개인정보가 있는지 검사하는 중…' : 'Ctrl+Enter로 보내기'}
                </span>
                <Button type="submit" disabled={busy || !draft.trim()}>
                  보내기
                </Button>
              </div>
            </form>
          )}
        </section>
      </div>
    </div>
  )
}
