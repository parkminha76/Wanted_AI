import { useEffect, useRef } from 'react'
import { Button } from '../shared/components/index.js'
import { GROUPS, GROUP_ORDER, groupOf } from '../shared/findings.js'

// 선택 마스킹 목록. 묶음(개인정보·민감정보·숨겨진 명령어·기타) → 유형 → 항목 순서로 체크한다.
//   choices: { [finding.id]: { checked, action } }
//   standardTypes: 부분 마스킹을 지원하는 유형(Set) — GET /masking/options의 supports_standard
export default function SelectiveMaskPanel({
  findings,
  choices,
  standardTypes,
  descriptions,
  onToggle,
  onToggleMany,
  onActionChange,
}) {
  const allIds = findings.map((finding) => finding.id)
  const selectedCount = allIds.filter((id) => choices[id]?.checked).length

  return (
    <div className="selective">
      <div className="selective__toolbar">
        <p className="selective__count" aria-live="polite">
          <b>{selectedCount}</b> / {findings.length}개 선택
        </p>
        <div className="row">
          <Button size="sm" variant="secondary" onClick={() => onToggleMany(allIds, true)}>
            전체 선택
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onToggleMany(allIds, false)}>
            전체 해제
          </Button>
        </div>
      </div>

      <div className="selective__groups">
        {GROUP_ORDER.map((groupKey) => {
          const groupFindings = findings.filter((finding) => groupOf(finding.type) === groupKey)
          if (groupFindings.length === 0) return null
          const types = [...new Set(groupFindings.map((finding) => finding.type))]

          return (
            <section key={groupKey} className="selective-group" aria-label={GROUPS[groupKey].label}>
              <GroupCheckbox
                className="selective-group__head"
                ids={groupFindings.map((finding) => finding.id)}
                choices={choices}
                onToggleMany={onToggleMany}
              >
                <b>{GROUPS[groupKey].label}</b>
                <span className="chip">{groupFindings.length}</span>
              </GroupCheckbox>

              {types.map((type) => {
                const items = groupFindings.filter((finding) => finding.type === type)
                const label = items[0].label
                const action = choices[items[0].id]?.action ?? 'full'
                const supportsStandard = standardTypes.has(type)

                return (
                  <div key={type} className="selective-type">
                    <div className="selective-type__head">
                      <GroupCheckbox
                        className="selective-type__check"
                        ids={items.map((finding) => finding.id)}
                        choices={choices}
                        onToggleMany={onToggleMany}
                      >
                        {label} <span className="text-muted">{items.length}</span>
                      </GroupCheckbox>
                      {supportsStandard ? (
                        <div className="segmented" aria-label={`${label} 마스킹 방식`}>
                          <button
                            type="button"
                            className="segmented__option"
                            aria-pressed={action !== 'standard'}
                            onClick={() => onActionChange(type, 'full')}
                          >
                            전체
                          </button>
                          <button
                            type="button"
                            className="segmented__option"
                            aria-pressed={action === 'standard'}
                            onClick={() => onActionChange(type, 'standard')}
                          >
                            부분
                          </button>
                        </div>
                      ) : (
                        <span className="chip">전체만 가능</span>
                      )}
                    </div>
                    {supportsStandard && action === 'standard' && descriptions[type] && (
                      <p className="selective-type__rule">부분 마스킹: {descriptions[type]}</p>
                    )}
                    <ul className="selective-items">
                      {items.map((finding) => (
                        <li key={finding.id}>
                          <label className="selective-item">
                            <input
                              type="checkbox"
                              checked={Boolean(choices[finding.id]?.checked)}
                              onChange={() => onToggle(finding.id)}
                            />
                            <span className="selective-item__value">{finding.text}</span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  </div>
                )
              })}
            </section>
          )
        })}
      </div>
    </div>
  )
}

// 여러 항목을 한 번에 켜고 끄는 체크박스. 일부만 켜져 있으면 중간 상태(indeterminate)로 보인다.
function GroupCheckbox({ ids, choices, onToggleMany, className, children }) {
  const ref = useRef(null)
  const checkedCount = ids.filter((id) => choices[id]?.checked).length
  const all = checkedCount === ids.length
  const some = checkedCount > 0 && !all

  useEffect(() => {
    if (ref.current) ref.current.indeterminate = some
  }, [some])

  return (
    <label className={className}>
      <input ref={ref} type="checkbox" checked={all} onChange={() => onToggleMany(ids, !all)} />
      <span>{children}</span>
    </label>
  )
}
