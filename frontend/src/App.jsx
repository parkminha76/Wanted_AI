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
      const result = kind === 'samples' ? await api.samples() : await api.scanFiles(files)
      setBatch(result)
      // 검사가 성공했을 때만 바꾼다 — 실패했는데 바꾸면 이전 결과의 원본 File이 사라진다.
      setBatchSource(kind)
      setUploads(kind === 'files' ? files : [])
      setFileIndex(0)
      setFindingId(null)
      navigate('results')
    } catch (err) {
      setScanError(err.message)
      navigate('')
    } finally {
      setScanJob(null)
    }
  }

  // "이 파일 취소" — 화면 목록에서만 뺀다.
  // TODO: 서버 배치에는 남아 있어서 "전체 사본 받기(.zip)"에는 아직 포함된다.
  function cancelFile(target) {
    setBatch((prev) => {
      if (!prev) return prev
      const results = prev.results.filter((result) => result !== target)
      return {
        ...prev,
        results,
        total_files: results.length,
        total_findings: results.reduce((sum, result) => sum + result.findings.length, 0),
      }
    })
    setFileIndex(0)
    setFindingId(null)
  }

  const results = batch?.results ?? []
  const scanProps = {
    batch,
    file: results[fileIndex] ?? results[0] ?? null,
    fileIndex,
    onSelectFile: (index) => {
      setFileIndex(index)
      setFindingId(null)
    },
    findingId,
    onSelectFinding: setFindingId,
    navigate,
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
      page = <MaskPage {...scanProps} uploads={uploads} batchSource={batchSource} />
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
