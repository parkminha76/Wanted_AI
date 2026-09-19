import { RiskBadge } from '../shared/components/index.js'

// 검사한 파일을 고르는 드롭다운. 최대 10개까지 올릴 수 있어서 버튼을 나열하면
// 화면이 파일 목록에 먹힌다. 목록 순서는 서버가 정렬해 준 위험도 순서 그대로다
// (schema.ScanBatch.sorted_by_risk — 프론트가 다시 정렬하지 않는다).
// 기본 선택은 App.startScan이 "처음 올린 파일"로 맞춰 준다.
export default function FileSwitcher({ results = [], index, onSelect }) {
  if (results.length <= 1) return null
  const current = results[index] ?? results[0]

  return (
    <div className="file-switcher">
      <label className="file-switcher__label" htmlFor="file-switcher-select">
        검사한 파일
      </label>
      <select
        id="file-switcher-select"
        className="file-switcher__select"
        value={index}
        onChange={(event) => onSelect(Number(event.target.value))}
      >
        {results.map((result, i) => (
          <option key={result.file_id || `${result.filename}-${i}`} value={i}>
            {result.filename || '텍스트'} · 위험도 {Math.round(result.risk_score)}
          </option>
        ))}
      </select>
      {/* 배지는 select 밖에 둔다 — option 안에서는 색이 안 먹는다. */}
      <RiskBadge level={current.level} score={current.risk_score} />
      <span className="file-switcher__count">전체 {results.length}개</span>
    </div>
  )
}
