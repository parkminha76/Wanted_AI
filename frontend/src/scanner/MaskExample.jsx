import { useState } from 'react'
import EXAMPLE from './maskExampleData.js'

// 두 마스킹 방식이 실제로 어떻게 나오는지 보여주는 예시. 내용은 샘플 계약서.pdf 1쪽 앞부분으로
// 고정이다 — 올린 문서가 무엇이든 "전체는 [유형]으로, 부분은 일부만 *로"라는 차이만 전하면 된다.
// 내 문서가 아니라는 것이 한눈에 보여야 해서 '예시' 딱지를 붙이고 테두리를 점선으로 준다.
export default function MaskExample() {
  const [mode, setMode] = useState('full')
  const standard = mode === 'standard'

  return (
    <div className="mask-example">
      <div className="mask-example__head">
        <span className="mask-example__badge">예시</span>
        <b>두 방식은 이렇게 다릅니다</b>
      </div>
      <div className="tabs" role="tablist" aria-label="마스킹 방식 예시">
        <button
          type="button"
          role="tab"
          aria-selected={!standard}
          className="tabs__tab"
          onClick={() => setMode('full')}
        >
          전체 마스킹
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={standard}
          className="tabs__tab"
          onClick={() => setMode('standard')}
        >
          부분 마스킹
        </button>
      </div>
      <p className="mask-example__desc">
        {standard
          ? '값의 일부만 남기고 나머지를 *로 가립니다. 사람이 원본과 대조하거나 본인 확인을 해야 하는 문서에 씁니다.'
          : '값을 지우고 그 자리에 무엇이 있었는지만 [유형] 이름으로 남깁니다.'}
      </p>
      <pre className="mask-example__doc">
        {EXAMPLE[standard ? 'standard' : 'full'].map((segment, index) =>
          segment.m ? (
            <mark key={index} className={segment.m === 'standard' ? 'hit hit--standard' : 'mask-token'}>
              {segment.t}
            </mark>
          ) : (
            <span key={index}>{segment.t}</span>
          ),
        )}
      </pre>
      <p className="mask-example__note">
        샘플 계약서.pdf 1쪽의 일부입니다. 예시이며 실제 데이터 파일이 아닙니다.
        {standard &&
          ' 조직명·사업자등록번호처럼 부분 규칙이 없는 유형은 부분 마스킹을 골라도 [유형]으로 통째 가립니다.'}
      </p>
    </div>
  )
}
