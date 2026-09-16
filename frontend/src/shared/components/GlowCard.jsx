import { useEffect } from 'react'

// 마우스를 따라 테두리에 빛이 번지는 카드(스포트라이트 카드). 모양은 components.css의 .glow-card.
//   <GlowCard as="li" className="landing-card">…</GlowCard>
//
// 빛 위치는 화면(viewport) 좌표 하나를 모든 카드가 같이 쓴다 — 배경을 background-attachment: fixed로 깔고
// 그 위의 --glow-x/--glow-y 지점에 원형 그라디언트를 그린다. 그래서 마우스 이벤트는 카드 수와 상관없이 문서에 하나만 붙인다.
//
// 켜는 조건: 마우스처럼 올려놓을 수 있는 포인터가 있고, 움직임 줄이기 설정이 아닐 때. 터치 화면에서는 아무것도 하지 않는다.
// 마우스를 한 번도 움직이지 않았거나 창 밖으로 나가면 --glow-on이 0이라 빛이 보이지 않는다.
//
// 참고: 원본(spotlight-card.tsx)은 카드마다 <style>과 pointermove를 새로 붙이고 touch-action: none을 걸어
// 휴대폰에서 카드 위를 밀면 페이지가 스크롤되지 않았다. 여기서는 둘 다 없앴다.

let subscribers = 0
let frame = 0
let lastPointer = null

function canGlow() {
  return (
    window.matchMedia?.('(hover: hover) and (pointer: fine)').matches &&
    !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  )
}

function applyPointer() {
  frame = 0
  if (!lastPointer) return
  const style = document.documentElement.style
  style.setProperty('--glow-x', lastPointer.x.toFixed(1))
  style.setProperty('--glow-y', lastPointer.y.toFixed(1))
  style.setProperty('--glow-xp', (lastPointer.x / window.innerWidth).toFixed(3))
  style.setProperty('--glow-on', '1')
}

function onPointerMove(event) {
  if (event.pointerType === 'touch') return
  lastPointer = { x: event.clientX, y: event.clientY }
  if (!frame) frame = requestAnimationFrame(applyPointer)
}

// 창 밖으로 나가면(relatedTarget이 없음) 빛을 끈다
function onMouseOut(event) {
  if (!event.relatedTarget) document.documentElement.style.setProperty('--glow-on', '0')
}

function subscribe() {
  subscribers += 1
  if (subscribers === 1 && canGlow()) {
    document.addEventListener('pointermove', onPointerMove, { passive: true })
    document.addEventListener('mouseout', onMouseOut)
  }
}

function unsubscribe() {
  subscribers -= 1
  if (subscribers > 0) return
  document.removeEventListener('pointermove', onPointerMove)
  document.removeEventListener('mouseout', onMouseOut)
  cancelAnimationFrame(frame)
  frame = 0
  lastPointer = null
  document.documentElement.style.setProperty('--glow-on', '0')
}

export default function GlowCard({ as: Tag = 'div', className = '', children, ...rest }) {
  useEffect(() => {
    subscribe()
    return unsubscribe
  }, [])

  return (
    <Tag className={`glow-card ${className}`.trim()} {...rest}>
      {children}
    </Tag>
  )
}
