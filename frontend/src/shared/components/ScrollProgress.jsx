import { useEffect, useRef } from 'react'

// 헤더 아래 읽기 진행 막대. 스크롤한 만큼 형광초록 막대가 찬다(장식이라 aria-hidden).
// 화면이 바뀌면 페이지 길이가 달라지므로 부모가 key로 다시 만든다(AppHeader).
export default function ScrollProgress() {
  const barRef = useRef(null)

  useEffect(() => {
    let ticking = false
    const update = () => {
      ticking = false
      const max = document.documentElement.scrollHeight - window.innerHeight
      const progress = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0
      if (barRef.current) barRef.current.style.transform = `scaleX(${progress})`
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

  return (
    <div className="scroll-progress" aria-hidden="true">
      <span ref={barRef} className="scroll-progress__bar" />
    </div>
  )
}
