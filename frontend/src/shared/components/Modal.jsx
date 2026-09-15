import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'

// 공통 모달. Esc·바깥 클릭·닫기 버튼으로 닫히고, 열려 있는 동안 뒤 페이지 스크롤을 막는다.
// 닫히면 열기 전에 포커스가 있던 버튼으로 돌아간다(키보드 사용자용).
export default function Modal({ open, title, onClose, actions, children }) {
  const titleId = useId()
  const dialogRef = useRef(null)

  // 부모가 매 렌더마다 새 함수를 넘겨도 아래 effect가 다시 돌지 않게 ref에 담는다.
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    if (!open) return undefined

    const previousFocus = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialogRef.current?.focus()

    const onKeyDown = (event) => {
      if (event.key === 'Escape') onCloseRef.current?.()
    }
    document.addEventListener('keydown', onKeyDown)

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
      previousFocus?.focus?.()
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCloseRef.current?.()
      }}
    >
      <div ref={dialogRef} className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="modal__header">
          <h2 id={titleId} className="modal__title">
            {title}
          </h2>
          <button type="button" className="modal__close" onClick={() => onCloseRef.current?.()} aria-label="닫기">
            ×
          </button>
        </div>
        <div className="modal__body">{children}</div>
        {actions && <div className="modal__actions">{actions}</div>}
      </div>
    </div>,
    document.body,
  )
}
