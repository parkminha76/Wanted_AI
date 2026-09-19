import { useRef, useState } from 'react'
import { api } from '../shared/api.js'
import { Button, RiskBadge } from '../shared/components/index.js'
import EmptyResult from './EmptyResult.jsx'
import MaskExample from './MaskExample.jsx'
import './scanner.css'

// 사본 받는 화면. 답하는 순서가 화면 순서다.
//   ① 어떤 파일을 어떤 방식으로 받을지 — 목록 하나에서 전부 고른다
//   ② 두 방식이 어떻게 다른지         — 고정 예시
//
// 드롭다운으로 파일을 하나씩 넘기던 때는 "내가 뭘 골랐더라"에 화면이 답하지 못해서 안내 문구를
// 따로 붙여야 했다. 목록으로 펼치면 그 문구가 필요 없다.
//
// 부분 마스킹은 탐지된 항목 전부에 표준 규칙(010-****)을 적용한다. 항목을 하나씩 고르는 단계는
// 두지 않는다 — 파일이 10개면 고르는 일만 열 번이 된다.

// 사본은 방식을 바꿀 때마다 만들지 않는다. 받기를 누를 때 필요한 것만 만든다 — 고르는 동안
// 만들면 쓰지도 않을 사본이 서버에 쌓이고, 먼저 만든 것부터 30분 TTL이 돌기 시작한다.
function needsCopy(row) {
  return row.mode === 'partial' && !row.partialFileId
}

