import { Button, DecodeText, SectionRail } from '../shared/components/index.js'
import './guide.css'

const STEPS = [
  { number: '01', icon: '⌑', title: '문서 올리기', copy: 'PDF·Word·Excel·텍스트·이미지 파일을 한 번에 최대 20개까지 올립니다.' },
  { number: '02', icon: '✦', title: 'AI 보안 검사', copy: '형식·체크섬 규칙, 개체명 인식, 직접 학습한 분류기가 개인정보와 숨은 AI 명령을 찾습니다.' },
  { number: '03', icon: '◈', title: '위험 요소 확인', copy: '파일별 위험도, 탐지 위치와 판단 근거, 오탐으로 제외한 항목까지 확인합니다.' },
  { number: '04', icon: '✓', title: '안전하게 마스킹', copy: '원본 형식 그대로 위험 요소만 가린 사본을 내려받습니다. 원본은 바로 삭제됩니다.' },
]

const SECTIONS = [
  { id: 'intro', label: '소개' },
  { id: 'steps', label: '단계' },
  { id: 'start', label: '시작' },
]

export default function GuidePage({ navigate }) {
  return (
    <div className="container guide-page">
      <SectionRail sections={SECTIONS} />
      <section id="intro" className="guide-intro rv">
        <p className="eyebrow">
          <span className="eyebrow__num">003</span>HOW IT WORKS
        </p>
        <h1 className="page-title">DocX-ray 이용 가이드</h1>
        <p className="page-desc">문서를 안전하게 검사하고 보호하는 방법을 확인하세요.</p>
      </section>

      <ol id="steps" className="guide-steps stagger">
        {STEPS.map((step) => (
          <li key={step.number} className="guide-step rv">
            <div className="guide-step__top">
              <span className="guide-step__number">
                <DecodeText text={step.number} />
              </span>
              <span className="guide-step__icon" aria-hidden="true">
                {step.icon}
              </span>
            </div>
            <h2 className="guide-step__title">{step.title}</h2>
            <p className="guide-step__copy">{step.copy}</p>
          </li>
        ))}
      </ol>

      <div id="start" className="cta-card rv">
        <div>
          <b>지금 문서의 보안 상태를 확인해 보세요.</b>
          <p>업로드부터 안전한 문서 다운로드까지, DocX-ray가 도와드립니다.</p>
        </div>
        <Button onClick={() => navigate('')}>문서 검사 시작하기 →</Button>
      </div>
    </div>
  )
}
