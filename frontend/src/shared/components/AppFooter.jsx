// 모든 화면 아래에 붙는 바닥글. 첫 화면(랜딩)에서 쓰던 것을 훈련 모드·이용 가이드에서도 함께 쓴다.
//
// 스타일은 아직 scanner/landing.css의 "바닥글" 단락에 있다. 이 파일에서 직접 불러와,
// 랜딩 화면을 거치지 않고 #training이나 #guide로 바로 들어와도 모양이 깨지지 않게 한다.
//
// 가운데 링크들은 랜딩의 구역(id)으로 데려간다. 지금 화면에 그 구역이 없으면 먼저 랜딩으로 옮기고,
// 랜딩이 그려진 다음에 스크롤한다.
import { useState } from 'react'
import LegalPolicyModal from './LegalPolicyModal.jsx'
import '../../scanner/landing.css'

const SECTION_WAIT_FRAMES = 20 // 랜딩이 그려지기를 기다리는 최대 프레임 수(약 0.3초)

function scrollTo(id) {
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  document.getElementById(id)?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
}

// standalone: 첫 화면 밖(훈련 모드·이용 가이드)에서 쓸 때. 본문과 붙지 않게 위 여백을 스스로 준다.
export default function AppFooter({ navigate, onScan, busy = false, standalone = false }) {
  const [policy, setPolicy] = useState(null)

  function goToSection(id) {
    if (document.getElementById(id)) {
      scrollTo(id)
      return
    }
    navigate('')
    let tries = 0
    const tick = () => {
      if (document.getElementById(id)) {
        scrollTo(id)
        return
      }
      if (tries < SECTION_WAIT_FRAMES) {
        tries += 1
        requestAnimationFrame(tick)
      }
    }
    requestAnimationFrame(tick)
  }

  return (
    <footer className={`container landing-footer${standalone ? ' landing-footer--standalone' : ''}`}>
      <div className="landing-footer__top">
        <div className="landing-footer__brand">
          <img
            className="landing-footer__logo"
            src="/docxray-logo-white.png"
            alt="DocX-ray — Document security beyond the surface"
          />
          <p className="landing-footer__tagline">
            AI가 문서 속 개인정보와
            <br />
            숨겨진 위험 요소를 탐지합니다.
          </p>
          <p className="landing-footer__stack" aria-hidden="true">
            SAFER DOCUMENTS
            <br />
            BRIGHTER TOMORROW
          </p>
        </div>

        <nav className="landing-footer__col" aria-label="서비스">
          <p className="landing-footer__title">서비스</p>
          <ul>
            <li>
              <button type="button" className="landing-footer__link" onClick={() => goToSection('upload')}>
                문서 보안 검사
              </button>
            </li>
            <li>
              <button type="button" className="landing-footer__link" onClick={() => navigate('training')}>
                사기 대응 훈련
              </button>
            </li>
          </ul>
        </nav>

        <nav className="landing-footer__col" aria-label="안내">
          <p className="landing-footer__title">안내</p>
          <ul>
            <li>
              <button type="button" className="landing-footer__link" onClick={() => navigate('guide')}>
                이용 가이드
              </button>
            </li>
          </ul>
        </nav>

        <nav className="landing-footer__col" aria-label="법적 고지">
          <p className="landing-footer__title">법적 고지</p>
          <ul>
            <li>
              <button type="button" className="landing-footer__link" onClick={() => setPolicy('terms')}>
                이용약관
              </button>
            </li>
            <li>
              <button type="button" className="landing-footer__link" onClick={() => setPolicy('privacy')}>
                개인정보 처리방침
              </button>
            </li>
          </ul>
        </nav>

        <div className="landing-footer__aside">
          <svg className="landing-footer__lock" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="4.5" y="10" width="15" height="10.5" rx="2.5" />
            <path d="M8 10V7a4 4 0 0 1 8 0v3" />
          </svg>
          <p className="landing-footer__aside-text">
            당신의 문서가 더 안전한 세상을 위해, <b>DocX-ray</b>가 함께합니다.
          </p>
          <p className="landing-footer__stack" aria-hidden="true">
            SAFE DOCUMENTS
            <br />
            SAFE BUSINESS
          </p>
        </div>
      </div>

      <div className="landing-footer__meta">
        <span>© 2026 Tracer 팀 · 2026 원티드 AI Championship 제안 프로젝트</span>
        <address className="landing-footer__address">
          Playdata 평생교육원 · 서울특별시 서초구 효령로 335 (서초동, 대호프레조빌) 1층 · Tel : 0507-1355-7302
        </address>
      </div>
      <LegalPolicyModal type={policy} onClose={() => setPolicy(null)} />
    </footer>
  )
}
