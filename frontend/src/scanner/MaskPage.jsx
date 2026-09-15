import { useState } from 'react'
import { api } from '../shared/api.js'
import { Button } from '../shared/components/index.js'
import { GROUPS, GROUP_ORDER, countByGroup } from '../shared/findings.js'
import DocumentPreview from './DocumentPreview.jsx'
import EmptyResult from './EmptyResult.jsx'
import FileSwitcher from './FileSwitcher.jsx'
import './scanner.css'

export default function MaskPage({ batch, file, fileIndex, onSelectFile, navigate }) {
  const [masked, setMasked] = useState(true)

  if (!batch || !file) return <EmptyResult navigate={navigate} />

  const counts = countByGroup(file.findings)
  const summary = GROUP_ORDER.filter((key) => counts[key] > 0).map((key) =>
    key === 'hidden' ? `숨겨진 명령어 ${counts[key]}건을 [숨은 명령]으로 바꿈` : `${GROUPS[key].label} ${counts[key]}건 마스킹 완료`,
  )
  const downloadableCount = batch.results.filter((result) => result.file_id).length

  return (
    <div className="container mask-page">
      <button type="button" className="back-link" onClick={() => navigate('results')}>
        ← 분석 결과로 돌아가기
      </button>
      <div className="page-head">
        <div>
          <h1 className="page-title">안전하게 마스킹된 문서</h1>
          <p className="page-desc">위험 요소를 [계좌번호]처럼 유형 이름으로 바꿔, AI 도구에 넣어도 문맥이 유지되게 했습니다.</p>
        </div>
        <button type="button" role="switch" aria-checked={masked} className="switch" onClick={() => setMasked((value) => !value)}>
          <span className="switch__track" aria-hidden="true">
            <span className="switch__thumb" />
          </span>
          마스킹 적용
        </button>
      </div>

      <FileSwitcher results={batch.results} index={fileIndex} onSelect={onSelectFile} />

      <section className="mask-grid">
        <div className="panel">
          <div className="panel__heading">
            <b>{masked ? '마스킹 사본' : '원문 (탐지 위치 표시)'}</b>
            <small>{file.filename || '텍스트'}</small>
          </div>
          <DocumentPreview
            title={file.filename}
            text={file.raw_text}
            findings={file.findings}
            masked={masked}
            maskedText={file.masked_text}
          />
        </div>

        <aside className="panel mask-summary">
          <div className="mask-summary__shield" aria-hidden="true">
            ♢
          </div>
          <h2 className="mask-summary__title">
            {file.findings.length > 0 ? '중요한 정보가 안전하게 보호되었습니다.' : '가릴 위험 요소가 없었습니다.'}
          </h2>
          {summary.length > 0 && (
            <ul className="checklist">
              {summary.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}

          {file.file_id ? (
            <Button size="lg" block href={api.downloadUrl(file.file_id)}>
              마스킹된 문서 다운로드
            </Button>
          ) : (
            <p className="alert alert--info">이 파일은 원본 형식의 사본을 만들지 못했습니다. 왼쪽 텍스트 사본을 참고해 주세요.</p>
          )}
          {batch.batch_id && downloadableCount > 1 && (
            <Button variant="secondary" block href={api.downloadAllUrl(batch.batch_id)}>
              사본 {downloadableCount}개 한 번에 받기 (.zip)
            </Button>
          )}
          <p className="mask-summary__note">원본은 서버에서 이미 삭제되었습니다. 사본은 검사 후 30분 동안만 받을 수 있습니다.</p>
        </aside>
      </section>
    </div>
  )
}
