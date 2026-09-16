import { useEffect, useState } from 'react'

// 첫 화면 오른쪽의 스캔 장면. 초록 선이 문서를 훑고 지나가면서 민감정보가 하나씩 가려지고,
// 가려진 항목을 누르면 아래 칸에 탐지 상세가 열린다. "다시 스캔"으로 처음부터 다시 볼 수 있다.
// 값은 모두 지어낸 예시이고, 실제 값은 화면에 아예 그리지 않는다 — 가림 점만 보여준다.
// 움직임 줄이기 설정이면 훑는 연출 없이 다 끝난 장면부터 보여준다.
const FIELDS = [
  {
    id: 'dob',
    mask: '••••••',
    type: '개인식별정보',
    risk: 'high',
    category: '생년월일',
    confidence: 92,
    description:
      '계약 당사자의 생년월일이 그대로 적혀 있습니다. 신분 확인용 정보와 합쳐지면 개인을 특정할 위험이 큽니다.',
    revealMs: 900,
  },
  {
    id: 'account',
    mask: '•••-•••-••••••',
    type: '금융정보',
    risk: 'high',
    category: '계좌번호',
    confidence: 95,
    description:
      '정산 조항에 은행 계좌번호가 원문 그대로 있습니다. 밖으로 보내기 전에 가리거나 따로 전달하는 편이 안전합니다.',
    revealMs: 1550,
  },
  {
    id: 'rrn',
    mask: '••••••-•••••••',
    type: '개인식별정보',
    risk: 'high',
    category: '주민등록번호',
    confidence: 98,
    description:
      '본문 가운데 문단에 주민등록번호 형식이 그대로 들어가 있습니다. 법적 고지 의무가 생길 수 있는 가장 위험한 항목입니다.',
    revealMs: 2150,
  },
]

const SCAN_MS = 2600 // 초록 선이 문서를 다 훑는 데 걸리는 시간(landing.css의 scan-sweep과 맞춘다)

const RISK_LABELS = { high: 'HIGH', medium: 'MED' }

