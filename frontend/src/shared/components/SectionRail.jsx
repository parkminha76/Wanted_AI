import { useEffect, useRef, useState } from 'react'

// 넓은 화면(1440px 이상) 왼쪽에 붙는 구역 목차. 코드 편집기 줄 번호처럼 "01 소개"로 보이고,
// 스크롤 위치에 따라 지금 보고 있는 구역을 강조한다. 좁은 화면에서는 CSS로 숨긴다.
//   sections: [{ id: 'intro', label: '소개' }] — id는 화면 안 요소의 id
//
// 강조 규칙
//   - 기본: 화면 38% 높이 기준선을 지난 마지막 구역.
//   - 맨 아래까지 내렸으면 마지막 구역 — 페이지 끝의 짧은 구역은 기준선까지 올라오지 못한다.
//   - 목차를 누르면 누른 구역을 고정한다. 페이지가 짧아 그 구역까지 스크롤할 수 없어도(첫 화면의 "업로드"·"특징"은
//     둘 다 맨 아래에서 멈춘다) 누른 항목이 강조된 채 남는다. 사용자가 직접 스크롤(휠·터치·키보드)하면 고정을 푼다.
const SETTLE_MS = 150

export default function SectionRail({ sections }) {
  const ids = sections.map((section) => section.id).join('|')
  const [active, setActive] = useState(sections[0]?.id)
  const pinned = useRef(null)
  const highlightTimer = useRef(0)

  useEffect(() => () => clearTimeout(highlightTimer.current), [])

  useEffect(() => {
    const list = ids.split('|')
    let ticking = false
    let settle = 0

    const natural = () => {
      const atBottom = window.scrollY > 0 && window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2
      if (atBottom) return list[list.length - 1]
      const line = window.scrollY + window.innerHeight * 0.38
      let current = list[0]
      for (const id of list) {
        const element = document.getElementById(id)
        if (element && element.getBoundingClientRect().top + window.scrollY <= line) current = id
      }
      return current
    }

    const update = () => {
      ticking = false
      setActive(pinned.current ?? natural())
    }

    // 목차를 눌러 생긴 스크롤이 멈춘 뒤: 누른 구역이 기준선에 닿았으면 고정을 풀고 평소 규칙으로 돌아간다.
    // 닿지 못했으면(페이지가 짧음) 누른 구역을 그대로 둔다.
    const onSettled = () => {
      if (pinned.current && natural() === pinned.current) pinned.current = null
      update()
    }

    const onScroll = () => {
      clearTimeout(settle)
      settle = setTimeout(onSettled, SETTLE_MS)
      if (!ticking) {
        ticking = true
        requestAnimationFrame(update)
      }
    }

    const release = () => {
      if (pinned.current) {
        pinned.current = null
        onScroll()
      }
    }

    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    window.addEventListener('wheel', release, { passive: true })
    window.addEventListener('touchstart', release, { passive: true })
    window.addEventListener('keydown', release)
    return () => {
      clearTimeout(settle)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      window.removeEventListener('wheel', release)
      window.removeEventListener('touchstart', release)
      window.removeEventListener('keydown', release)
    }
  }, [ids])

  // 누른 구역으로 스크롤하고, 그 구역에 잠깐 테두리를 띄워 어디로 왔는지 보여준다.
  // 페이지가 짧아 구역이 화면 위까지 올라오지 못해도(첫 화면의 "특징") 테두리로 위치를 알 수 있다.
  // 키보드·화면 읽기 사용자를 위해 포커스도 그 구역으로 옮긴다(스크롤은 위에서 따로 하므로 preventScroll).
  function go(id) {
    const target = document.getElementById(id)
    if (!target) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    pinned.current = id
    setActive(id)
    target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })

    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1')
    target.setAttribute('data-rail-target', '')
    target.focus({ preventScroll: true })
    target.classList.remove('section-target')
    void target.offsetWidth // 같은 구역을 연달아 눌러도 테두리 효과가 처음부터 다시 돌게
    target.classList.add('section-target')
    clearTimeout(highlightTimer.current)
    highlightTimer.current = setTimeout(() => target.classList.remove('section-target'), 1600)
  }

  return (
    <nav className="section-rail" aria-label="이 화면의 구역">
      <ol className="section-rail__list">
        {sections.map((section, index) => {
          const isActive = section.id === active
          return (
            <li key={section.id}>
              <button
                type="button"
                className={`section-rail__item${isActive ? ' is-active' : ''}`}
                aria-current={isActive ? 'true' : undefined}
                onClick={() => go(section.id)}
              >
                <span className="section-rail__num">{String(index + 1).padStart(2, '0')}</span>
                <span>{section.label}</span>
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
