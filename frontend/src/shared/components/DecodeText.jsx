import { useEffect, useRef, useState } from 'react'

const DIGITS = '0123456789'
const DURATION_MS = 700

// 숫자 해독 효과. 화면에 들어오면 숫자 자리가 무작위 숫자로 뒤섞였다가 앞에서부터 제자리 값으로 풀린다.
// 숫자가 아닌 글자("건", "%")는 그대로 둔다. 움직임 줄이기 설정이면 처음부터 최종 값만 보여준다.
//
// 화면 읽기 프로그램에는 뒤섞이는 글자 대신 최종 값만 읽히게 한다(visually-hidden 사본 + aria-hidden 표시용).
export default function DecodeText({ text, className = '' }) {
  const value = String(text ?? '')
  const ref = useRef(null)
  const [shown, setShown] = useState(value)

  useEffect(() => {
    setShown(value)
    const element = ref.current
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (!element || reduce || !('IntersectionObserver' in window) || !/\d/.test(value) || value.length > 16) {
      return undefined
    }

    const chars = Array.from(value)
    let frame = 0
    let settle = 0

    function run() {
      // 탭이 뒤로 가 있거나 브라우저가 화면 갱신을 늦추면 중간값에 멈출 수 있어서, 시간이 지나면 최종 값으로 맞춘다.
      settle = setTimeout(() => {
        cancelAnimationFrame(frame)
        setShown(value)
      }, DURATION_MS + 150)
      const start = performance.now()
      const tick = (now) => {
        const progress = Math.min(1, (now - start) / DURATION_MS)
        const settled = Math.floor(progress * chars.length)
        setShown(
          chars
            .map((char, index) =>
              index < settled || !/\d/.test(char) ? char : DIGITS[Math.floor(Math.random() * DIGITS.length)],
            )
            .join(''),
        )
        if (progress < 1) frame = requestAnimationFrame(tick)
        else setShown(value)
      }
      frame = requestAnimationFrame(tick)
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          observer.disconnect()
          run()
        }
      },
      { threshold: 0.4 },
    )
    observer.observe(element)

    return () => {
      observer.disconnect()
      cancelAnimationFrame(frame)
      clearTimeout(settle)
    }
  }, [value])

  return (
    <span ref={ref} className={`decode ${className}`.trim()}>
      <span className="visually-hidden">{value}</span>
      <span aria-hidden="true">{shown}</span>
    </span>
  )
}
