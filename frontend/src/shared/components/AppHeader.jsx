import { useState } from 'react'

const LINKS = [
  { to: '', label: '문서 검사', match: (route) => route === '' || route === 'scanning' || route.startsWith('results') },
  { to: 'training', label: '훈련 모드', match: (route) => route.startsWith('training') },
  { to: 'guide', label: '이용 가이드', match: (route) => route === 'guide' },
]

// 상단 헤더. 768px 미만에서는 메뉴 버튼으로 여닫는다.
export default function AppHeader({ route, onNavigate }) {
  const [open, setOpen] = useState(false)

  const go = (to) => {
    setOpen(false)
    onNavigate(to)
  }

  return (
    <header className="app-header">
      <div className="app-header__inner container">
        <button type="button" className="brand" onClick={() => go('')} aria-label="DocX-ray 첫 화면">
          <span className="brand__mark" aria-hidden="true">
            ✦
          </span>
          <span>
            Doc<span className="brand__accent">X</span>-ray
          </span>
        </button>

        <button
          type="button"
          className="app-header__menu"
          aria-label={open ? '메뉴 닫기' : '메뉴 열기'}
          aria-expanded={open}
          aria-controls="main-nav"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? '×' : '☰'}
        </button>

        <nav id="main-nav" className={`app-header__nav${open ? ' is-open' : ''}`} aria-label="주요 메뉴">
          {LINKS.map((link) => {
            const active = link.match(route)
            return (
              <button
                key={link.label}
                type="button"
                className={`app-header__link${active ? ' is-active' : ''}`}
                aria-current={active ? 'page' : undefined}
                onClick={() => go(link.to)}
              >
                {link.label}
              </button>
            )
          })}
        </nav>
      </div>
    </header>
  )
}
