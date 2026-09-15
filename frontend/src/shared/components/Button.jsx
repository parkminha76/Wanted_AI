// 공통 버튼. href를 주면 링크(<a>)로 그린다 — 마스킹 사본 다운로드처럼 주소로 이동하는 동작용.
//   variant: primary | secondary | ghost | danger
//   size:    sm | md | lg   (sm도 높이 44px은 지킨다)
export default function Button({
  variant = 'primary',
  size = 'md',
  block = false,
  href,
  type = 'button',
  className = '',
  children,
  ...rest
}) {
  const classes = ['btn', `btn--${variant}`, `btn--${size}`, block && 'btn--block', className]
    .filter(Boolean)
    .join(' ')

  if (href) {
    return (
      <a className={classes} href={href} {...rest}>
        {children}
      </a>
    )
  }

  return (
    <button type={type} className={classes} {...rest}>
      {children}
    </button>
  )
}
