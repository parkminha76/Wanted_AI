import { useEffect, useState } from 'react'

// 오른쪽 아래에 떠 있는 "맨 위로" 버튼. 일정 거리 내려가면 나타나고, 누르면 최상단으로 돌아간다.
// 화면이 바뀌면 스크롤 위치도 처음으로 돌아가므로 부모가 key로 다시 만든다(App).
//
// 기준을 고정 px(예: 200px)로 두면, 화면이 짧거나 뷰포트가 큰 조합에서 "내려갈 수 있는 최대 거리"가
// 그 값보다 작아 아무리 내려도 조건을 못 채우는 경우가 생긴다 — 실측: 이용 가이드는 1920×1080 화면에서
// 최대로 내려갈 수 있는 거리가 8px뿐이라 200px는 영원히 못 채운다. 그래서 "내려갈 수 있는 최대 거리"의
// 일정 비율로 기준을 잡는다 — 짧은 화면에서는 기준도 같이 낮아져서 늘 닿을 수 있다.
const SHOW_AFTER_RATIO = 0.3
const SHOW_AFTER_PX_MAX = 200 // 화면이 아주 길 때 기준이 지나치게 늦어지지 않게 위쪽 한도를 둔다

export default function ScrollTopButton() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    let ticking = false
    const update = () => {
      ticking = false
      const maxScroll = document.documentElement.scrollHeight - window.innerHeight
      const threshold = Math.min(SHOW_AFTER_PX_MAX, Math.max(0, maxScroll) * SHOW_AFTER_RATIO)
      setVisible(window.scrollY > threshold)
    }
    const onScroll = () => {
      if (!ticking) {
        ticking = true
        requestAnimationFrame(update)
      }
    }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [])

  function toTop() {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' })
  }

  return (
    <button
      type="button"
      className={`scroll-top${visible ? ' is-visible' : ''}`}
      aria-label="맨 위로"
      title="맨 위로"
      onClick={toTop}
    >
      <span className="scroll-top__arrow" aria-hidden="true" />
    </button>
  )
}
