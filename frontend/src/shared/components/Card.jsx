// 공통 카드. 제목·설명·오른쪽 동작(버튼, 배지)을 머리에 두고 본문은 children.
//   tone: danger | muted
export default function Card({ title, description, actions, tone, as: Tag = 'section', className = '', children }) {
  const classes = ['card', tone && `card--${tone}`, className].filter(Boolean).join(' ')
  const hasHeader = title || description || actions

  return (
    <Tag className={classes}>
      {hasHeader && (
        <div className="card__header">
          <div className="card__heading">
            {title && <h2 className="card__title">{title}</h2>}
            {description && <p className="card__description">{description}</p>}
          </div>
          {actions && <div className="card__actions">{actions}</div>}
        </div>
      )}
      {children}
    </Tag>
  )
}
