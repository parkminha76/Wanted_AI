// 위험도 배지. level은 서버가 계산해 준 값(high/medium/low)을 그대로 쓴다 —
// 화면에서 점수로 다시 구간을 나누면 schema.py 기준과 어긋날 수 있다.
export const LEVEL_LABELS = {
  high: '높은 위험',
  medium: '주의',
  low: '낮은 위험',
}

export default function RiskBadge({ level = 'low', score }) {
  return (
    <span className={`badge badge--${level}`}>
      {LEVEL_LABELS[level] ?? level}
      {typeof score === 'number' && <span className="badge__score">{Math.round(score)}점</span>}
    </span>
  )
}
