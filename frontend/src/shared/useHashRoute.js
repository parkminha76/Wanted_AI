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

  const navigate = (to) => {
    window.location.hash = `/${to}`
    window.scrollTo(0, 0)
  }

  return [route, navigate]
}