export default function MaskPage({
  batch,
  file,
  navigate,
  uploads = [],
  batchSource = null,
  onRetryExpired,
}) {
  // { [file_id]: { mode: 'full' | 'partial', checked, partialFileId } }
  const [picks, setPicks] = useState({})
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  // 사본은 검사 후 30분이 지나면 서버에서 지워진다(main.py MASKED_FILE_TTL_SECONDS).
  const [expired, setExpired] = useState(false)
  // 받기는 한 번에 하나만 돈다. busy(상태)로 막으면 React가 다시 그리기 전에 두 번째 클릭이
  // 들어와서, 사본을 두 번 만들고 화면이 가리키는 id와 서버가 아는 id가 어긋난다.
  const running = useRef(false)

  if (!batch || !file) return <EmptyResult navigate={navigate} />

  // 원본 형식 사본을 못 만든 파일은 받을 것이 없으므로 목록에서 뺀다.
  const rows = batch.results
    .filter((result) => result.file_id)
    .map((result) => ({
      result,
      id: result.file_id,
      mode: picks[result.file_id]?.mode ?? 'full',
      checked: picks[result.file_id]?.checked ?? true,
      partialFileId: picks[result.file_id]?.partialFileId ?? null,
      // 부분 마스킹 사본은 원본을 서버에 한 번 더 보내야 만들 수 있다(서버는 원본을 안 남긴다).
      // 샘플 문서는 브라우저에 File이 없어 서버에 있는 샘플을 이름으로 지정한다.
      source: uploads.find((upload) => upload.name === result.filename) ?? null,
    }))
    .map((row) => ({ ...row, canPartial: Boolean(row.source) || batchSource === 'samples' }))

  const update = (id, patch) => {
    setPicks((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }))
    setError('')
  }

  const picked = rows.filter((row) => row.checked)
  const skipped = batch.results.length - rows.length
  const blocked = picked.filter((row) => row.mode === 'partial' && !row.canPartial)
  const allBlocked = rows.filter((row) => row.mode === 'partial' && !row.canPartial)
  // 머리 칸 체크는 "하나라도 골랐나"다. 누르면 고른 게 있을 때는 전부 끄고, 없을 때는 전부 켠다.
  const anyPicked = picked.length > 0

  const toggleAll = () =>
    setPicks((prev) =>
      Object.fromEntries(rows.map((row) => [row.id, { ...prev[row.id], checked: !anyPicked }])),
    )

  // 응답을 확인하려고 같은 URL을 두 번 호출하면 안 된다. /download/all은 요청마다 임시 zip을
  // 만들고 응답 뒤 지우며, 배포 환경에서는 두 요청이 서로 다른 인스턴스로 갈 수도 있다.
  // 한 번 받은 응답을 Blob URL로 바꿔 그대로 저장한다.
  async function downloadCopy(url, fallbackName) {
    try {
      const response = await fetch(url)
      if (response.status === 404) {
        setExpired(true)
        return false
      }
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        throw new Error(
          typeof data?.detail === 'string' ? data.detail : `다운로드에 실패했습니다. (${response.status})`,
        )
      }

      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const disposition = response.headers.get('content-disposition') || ''
      const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
      const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1]
      let filename = fallbackName
      try {
        filename = encodedName ? decodeURIComponent(encodedName) : plainName || fallbackName
      } catch {
        filename = fallbackName
      }

      const anchor = document.createElement('a')
      anchor.href = objectUrl
      anchor.download = filename
      anchor.rel = 'noopener'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      // Chrome은 클릭 이벤트가 끝난 뒤 실제 파일 저장을 시작할 수 있다. 즉시 revoke하면
      // 저장이 시작되기 전에 Blob URL이 사라져 버튼을 눌러도 아무 반응이 없는 경우가 있다.
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60000)
      return true
    } catch (err) {
      setError(err.message || '파일을 다운로드하지 못했습니다. 잠시 후 다시 시도해 주세요.')
      return false
    }
  }

  // 부분 마스킹 사본을 만든다. replaces로 어느 사본을 대신하는지 알려 주면, 서버가 새 사본을
  // 같은 배치의 것으로 표시한다 — .zip이 "이 배치의 사본만 묶는다"를 지키면서도 이걸 받아들인다.
  async function buildCopy(row) {
    const selections = row.result.findings.map((finding) => ({
      id: finding.id,
      type: finding.type,
      start: finding.start,
      end: finding.end,
      action: 'standard',
    }))
    const previous = row.partialFileId ?? row.id
    const made = row.source
      ? await api.maskSelected(row.source, selections, previous)
      : await api.maskSample(row.result.filename, selections, previous)
    update(row.id, { partialFileId: made.file_id })
    return made.file_id
  }

  // 받을 파일 중 부분 마스킹으로 바꾼 것의 사본을 먼저 만든다. 받을 사본의 id 목록을 돌려준다.
  // 부분 마스킹 사본은 새 id를 받으므로 원래 id를 그대로 쓰면 전체 마스킹본이 내려간다.
  async function prepare(targetRows) {
    const pending = targetRows.filter(needsCopy)
    const made = {}
    try {
      for (const [index, row] of pending.entries()) {
        setBusy(`부분 마스킹 사본 만드는 중 (${index + 1}/${pending.length}) — ${row.result.filename}`)
        made[row.id] = await buildCopy(row)
      }
    } catch (err) {
      setError(err.message)
      return null
    } finally {
      setBusy('')
    }
    return targetRows.map((row) => {
      const partial = made[row.id] ?? row.partialFileId
      return row.mode === 'partial' && partial ? partial : row.id
    })
  }

  // 받기는 한 번에 하나만. 두 번 눌러도 앞의 것이 끝날 때까지 두 번째는 그냥 버린다.
  async function once(targetRows, work) {
    if (running.current) return
    running.current = true
    setError('')
    try {
      const ids = await prepare(targetRows)
      if (ids) await work(ids)
    } finally {
      running.current = false
    }
  }

  // 체크한 파일은 각각의 원래 형식으로 받는다. ZIP 버튼과 역할을 섞지 않는다.
  const downloadSelected = () =>
    once(picked, async (ids) => {
      for (const [index, id] of ids.entries()) {
        const filename = picked[index]?.result.filename || `masked_file_${index + 1}`
        if (!(await downloadCopy(api.downloadUrl(id), `masked_${filename}`))) return
      }
    })

  // ZIP은 체크 상태와 무관하게 현재 목록 전체를 한 파일로 받는다. 각 행에서 고른
  // 전체/부분 마스킹 방식은 그대로 반영한다.
  const downloadZip = () =>
    once(rows, (ids) => downloadCopy(api.downloadAllUrl(batch.batch_id, ids), 'docxray_masked.zip'))

  const busyLabel = (
    <>
      <span className="spinner" aria-hidden="true" /> 사본 만드는 중…
    </>
  )
  const stopped = picked.length === 0 || blocked.length > 0 || Boolean(busy)
  const zipStopped = rows.length === 0 || allBlocked.length > 0 || Boolean(busy)

  return (
    <div className="container mask-page">
      <button type="button" className="back-link" onClick={() => navigate('results')}>
        ← 분석 결과로 돌아가기
      </button>
      <div className="page-head">
        <div>
          <h1 className="page-title">안전하게 마스킹된 문서</h1>
          <p className="page-desc">
            파일마다 가리는 방식을 고르고 한 번에 받으세요. 원문과 사본을 나란히 대조하려면{' '}
            <button type="button" className="text-link" onClick={() => navigate('results/detail')}>
              검사 결과 상세보기
            </button>
            로 가세요.
          </p>
        </div>
        <div className="page-head__actions">
          <Button disabled={expired || stopped} onClick={downloadSelected}>
            {busy ? busyLabel : `↓ 선택 파일 다운받기${picked.length > 1 ? ` (${picked.length}개)` : ''}`}
          </Button>
          <Button variant="secondary" disabled={expired || zipStopped} onClick={downloadZip}>
            전체 파일 ZIP 받기
          </Button>
          {expired && (
            <Button onClick={onRetryExpired ?? (() => navigate('', { replace: true }))}>
              ↻ 사본 다시 만들기
            </Button>
          )}
        </div>
      </div>

      {expired && (
        <p className="alert alert--error" role="alert">
          서버가 업데이트되었거나 사본 보관 시간이 지났습니다. 선택 내용은 그대로 두었습니다. 위의
          사본 다시 만들기를 눌러 새 사본을 만들어 주세요.
        </p>
      )}
      {busy && (
        <p className="alert alert--info" role="status">
          {busy}
        </p>
      )}
      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
      {blocked.length > 0 && (
        <p className="alert alert--info">
          {blocked.map((row) => row.result.filename).join(' · ')}: 올린 원본이 브라우저에 없어 부분 마스킹
          사본을 만들 수 없습니다. 전체 마스킹으로 받거나 파일을 다시 올려 주세요.
        </p>
      )}

      <div className="mask-picks__caption">받을 파일과 가리는 방식을 고르세요.</div>

      <table className="mask-picks" aria-label="받을 파일과 가리는 방식">
            <thead>
              <tr>
                <th scope="col">
                  {/* 머리 칸 체크박스가 전체 선택·해제다. 글자는 없다 — 아래 칸이 전부 체크박스라
                      무엇을 켜고 끄는 자리인지는 모양으로 이미 읽힌다. 읽어주는 이름만 남긴다. */}
                  <input
                    type="checkbox"
                    checked={anyPicked}
                    aria-label={anyPicked ? '전체 해제' : '전체 선택'}
                    onChange={toggleAll}
                  />
                </th>
                <th scope="col">파일</th>
                <th scope="col">전체 마스킹</th>
                <th scope="col">부분 마스킹</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className={row.checked ? undefined : 'is-off'}>
                  <td>
                    <input
                      type="checkbox"
                      checked={row.checked}
                      aria-label={`${row.result.filename} 받기`}
                      onChange={() => update(row.id, { checked: !row.checked })}
                    />
                  </td>
                  <td>
                    <span className="mask-picks__name">{row.result.filename || '텍스트'}</span>
                    <RiskBadge level={row.result.level} score={row.result.risk_score} />
                  </td>
                  {['full', 'partial'].map((mode) => (
                    <td key={mode}>
                      <input
                        type="radio"
                        name={`mode-${row.id}`}
                        checked={row.mode === mode}
                        disabled={mode === 'partial' && !row.canPartial}
                        aria-label={`${row.result.filename} ${mode === 'full' ? '전체' : '부분'} 마스킹`}
                        onChange={() => update(row.id, { mode })}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
      </table>

      {skipped > 0 && (
        <p className="mask-summary__note">{skipped}개는 원본 형식의 사본을 만들지 못해 목록에서 뺐습니다.</p>
      )}

      <MaskExample />

      <p className="mask-summary__note">
        원본은 서버에서 이미 삭제되었습니다. 사본은 검사 후 30분 동안만 받을 수 있습니다.
      </p>
    </div>
  )
}
