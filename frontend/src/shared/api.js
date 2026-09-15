// FastAPI(backend/main.py) 호출은 전부 이 파일을 거친다. 화면 컴포넌트에서 fetch를 직접 쓰지 않는다.
//
// 사용법
//   import { api, ApiError } from '../shared/api.js'
//   try {
//     const batch = await api.scanFiles(files)
//   } catch (err) {
//     setError(err.message)   // 사용자에게 보여줄 한국어 문장이 들어 있다
//   }
//
// 서버 주소는 frontend/.env의 VITE_API_BASE_URL. 없으면 로컬 개발 서버를 쓴다.

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')

// backend/main.py의 MAX_FILES_PER_REQUEST / MAX_UPLOAD_BYTES와 같은 값이어야 한다.
// 서버도 검사하지만, 20MB를 다 올린 뒤에 거절당하지 않도록 화면에서 먼저 막는다.
export const UPLOAD_LIMITS = {
  maxFiles: 20,
  maxFileBytes: 20 * 1024 * 1024,
}

const TIMEOUT_MS = {
  default: 30_000,
  // 첫 검사는 NER 모델을 불러오느라 수십 초 걸릴 수 있다. 파일이 여러 개면 더 걸린다.
  scan: 180_000,
  // 훈련 모드는 외부 AI(Attacker/Defender) 응답을 기다린다.
  training: 90_000,
}

export class ApiError extends Error {
  constructor(message, status = 0, detail = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status   // 0이면 서버에 닿지 못한 것(네트워크·시간 초과)
    this.detail = detail   // FastAPI가 준 detail 원본
  }
}

function messageFrom(data, status) {
  const detail = data?.detail
  // 우리 서버는 HTTPException(detail="한국어 문장")으로 이유를 보낸다.
  if (typeof detail === 'string') return detail
  // 422(입력 검증 실패)는 detail이 배열이다.
  if (Array.isArray(detail)) return '입력값을 확인해 주세요.'
  return `요청을 처리하지 못했습니다. (${status})`
}

async function request(path, { method = 'GET', json, body, timeoutMs = TIMEOUT_MS.default } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  const headers = {}
  let payload = body
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(json)
  }

  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, { method, headers, body: payload, signal: controller.signal })
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new ApiError('응답이 너무 오래 걸립니다. 잠시 후 다시 시도해 주세요.')
    }
    throw new ApiError('서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인해 주세요.')
  } finally {
    clearTimeout(timer)
  }

  const data = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(messageFrom(data, response.status), response.status, data?.detail ?? null)
  }
  return data
}

export const api = {
  /** GET /health — { status, schema_version, training_mode: 'on' | 'off' } */
  health: () => request('/health'),

  /** POST /scan — 파일 여러 개. 응답 ScanBatch: { batch_id, results[], total_files, total_findings }. results는 서버가 위험도 순으로 정렬해 준다. */
  scanFiles(files) {
    const form = new FormData()
    for (const file of files) form.append('files', file) // 서버 인자 이름이 files다
    return request('/scan', { method: 'POST', body: form, timeoutMs: TIMEOUT_MS.scan })
  },

  /** POST /scan/text — 문장 하나. 응답 ScanResult(file_id 없음, masked_text 있음). */
  scanText: (text) => request('/scan/text', { method: 'POST', json: { text }, timeoutMs: TIMEOUT_MS.scan }),

  /** GET /samples — 심사위원용 샘플 검사 결과. /scan과 같은 모양이고 두 번째부터는 캐시라 빠르다. */
  samples: () => request('/samples', { timeoutMs: TIMEOUT_MS.scan }),

  /** 마스킹 사본 다운로드 주소. 링크(href)로 쓴다. 사본은 서버에서 30분 뒤 지워진다. */
  downloadUrl: (fileId) => `${BASE_URL}/download/${encodeURIComponent(fileId)}`,
  downloadAllUrl: (batchId) => `${BASE_URL}/download/all?batch_id=${encodeURIComponent(batchId)}`,

  /** POST /training/start — { training_progress_id, level, scenario_id, scenario_title, turn_no, attacker_message } */
  startTraining: ({ userId, level }) =>
    request('/training/start', { method: 'POST', json: { user_id: userId, level }, timeoutMs: TIMEOUT_MS.training }),

  /** POST /training/{id}/reply — { training_progress_id, turn_no, is_finished, attacker_message } */
  replyTraining: (trainingId, text) =>
    request(`/training/${trainingId}/reply`, { method: 'POST', json: { text }, timeoutMs: TIMEOUT_MS.training }),

  /** GET /training/{id}/report — { training_progress_id, level, score, grade, risky_actions, good_actions, improvements, summary } */
  trainingReport: (trainingId) => request(`/training/${trainingId}/report`, { timeoutMs: TIMEOUT_MS.training }),
}
