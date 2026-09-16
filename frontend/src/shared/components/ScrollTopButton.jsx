import { useEffect, useState } from 'react'

// 오른쪽 아래에 떠 있는 "맨 위로" 버튼. 한 화면 높이만큼 내려가면 나타나고, 누르면 최상단으로 돌아간다.
// 화면이 바뀌면 스크롤 위치도 처음으로 돌아가므로 부모가 key로 다시 만든다(App).
const SHOW_AFTER_SCREENS = 1

export default function ScrollTopButton() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    let ticking = false
    const update = () => {
      ticking = false
      setVisible(window.scrollY > window.innerHeight * SHOW_AFTER_SCREENS)
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
