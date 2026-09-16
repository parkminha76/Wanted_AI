import { Fragment, useEffect, useRef, useState } from 'react'

// 훈련 소개 화면 오른쪽의 맛보기 대화.
//   1) 아무것도 안 하면 사기범 메시지가 한 글자씩 입력되는 시연이 반복된다.
//   2) 아래 입력칸에 직접 답장하면 시연이 멈추고, 미리 써 둔 사기범 후속 멘트가 차례로 온다.
//   3) 후속 멘트가 떨어지면 맛보기를 닫고 아래 레벨 선택으로 안내한다.
// 사기범 문구는 전부 지어낸 예시다. 실제 AI를 부르지 않으므로 키 없이도 돌아가고(발표 데모용),
// 사용자가 친 글은 메모리에만 두고 어디에도 보내지 않는다.
// 움직임 줄이기 설정이면 시연 없이 처음부터 다 쳐진 모습만 보여준다(training.css).
const INTRO = [
  '[긴급] 계정 보안 확인이 필요합니다.\n24시간 내 인증하지 않으면 계정이 잠깁니다.',
  '아래 링크에서 본인 확인을 진행해 주세요 →',
]

// 답장 한 번에 하나씩 온다. 정보를 조금씩 더 요구하도록 순서를 잡았다.
const FOLLOW_UPS = [
  '본인 확인이 안 되면 도와드릴 수 없습니다.\n성함과 생년월일만 알려 주세요.',
  '방금 문자로 간 인증번호 6자리만 불러 주시면\n제가 대신 처리해 드리겠습니다.',
]

const CLOSING = '맛보기는 여기까지입니다. 아래에서 레벨을 고르면 실제 훈련이 시작됩니다.'

const CHAR_MS = 32 // 한 글자
const START_MS = 500 // 화면에 뜨고 첫 글자까지
const BETWEEN_MS = 700 // 시연에서 메시지와 메시지 사이
const RESTART_MS = 2800 // 시연을 다 돌고 처음으로 돌아가기까지
const ANSWER_MS = 900 // 내 답장 뒤 사기범이 다시 말을 걸기까지
const MAX_LENGTH = 120 // 말풍선이 칸을 넘기지 않을 정도로만 받는다

const INTRO_TOTAL = INTRO.reduce((sum, text) => sum + text.length, 0)
// 시연에서 메시지가 끝나는 지점(마지막은 뺀다). 여기서 한 박자 쉰다.
const BREAKS = INTRO.slice(0, -1).map((_, index) =>
  INTRO.slice(0, index + 1).reduce((sum, text) => sum + text.length, 0),
)

function prefersReducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

