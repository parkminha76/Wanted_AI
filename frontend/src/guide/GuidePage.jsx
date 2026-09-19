import { EyeOff, FileUp, ScanSearch, TriangleAlert } from 'lucide-react'
import { UPLOAD_LIMITS } from '../shared/api.js'
import { Badge, Button, DecodeText, GlowCard, SectionRail } from '../shared/components/index.js'
import './guide.css'

// 아이콘은 훈련 모드 소개 카드(FEATURES)와 같은 Lucide line icon 세트를 쓴다.
//   FileUp 파일 업로드 / ScanSearch AI가 훑어 찾는 동작("검사") / TriangleAlert 위험 경고 / EyeOff 가려서 안 보이게(마스킹)
const STEPS = [
  { number: '01', Icon: FileUp, title: '문서 업로드', copy: `PDF·Word·Excel·텍스트·이미지 파일을 한 번에 최대 ${UPLOAD_LIMITS.maxFiles}개까지 업로드합니다.` },
  { number: '02', Icon: ScanSearch, title: 'AI 보안 검사', copy: '형식·체크섬 규칙, 개체명 인식, 직접 학습한 분류기가 개인정보와 숨은 AI 명령을 찾습니다.' },
  { number: '03', Icon: TriangleAlert, title: '위험 요소 확인', copy: '파일별 위험도, 탐지 위치와 판단 근거, 오탐으로 제외한 항목까지 확인합니다.' },
  { number: '04', Icon: EyeOff, title: '안전하게 마스킹', copy: '원본 형식 그대로, 위험 요소만 마스킹한 사본을 내려받습니다. 원본은 바로 삭제됩니다.' },
]

const SECTIONS = [
  { id: 'intro', label: '소개' },
  { id: 'steps', label: '단계' },
  { id: 'start', label: '시작' },
]

const UPLOAD_BUTTON_SELECTOR = '#upload .dropzone .btn' // UploadPage.jsx의 goToUpload()가 쓰는 것과 같은 자리
const WAIT_FRAMES = 20 // 첫 화면이 그려지기를 기다리는 최대 프레임 수(약 0.3초, AppFooter.jsx와 같은 값)

export default function GuidePage({ navigate }) {
  // 첫 화면으로 옮긴 뒤, 그 화면이 그려지면 업로드 상자까지 스크롤하고 안의 버튼에 초점을 둔다.
  // 다른 화면이라 지금은 그 요소가 없으므로, 그려질 때까지 프레임마다 확인한다(AppFooter.jsx의 goToSection과 같은 방식).
  function goToUpload() {
    navigate('')
    let tries = 0
    const tick = () => {
      const target = document.querySelector(UPLOAD_BUTTON_SELECTOR)
      if (target) {
        const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
        document.getElementById('upload')?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
        target.focus({ preventScroll: true })
        return
      }
      if (tries < WAIT_FRAMES) {
        tries += 1
        requestAnimationFrame(tick)
      }
    }
    requestAnimationFrame(tick)
  }

  return (
    <div className="container guide-page">
      <SectionRail sections={SECTIONS} />
      <section id="intro" className="guide-intro rv">
        <Badge>HOW IT WORKS</Badge>
        <h1 className="page-title">DocX-ray 이용 가이드</h1>
        <p className="page-desc">문서를 안전하게 검사하고 보호하는 방법을 확인하세요.</p>
      </section>

      {/* 뜨는 효과(:hover transform)는 바깥 li가 갖고, 빛(GlowCard)은 안쪽 div가 갖는다.
          둘을 한 요소에 같이 두면 호버 중 transform이 걸리는 순간 GlowCard의
          background-attachment: fixed 좌표가 요소 로컬 좌표로 다시 해석돼 빛이 카드 밖으로 밀려난다. */}
      <ol id="steps" className="guide-steps stagger">
        {STEPS.map((step) => (
          <li key={step.number} className="guide-step rv">
            <GlowCard className="guide-step__glow">
              <div className="guide-step__top">
                <span className="guide-step__number">
                  <DecodeText text={step.number} />
                </span>
                <span className="guide-step__icon" aria-hidden="true">
                  <step.Icon size={22} strokeWidth={1.8} />
                </span>
              </div>
              <h2 className="guide-step__title">{step.title}</h2>
              <p className="guide-step__copy">{step.copy}</p>
            </GlowCard>
          </li>
        ))}
      </ol>

      <div id="start" className="cta-card rv">
        <div>
          <b>지금 문서의 보안 상태를 확인해 보세요.</b>
          <p>업로드부터 안전한 문서 다운로드까지, DocX-ray가 도와드립니다.</p>
        </div>
        <Button onClick={goToUpload}>문서 검사 시작하기 →</Button>
      </div>
    </div>
  )
}