export default function LandingScanMock() {
  const [run, setRun] = useState(0) // "다시 스캔"을 누를 때마다 올려서 아래 효과를 다시 돌린다
  const [revealed, setRevealed] = useState(0) // 몇 번째 항목까지 가려졌는지
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  const [openId, setOpenId] = useState(null)

  useEffect(() => {
    setRevealed(0)
    setDone(false)
    setOpenId(null)

    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setRunning(false)
      setRevealed(FIELDS.length)
      setDone(true)
      return undefined
    }

    // 리셋과 같은 프레임에 켜면 애니메이션이 처음부터 돌지 않는다. 한 프레임 뒤에 시작한다.
    setRunning(false)
    const frame = requestAnimationFrame(() => setRunning(true))
    const timers = FIELDS.map((field, index) =>
      setTimeout(() => setRevealed(index + 1), field.revealMs),
    )
    timers.push(setTimeout(() => setDone(true), SCAN_MS))

    return () => {
      cancelAnimationFrame(frame)
      timers.forEach(clearTimeout)
    }
  }, [run])

  const open = FIELDS.find((field) => field.id === openId)

  // 가려진 항목만 누를 수 있다. 훑는 중에 아직 안 지나간 자리는 눌러도 반응하지 않는다.
  function maskedField(index) {
    const field = FIELDS[index]
    const isRevealed = index < revealed
    return (
      <button
        type="button"
        className={`scan-mock__mask${isRevealed ? ' is-revealed' : ''}${
          openId === field.id ? ' is-open' : ''
        }`}
        disabled={!isRevealed}
        aria-label={`${field.category} 탐지 항목 자세히 보기`}
        onClick={() => setOpenId(field.id)}
      >
        <span aria-hidden="true">{field.mask}</span>
      </button>
    )
  }

  return (
    // className은 고정해 둔다 — 상태를 클래스로 넣으면 리렌더 때 className을 다시 써서
    // useScrollReveal이 직접 붙여 둔 .in이 지워지고, .motion .rv가 opacity:0으로 되돌려 장면이 사라진다.
    <div className="scan-mock rv" data-running={running ? '' : undefined} data-done={done ? '' : undefined}>
      <div className="scan-mock__glow" aria-hidden="true" />

      <div className="scan-mock__frame">
        <div className="scan-mock__head">
          <span className="scan-mock__file">계약서_최종_v3.docx</span>
          <span className="scan-mock__status" aria-live="polite">
            <i className="scan-mock__dot" aria-hidden="true" />
            {done ? 'SCAN COMPLETE' : 'SCANNING…'}
          </span>
        </div>

        {/* 문서 미리보기. 글줄은 내용이 아니라 자리 표시용 막대라서 화면 읽기 프로그램에는 감춘다. */}
        <div className="scan-mock__doc">
          <i className="scan-mock__corner scan-mock__corner--tl" aria-hidden="true" />
          <i className="scan-mock__corner scan-mock__corner--tr" aria-hidden="true" />
          <i className="scan-mock__corner scan-mock__corner--bl" aria-hidden="true" />
          <i className="scan-mock__corner scan-mock__corner--br" aria-hidden="true" />
          <i className="scan-mock__scanline" aria-hidden="true" />

          <i className="scan-mock__bar scan-mock__bar--62" aria-hidden="true" />
          <i className="scan-mock__bar scan-mock__bar--88" aria-hidden="true" />

          <p className="scan-mock__row">
            <span className="scan-mock__label">김민준 /</span>
            {maskedField(0)}
          </p>

          <i className="scan-mock__bar scan-mock__bar--76" aria-hidden="true" />

          <p className="scan-mock__row">
            <span className="scan-mock__label">계좌</span>
            {maskedField(1)}
          </p>

          <i className="scan-mock__bar scan-mock__bar--58" aria-hidden="true" />

          <p className="scan-mock__row scan-mock__row--inline">
            <i className="scan-mock__bar scan-mock__bar--30" aria-hidden="true" />
            {maskedField(2)}
            <i className="scan-mock__bar scan-mock__bar--30" aria-hidden="true" />
          </p>

          <i className="scan-mock__bar scan-mock__bar--82" aria-hidden="true" />
          <i className="scan-mock__bar scan-mock__bar--45" aria-hidden="true" />
        </div>

        {/* 누른 항목의 상세. 아무것도 안 눌렀을 때도 칸 높이를 잡아 둬서 열고 닫을 때 안 흔들린다. */}
        <div className="scan-mock__dock">
          {open ? (
            <div className="scan-mock__finding">
              <div className="scan-mock__finding-body">
                <p className="scan-mock__finding-head">
                  <span className="scan-mock__tag">{open.type}</span>
                  <span className={`scan-mock__tag scan-mock__tag--${open.risk}`}>
                    {RISK_LABELS[open.risk]}
                  </span>
                  <b className="scan-mock__finding-cat">{open.category}</b>
                </p>
                <p className="scan-mock__finding-desc">{open.description}</p>
                <p className="scan-mock__finding-meta">
                  확신도 {open.confidence}%
                  <span className="scan-mock__conf" aria-hidden="true">
                    <i style={{ width: `${open.confidence}%` }} />
                  </span>
                </p>
              </div>
              <button
                type="button"
                className="scan-mock__finding-close"
                aria-label="탐지 상세 닫기"
                onClick={() => setOpenId(null)}
              >
                <span aria-hidden="true">✕</span>
              </button>
            </div>
          ) : (
            <p className="scan-mock__dock-empty">가려진 항목을 누르면 탐지 내용이 여기에 나옵니다</p>
          )}
        </div>

        <div className="scan-mock__foot">
          <span className="scan-mock__progress" aria-hidden="true">
            <i />
          </span>
          <span className="scan-mock__count">{revealed} FINDINGS</span>
          <span className="scan-mock__risk">RISK HIGH</span>
        </div>
      </div>

      <button
        type="button"
        className="scan-mock__replay"
        disabled={!done}
        onClick={() => setRun((value) => value + 1)}
      >
        다시 스캔
      </button>
    </div>
  )
}
