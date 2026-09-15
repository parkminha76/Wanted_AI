import { useRef, useState } from 'react'
import { UPLOAD_LIMITS } from '../shared/api.js'
import { Button } from '../shared/components/index.js'
import './scanner.css'

// 스캐너가 읽는 확장자. backend/scanner/scan.py의 _FILE_TYPE_BY_EXTENSION(= parse.py의 표)과 같게 둔다.
const ACCEPTED_EXTENSIONS = [
  '.pdf', '.docx', '.xlsx', '.xlsm',
  '.txt', '.md', '.csv', '.log',
  '.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tif', '.tiff',
]

const BENEFITS = [
  { icon: '◉', title: '숨은 위험까지 한 번에', copy: '개인정보·민감정보·숨은 AI 명령 동시 탐지' },
  { icon: '♜', title: '원본은 바로 삭제', copy: '검사가 끝나면 서버에 남기지 않습니다' },
  { icon: '◇', title: '형식 그대로 마스킹', copy: 'PDF·Word·Excel 사본을 그대로 내려받기' },
]

function extensionOf(name) {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot).toLowerCase() : ''
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  const megabytes = bytes / 1024 / 1024
  return `${Number.isInteger(megabytes) ? megabytes : megabytes.toFixed(1)} MB`
}

// 첫 화면. 주 버튼(CTA)이 상태에 따라 바뀐다.
//   파일 고르기 전  "파일 선택하기"          — 업로드 영역이 크게 보인다.
//   파일 고른 뒤    "AI 보안 검사 시작"      — 업로드 영역은 "파일 추가하기" 한 줄로 줄어든다.
// 샘플 문서 체험은 파일이 없는 사람(심사위원 시연 등)을 위한 보조 버튼으로 항상 아래에 둔다.
export default function UploadPage({ onScan, error, busy }) {
  const inputRef = useRef(null)
  const [files, setFiles] = useState([])
  const [dragging, setDragging] = useState(false)
  const [problems, setProblems] = useState([])
  const hasFiles = files.length > 0

  function openPicker() {
    if (!busy) inputRef.current?.click()
  }

  function addFiles(fileList) {
    const next = [...files]
    const found = []
    for (const file of Array.from(fileList)) {
      if (!ACCEPTED_EXTENSIONS.includes(extensionOf(file.name))) {
        found.push(`${file.name}: 지원하지 않는 형식입니다.`)
        continue
      }
      if (file.size > UPLOAD_LIMITS.maxFileBytes) {
        found.push(`${file.name}: 파일당 ${formatBytes(UPLOAD_LIMITS.maxFileBytes)}까지 올릴 수 있습니다.`)
        continue
      }
      if (next.some((picked) => picked.name === file.name && picked.size === file.size)) continue
      if (next.length >= UPLOAD_LIMITS.maxFiles) {
        found.push(`한 번에 ${UPLOAD_LIMITS.maxFiles}개까지 올릴 수 있습니다.`)
        break
      }
      next.push(file)
    }
    setFiles(next)
    setProblems(found)
  }

  const messages = [...problems, ...(error ? [error] : [])]

  return (
    <div className="container upload-page">
      <section className="hero">
        <div>
          <p className="eyebrow">AI DOCUMENT SECURITY</p>
          <h1 className="hero__title">
            문서 속
            <br />
            보이지 않는 위험까지
            <br />
            <em>AI</em>가 검사합니다.
          </h1>
          <p className="hero__desc">
            개인정보, 계좌·API 키 같은 민감정보, 문서에 숨겨진 AI 명령어까지 보내기 전에 찾아서 가려 드립니다.
          </p>
        </div>
        <div className="scan-art" aria-hidden="true">
          <div className="scan-art__doc">
            <b>DOCX</b>
            <i />
            <i />
            <i />
          </div>
          <div className="scan-art__line" />
          <ul className="scan-art__float">
            <li>개인정보 탐지</li>
            <li>민감정보 분석</li>
            <li>숨은 명령 탐지</li>
            <li>위험도 평가</li>
          </ul>
        </div>
      </section>

      <section className="dropzone-card" aria-label="문서 업로드">
        {/* 파일 선택 창은 버튼으로 연다. 영역 빈 곳을 눌러도 열리지만 키보드 사용자는 버튼을 쓴다. */}
        <div
          className={`dropzone${hasFiles ? ' dropzone--compact' : ''}${dragging ? ' is-dragging' : ''}`}
          onClick={(event) => {
            if (!event.target.closest('button')) openPicker()
          }}
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            if (!busy) addFiles(event.dataTransfer.files)
          }}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS.join(',')}
            className="visually-hidden"
            tabIndex={-1}
            aria-hidden="true"
            disabled={busy}
            onChange={(event) => {
              addFiles(event.target.files)
              event.target.value = '' // 같은 파일을 빼고 다시 고를 수 있게
            }}
          />

          {hasFiles ? (
            <>
              <p className="dropzone__compact-text">파일을 더 올리려면 이곳에 드롭하거나</p>
              <Button variant="secondary" size="sm" disabled={busy} onClick={openPicker}>
                파일 추가하기
              </Button>
            </>
          ) : (
            <>
              <span className="dropzone__icon" aria-hidden="true">
                ⌑
              </span>
              <h2 className="dropzone__title">문서를 업로드하세요</h2>
              <p className="dropzone__hint">
                PDF · Word · Excel · 텍스트 · 이미지 (최대 {UPLOAD_LIMITS.maxFiles}개, 파일당{' '}
                {formatBytes(UPLOAD_LIMITS.maxFileBytes)})
              </p>
              <Button size="lg" disabled={busy} onClick={openPicker}>
                파일 선택하기
              </Button>
              <p className="dropzone__drop">또는 파일을 이곳에 드롭</p>
            </>
          )}
        </div>

        {messages.length > 0 && (
          <p className="alert alert--error" role="alert">
            {messages.map((message) => (
              <span key={message} className="alert__line">
                {message}
              </span>
            ))}
          </p>
        )}

        {hasFiles && (
          <>
            <ul className="file-list" aria-label="선택한 파일">
              {files.map((file) => (
                <li key={`${file.name}-${file.size}`} className="file-list__item">
                  <span className="file-list__icon" aria-hidden="true">
                    ⌑
                  </span>
                  <span className="file-list__info">
                    <span className="file-list__name">{file.name}</span>
                    <span className="file-list__size">{formatBytes(file.size)}</span>
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    aria-label={`${file.name} 빼기`}
                    onClick={() => setFiles((prev) => prev.filter((picked) => picked !== file))}
                  >
                    빼기
                  </Button>
                </li>
              ))}
            </ul>
            <Button size="lg" block disabled={busy} onClick={() => onScan('files', files)}>
              AI 보안 검사 시작{files.length > 1 ? ` (${files.length}개)` : ''} →
            </Button>
          </>
        )}

        <p className="dropzone-card__note">
          올린 원본은 검사가 끝나면 서버에서 바로 삭제되고, 가린 사본은 30분 동안만 내려받을 수 있습니다.
        </p>

        <div className="sample-cta">
          <p className="sample-cta__text">문서가 없어도 바로 체험해 보세요</p>
          <Button variant="ghost" disabled={busy} onClick={() => onScan('samples')}>
            샘플 문서로 검사해보기 →
          </Button>
        </div>
      </section>

      <ul className="benefits">
        {BENEFITS.map((benefit) => (
          <li key={benefit.title} className="benefit">
            <span className="benefit__icon" aria-hidden="true">
              {benefit.icon}
            </span>
            <span>
              <b>{benefit.title}</b>
              <small>{benefit.copy}</small>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
