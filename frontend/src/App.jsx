import { useState } from 'react'
import { api } from './shared/api.js'
import { AppFooter, AppHeader, ScrollTopButton } from './shared/components/index.js'
import { useHashRoute } from './shared/useHashRoute.js'
import { useScrollReveal } from './shared/useScrollReveal.js'
import UploadPage from './scanner/UploadPage.jsx'
import ScanningPage from './scanner/ScanningPage.jsx'
import ResultsPage from './scanner/ResultsPage.jsx'
import FindingDetailPage from './scanner/FindingDetailPage.jsx'
import MaskPage from './scanner/MaskPage.jsx'
import TrainingHomePage from './training/TrainingHomePage.jsx'
import SimulationPage from './training/SimulationPage.jsx'
import ReportPage from './training/ReportPage.jsx'
import GuidePage from './guide/GuidePage.jsx'

// 화면 주소(# 뒤)
//   ''                 문서 업로드
//   'scanning'         검사 중
//   'results'          분석 결과 (문서 미리보기 + 탐지 항목, 숨은 명령 팝업)
//   'results/detail'   탐지 항목 상세
//   'results/mask'     마스킹 사본 미리보기·다운로드
//   'training'         훈련 모드 소개 + 레벨 선택
//   'training/play'    Attacker AI 대화
//   'training/report'  훈련 결과 리포트
//   'guide'            이용 가이드
// 바닥글을 함께 보여줄 화면. 첫 화면('')은 UploadPage 안에서 직접 그린다.
const FOOTER_ROUTES = new Set(['training', 'guide'])