export default function TypingChatMock() {
  const [introTyped, setIntroTyped] = useState(0)
  const [replies, setReplies] = useState([])
  // 지금 도착 중인 후속 멘트(= 마지막 답장에 대한 것)를 몇 글자까지 쳤는지
  const [botTyped, setBotTyped] = useState(0)
  const [draft, setDraft] = useState('')
  const feedRef = useRef(null)

  const taken = replies.length > 0
  const pending = FOLLOW_UPS[replies.length - 1] // 마지막 답장에 붙을 후속 멘트(없으면 undefined)

  // 시연: 답장을 시작하기 전까지만 돈다. 답장을 시작하면 사기범 메시지를 전부 드러낸다.
  useEffect(() => {
    if (prefersReducedMotion() || taken) {
      setIntroTyped(INTRO_TOTAL)
      return undefined
    }

    let timer = 0
    let count = 0
    const tick = () => {
      count = count >= INTRO_TOTAL ? 0 : count + 1
      setIntroTyped(count)
      const delay =
        count >= INTRO_TOTAL ? RESTART_MS : BREAKS.includes(count) ? BETWEEN_MS : CHAR_MS
      timer = setTimeout(tick, delay)
    }
    timer = setTimeout(tick, START_MS)
    return () => clearTimeout(timer)
  }, [taken])

  // 후속 멘트: 답장을 보내면 한 박자 뒤에 한 글자씩 도착한다.
  useEffect(() => {
    if (!pending) return undefined
    if (prefersReducedMotion()) {
      setBotTyped(pending.length)
      return undefined
    }

    setBotTyped(0)
    let timer = 0
    let count = 0
    const tick = () => {
      count += 1
      setBotTyped(count)
      if (count < pending.length) timer = setTimeout(tick, CHAR_MS)
    }
    timer = setTimeout(tick, ANSWER_MS)
    return () => clearTimeout(timer)
  }, [pending])

  // 새 말풍선이 붙으면 마지막이 보이도록 대화를 아래로 내린다.
  useEffect(() => {
    if (taken) feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight })
  }, [taken, replies.length, botTyped])

  const arriving = Boolean(pending) && botTyped < pending.length
  const done = taken && !pending // 후속 멘트를 다 쓴 뒤

  function send(event) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || arriving || done) return
    setReplies((list) => [...list, text])
    setDraft('')
  }

  // 시연 중에는 사기범 메시지를 잘라서 보여준다. 답장을 시작하면 전문을 보여준다.
  let remaining = introTyped
  const introShown = INTRO.map((text) => {
    const count = Math.max(0, Math.min(text.length, remaining))
    remaining -= text.length
    return count
  })
  // 커서는 지금 치고 있는 시연 말풍선에 둔다. 답장을 시작했으면 시연 커서는 없앤다.
  const introCursor = taken ? -1 : introShown.findIndex((count, index) => count < INTRO[index].length)

  return (
    <div className="chat-mock">
      {/* 시연이 도는 동안에는 글자가 잘린 채로 바뀌므로 화면 읽기 프로그램에 읽히지 않게 둔다.
          사용자가 답장을 시작하면 문장이 온전해지므로 그때 드러낸다. */}
      <div ref={feedRef} className="chat-mock__feed" aria-hidden={taken ? undefined : 'true'}>
        {INTRO.map((text, index) =>
          introShown[index] > 0 ? (
            <div key={text} className="chat-mock__bubble">
              <p className="chat-mock__sender">알 수 없는 발신자</p>
              <p className="chat-mock__msg">
                {text.slice(0, introShown[index])}
                {index === introCursor && <span className="chat-mock__cursor" />}
              </p>
            </div>
          ) : null,
        )}

        {replies.map((text, index) => {
          const follow = FOLLOW_UPS[index]
          const last = index === replies.length - 1
          const typedCount = last ? botTyped : follow?.length ?? 0
          return (
            <Fragment key={`${index}-${text}`}>
              <div className="chat-mock__bubble chat-mock__bubble--mine">
                <p className="chat-mock__msg">{text}</p>
              </div>
              {follow && typedCount > 0 && (
                <div className="chat-mock__bubble">
                  <p className="chat-mock__sender">알 수 없는 발신자</p>
                  <p className="chat-mock__msg">
                    {follow.slice(0, typedCount)}
                    {last && typedCount < follow.length && <span className="chat-mock__cursor" />}
                  </p>
                </div>
              )}
            </Fragment>
          )
        })}

        {done && <p className="chat-mock__note">{CLOSING}</p>}
      </div>

      <form className="chat-mock__input" onSubmit={send}>
        <label htmlFor="chat-mock-draft" className="visually-hidden">
          사기범에게 답장 써보기
        </label>
        <input
          id="chat-mock-draft"
          className="chat-mock__field"
          type="text"
          value={draft}
          maxLength={MAX_LENGTH}
          placeholder={done ? '맛보기가 끝났습니다' : '메시지 입력'}
          autoComplete="off"
          disabled={done}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          type="submit"
          className="chat-mock__send"
          disabled={!draft.trim() || arriving || done}
          aria-label="보내기"
        >
          <span aria-hidden="true">↑</span>
        </button>
      </form>
    </div>
  )
}
