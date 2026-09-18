import { useEffect, useRef } from 'react'

// 마우스를 따라 테두리에 빛이 번지는 카드(스포트라이트 카드). 모양은 components.css의 .glow-card.
//   <GlowCard as="li" className="landing-card">…</GlowCard>
//
// 빛 위치는 카드마다 "자기 자신의 왼쪽 위 모서리에서 마우스까지의 거리"로 계산해 각 카드 자신에 직접 심는다
// (--glow-local-x/y, background-attachment는 기본값인 scroll). 마우스 이벤트 리스너는 문서에 하나만 붙이고,
// 매 프레임 등록된 카드 전체를 순회해 각자의 지점을 다시 계산한다 — 카드 수와 상관없이 리스너는 하나다.
//
// 예전에는 화면(viewport) 좌표 하나를 모든 카드가 공유하고 background-attachment: fixed로 그렸다. 더 단순했지만
// 크롬에서 이 방식이 특정 상황(중첩된 위치·구조에 따라, 정확히는 규명하지 못한 조건)에 커스텀 프로퍼티가 바뀌어도
// 다시 그려지지 않는 경우가 있었다 — 계산된 값은 맞는데 화면에 반영이 안 됨(이용 가이드 카드에서 재현). 카드 자신의
// 로컬 좌표 + 기본 배경 첨부 방식으로 바꾸니 이 문제가 사라졌다. 성능 대신 정확성을 택한 선택이다.
//
// 켜는 조건: 마우스처럼 올려놓을 수 있는 포인터가 있고, 움직임 줄이기 설정이 아닐 때. 터치 화면에서는 아무것도 하지 않는다.
// 마우스를 한 번도 움직이지 않았거나 창 밖으로 나가면 --glow-on이 0이라 빛이 보이지 않는다.
//
// 참고: 원본(spotlight-card.tsx)은 카드마다 <style>과 pointermove를 새로 붙이고 touch-action: none을 걸어
// 휴대폰에서 카드 위를 밀면 페이지가 스크롤되지 않았다. 여기서는 둘 다 없앴다.

const registry = new Set()
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
  const rootStyle = document.documentElement.style
  // 색상각 스침(--glow-hue-now)만 화면 전체 기준 위치를 쓴다 — 이건 배경 위치 계산이 아니라
  // 그냥 숫자 하나를 색 공식에 넣는 것이라 fixed 첨부 버그와 무관하다.
  rootStyle.setProperty('--glow-xp', (lastPointer.x / window.innerWidth).toFixed(3))
  rootStyle.setProperty('--glow-on', '1')

  for (const el of registry) {
    const rect = el.getBoundingClientRect()
    el.style.setProperty('--glow-local-x', (lastPointer.x - rect.left).toFixed(1))
    el.style.setProperty('--glow-local-y', (lastPointer.y - rect.top).toFixed(1))
  }
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
  const ref = useRef(null)

  useEffect(() => {
    const el = ref.current
    subscribe()
    if (el) registry.add(el)
    return () => {
      if (el) registry.delete(el)
      unsubscribe()
    }
  }, [])

  return (
    <Tag ref={ref} className={`glow-card ${className}`.trim()} {...rest}>
      {children}
    </Tag>
  )
}