export default function App() {
  const [route, navigate] = useHashRoute()
  useScrollReveal(route)

  // 화면 사이에 넘기는 데이터는 메모리에만 둔다. 검사 결과에는 원문과 탐지 값이 들어 있어서
  // localStorage 같은 브라우저 저장소에 남기지 않는다(privacy-first). 새로고침하면 사라진다.
  const [batch, setBatch] = useState(null)
  const [fileIndex, setFileIndex] = useState(0)
  const [findingId, setFindingId] = useState(null)
  const [scanJob, setScanJob] = useState(null) // { kind: 'files' | 'samples', fileCount, startedAt }
  const [scanError, setScanError] = useState('')
  const [training, setTraining] = useState(null) // { id, level, state, turnNo, firstMessage }
  // 직접 올린 File 객체. 선택 마스킹(POST /mask)은 원본을 한 번 더 보내야 해서 메모리에만 들고 있는다.
  // 샘플 문서 검사에는 원본 File이 없으므로 빈 배열이다.
  const [uploads, setUploads] = useState([])
  // 지금 결과가 직접 올린 파일인지 샘플 문서인지. 샘플은 선택 마스킹 때 POST /samples/mask를 쓴다.
  const [batchSource, setBatchSource] = useState(null) // 'files' | 'samples'

  async function startScan(kind, files = []) {
    setScanError('')
    setScanJob({ kind, fileCount: files.length, startedAt: Date.now() })
    navigate('scanning')
    try {
      // 샘플은 files 자리에 고른 파일 이름(문자열)이 온다. 빈 배열이면 전체 샘플이다.
      const result = kind === 'samples' ? await api.samples(files) : await api.scanFiles(files)
      setBatch(result)
      // 검사가 성공했을 때만 바꾼다 — 실패했는데 바꾸면 이전 결과의 원본 File이 사라진다.
      setBatchSource(kind)
      setUploads(kind === 'files' ? files : [])
      // 서버는 위험도 내림차순으로 돌려준다. 화면 기본값은 사용자가 처음 올린 파일이다 —
      // 목록 순서는 그대로 두고 어느 것을 펴 놓을지만 바꾼다. 샘플 검사는 올린 순서가
      // 없으므로 서버 순서 첫 번째(=가장 위험한 파일)를 그대로 쓴다.
      const firstUploaded =
        kind === 'files'
          ? result.results.findIndex((r) => r.filename === files[0]?.name)
          : -1
      setFileIndex(firstUploaded < 0 ? 0 : firstUploaded)
      setFindingId(null)
      // replace — "검사 중" 화면을 뒤로가기 스택에 안 남긴다(안 그러면 결과에서 뒤로 갈 때
      // 끝나 버린 검사 중 화면으로 떨어진다).
      navigate('results', { replace: true })
    } catch (err) {
      setScanError(err.message)
      navigate('', { replace: true })
    } finally {
      setScanJob(null)
    }
  }

  // "이 파일 취소" — 화면 목록에서만 뺀다.
  // TODO: 서버 배치에는 남아 있어서 "전체 사본 받기(.zip)"에는 아직 포함된다.
  function cancelFile(target) {
    let remaining = 0
    setBatch((prev) => {
      if (!prev) return prev
      const results = prev.results.filter((result) => result !== target)
      remaining = results.length
      return {
        ...prev,
        results,
        total_files: results.length,
        total_findings: results.reduce((sum, result) => sum + result.findings.length, 0),
      }
    })
    // 마지막 남은 파일까지 취소하면 보여줄 결과가 없다 — "검사 결과가 없습니다" 안내 화면으로
    // 한 번 더 넘어가지 않고 바로 첫 화면으로 돌아간다(검사 완료 후 뒤로가기와 같은 이유).
    if (remaining === 0) navigate('', { replace: true })
    setFileIndex(0)
    setFindingId(null)
  }

  const results = batch?.results ?? []
  const scanProps = {
    batch,
    file: results[fileIndex] ?? results[0] ?? null,
    fileIndex,
    // 직접 올린 이미지 원본은 마스킹 사본 생성에도 이미 브라우저 메모리에서만 보관한다.
    // 상세 미리보기는 이 File 객체를 재사용하므로 서버에 원본을 추가 저장하지 않는다.
    sourceFile: uploads.find((uploaded) => uploaded.name === (results[fileIndex]?.filename ?? results[0]?.filename)) ?? null,
    // 합성 샘플은 서버 저장소의 원본을 미리보기로만 가져온다. 실제 업로드 원본에는 이 주소를 만들지 않는다.
    sourceUrl: batchSource === 'samples' && results[fileIndex]
      ? api.sampleOriginalUrl(results[fileIndex].filename)
      : null,
    onSelectFile: (index) => {
      setFileIndex(index)
      setFindingId(null)
    },
    findingId,
    onSelectFinding: setFindingId,
    navigate,
  }

  // 서버가 재배포·재시작되면 메모리에만 있던 다운로드 ID가 사라질 수 있다.
  // 이때 첫 화면으로만 보내면 사용자가 같은 만료 결과로 되돌아올 수 있으므로,
  // 브라우저 메모리에 남아 있는 원본(또는 샘플 이름)으로 실제 검사를 다시 수행한다.
  const retryExpiredCopies = () => {
    if (batchSource === 'files' && uploads.length > 0) {
      return startScan('files', uploads)
    }
    if (batchSource === 'samples' && batch?.results?.length > 0) {
      return startScan('samples', batch.results.map((result) => result.filename))
    }
    navigate('', { replace: true })
  }

  let page
  switch (route) {
    case 'scanning':
      page = <ScanningPage job={scanJob} navigate={navigate} />
      break
    case 'results':
      page = <ResultsPage {...scanProps} onCancelFile={cancelFile} />
      break
    case 'results/detail':
      page = <FindingDetailPage {...scanProps} />
      break
    case 'results/mask':
      page = (
        <MaskPage
          {...scanProps}
          uploads={uploads}
          batchSource={batchSource}
          onRetryExpired={retryExpiredCopies}
        />
      )
      break
    case 'training':
      page = (
        <TrainingHomePage
          onStarted={(started) => {
            setTraining(started)
            navigate('training/play')
          }}
        />
      )
      break
    case 'training/play':
      page = <SimulationPage training={training} navigate={navigate} />
      break
    case 'training/report':
      page = <ReportPage training={training} navigate={navigate} />
      break
    case 'guide':
      page = <GuidePage navigate={navigate} />
      break
    default:
      page = <UploadPage onScan={startScan} error={scanError} busy={scanJob !== null} navigate={navigate} />
  }

  return (
    <div className="app">
      <AppHeader route={route} onNavigate={navigate} />
      <main className="app-main">
        {page}
        {/* 바닥글은 훈련 모드·이용 가이드에도 똑같이 붙인다. 첫 화면은 UploadPage가 직접 들고 있고,
            검사 중·결과 화면처럼 작업 흐름 한가운데인 화면에는 붙이지 않는다. */}
        {FOOTER_ROUTES.has(route) && (
          <AppFooter navigate={navigate} onScan={startScan} busy={scanJob !== null} standalone />
        )}
      </main>
      <ScrollTopButton key={route} />
    </div>
  )
}
