// 위험도 배지. level은 서버가 계산해 준 값(high/medium/low)을 그대로 쓴다 —
// 화면에서 점수로 다시 구간을 나누면 schema.py 기준과 어긋날 수 있다.
//
// 글자는 "높은 위험 98점"이 아니라 "위험도 98 / 100"이다. 등급 이름만으로는
// 무엇이 높다는 건지 전해지지 않는다는 피드백이 있었다. 등급은 색으로만 남긴다.
export const LEVEL_LABELS = {
  high: '높은 위험',
  medium: '주의',
  low: '낮은 위험',
}

// 점수가 무슨 뜻인지 한 줄. 점수를 처음 보여주는 화면이 이 문구를 함께 쓴다.
export const SCORE_HINT = '점수가 높을수록 파일 내 보안상 주의가 필요한 요소가 많습니다.'

export default function RiskBadge({ level = 'low', score }) {
  return (
    <span className={`badge badge--${level}`}>
      {typeof score === 'number' ? (
        <>
          위험도
          <span className="badge__score">{Math.round(score)} / 100</span>
        </>
      ) : (
        (LEVEL_LABELS[level] ?? level)
      )}
    </span>
  )
}
