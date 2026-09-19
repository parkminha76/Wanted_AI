import { useEffect, useState } from 'react'

// 라우터 라이브러리 없이 # 뒤 주소로 화면을 바꾼다. 브라우저 뒤로가기가 그대로 동작하고,
// 정적 호스팅에서도 새로고침 시 404가 나지 않는다.
function readHash() {
  return window.location.hash.replace(/^#\/?/, '')
}

export function useHashRoute() {
  const [route, setRoute] = useState(readHash)

  useEffect(() => {
    const onHashChange = () => setRoute(readHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  // replace: true — 지금 히스토리 항목을 덮어쓴다(새로 쌓지 않는다). 검사 중처럼 잠깐 지나가는
  // 화면을 이 값으로 다음 화면(결과/에러 복귀)으로 넘기면, 그 지나가는 화면이 뒤로가기 스택에
  // 안 남는다 — 안 그러면 결과 화면에서 뒤로 가면 "검사 중"의 끝난 상태(빈 화면)로 떨어진다.
  const navigate = (to, { replace = false } = {}) => {
    if (replace) {
      const { pathname, search } = window.location
      window.history.replaceState(null, '', `${pathname}${search}#/${to}`)
      setRoute(readHash())
    } else {
      window.location.hash = `/${to}`
    }
    window.scrollTo(0, 0)
  }

  return [route, navigate]
}
