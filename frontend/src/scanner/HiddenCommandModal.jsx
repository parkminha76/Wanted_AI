import { Button, Modal } from '../shared/components/index.js'

// 숨은 명령 확인 팝업 — 버튼 3개("이 문장을 제거하고 사본 만들기" / "무시하고 진행" / "이 파일 취소").
export default function HiddenCommandModal({ open, result, onClose, onRemove, onIgnore, onCancelFile }) {
  if (!result) return null

  const commands = result.findings.filter((finding) => finding.type === 'injection' || finding.type === 'hidden_text')

  return (
    <Modal
      open={open}
      title="숨은 명령이 발견되었습니다"
      onClose={onClose}
      actions={
        <>
          {/* 문장 하나만 지우는 API는 없다. 마스킹 사본이 숨은 명령을 이미 [숨은 명령]으로 바꿔 두므로
              사본 화면으로 보내 확인·다운로드하게 한다. */}
          <Button onClick={onRemove}>이 문장을 제거하고 사본 만들기</Button>
          <Button variant="secondary" onClick={onIgnore}>
            무시하고 진행
          </Button>
          <Button variant="ghost" onClick={onCancelFile}>
            이 파일 취소
          </Button>
        </>
      }
    >
      <div className="stack stack--tight">
        <p className="break-anywhere">
          <strong>{result.filename || '이 문서'}</strong> 안에 AI에게 내리는 지시문이 숨겨져 있습니다. 이 문서를 AI 도구에
          넣으면 AI가 이 지시를 따를 수 있습니다.
        </p>
        <ul className="finding-list">
          {commands.map((finding) => {
            // 어떻게 숨겨져 있었는지. 승격된 경우 hidden_reason_text, 다른 항목에 합쳐진 경우 hidden.reason.
            const howHidden = finding.evidence?.hidden_reason_text || finding.evidence?.hidden?.reason
            const commandText = finding.evidence?.restored || finding.text
            return (
              <li key={finding.id} className="finding-list__item">
                <div className="finding-list__head">
                  <strong>{finding.label}</strong>
                  {finding.page != null && <span className="chip">{finding.page}쪽</span>}
                </div>
                <p className="finding-list__reason">
                  {finding.reason}
                  {howHidden ? ` · ${howHidden}` : ''}
                </p>
                <p className="hidden-command__text">{commandText}</p>
              </li>
            )
          })}
        </ul>
      </div>
    </Modal>
  )
}
