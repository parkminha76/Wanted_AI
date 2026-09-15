import { RiskBadge } from '../shared/components/index.js'

// 여러 파일을 올렸을 때 파일을 고르는 줄. 순서는 서버가 정렬해 준 위험도 순서 그대로다.
export default function FileSwitcher({ results = [], index, onSelect }) {
  if (results.length <= 1) return null

  return (
    <div className="file-switcher" aria-label="검사한 파일">
      {results.map((result, i) => (
        <button
          key={result.file_id || `${result.filename}-${i}`}
          type="button"
          className="file-switcher__item"
          aria-pressed={i === index}
          onClick={() => onSelect(i)}
        >
          <span className="file-switcher__name">{result.filename || '텍스트'}</span>
          <RiskBadge level={result.level} score={result.risk_score} />
        </button>
      ))}
    </div>
  )
}
