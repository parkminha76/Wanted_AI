import { useEffect, useState } from 'react'

// 코드 줄이 한 글자씩 입력되는 효과 + 깜빡이는 커서. 장식용이라 부모에서 aria-hidden으로 감싼다.
//   lines: [{ fn: 'scan', arg: '("업무협약서.pdf")' }] — fn은 강조색, arg는 흐린 글자로 그린다.
// 움직임 줄이기 설정이면 처음부터 전부 보여주고 커서만 멈춰 있다.
export default function TypeLines({ lines, startDelayMs = 400, charMs = 34, className = '' }) {
  const texts = lines.map((line) => `${line.fn}${line.arg}`)
  const total = texts.reduce((sum, text) => sum + text.length, 0)
  const [typed, setTyped] = useState(0)

  useEffect(() => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      setTyped(total)
      return undefined
    }
    setTyped(0)
    let timer = 0
    const begin = setTimeout(() => {
      timer = setInterval(() => {
        setTyped((count) => {
          if (count + 1 >= total) clearInterval(timer)
          return Math.min(total, count + 1)
        })
      }, charMs)
    }, startDelayMs)
    return () => {
      clearTimeout(begin)
      clearInterval(timer)
    }
  }, [total, startDelayMs, charMs])

  // 지금 입력 중인 줄(다 끝났으면 마지막 줄)에 커서를 둔다.
  let remaining = typed
  let cursorLine = lines.length - 1
  const visible = texts.map((text, index) => {
    const count = Math.max(0, Math.min(text.length, remaining))
    if (remaining < text.length && cursorLine === lines.length - 1 && typed < total) cursorLine = index
    remaining -= text.length
    return text.slice(0, count)
  })

  return (
    <div className={`term ${className}`.trim()}>
      {lines.map((line, index) => {
        const shown = visible[index]
        return (
          <p key={`${line.fn}-${index}`} className="term__line">
            <span className="term__fn">{shown.slice(0, line.fn.length)}</span>
            <span>{shown.slice(line.fn.length)}</span>
            {index === cursorLine && <span className="term__cursor" />}
          </p>
        )
      })}
    </div>
  )
}
