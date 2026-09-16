import { useEffect } from 'react'

// 스크롤 등장 효과. .rv를 붙인 요소가 화면에 들어오면 .in을 붙인다(base.css "스크롤 등장").
//
// html.motion은 여기서만 붙인다. 움직임 줄이기 설정이거나 IntersectionObserver가 없는 브라우저면 붙이지 않아서
// .rv가 처음부터 보이는 상태로 남는다 — 스크립트가 못 돌았는데 내용이 투명한 채 멈추는 일이 없게.
//
// 화면을 바꾸거나(dependency) 결과·리포트처럼 나중에 그려지는 내용이 생겨도 새 .rv를 찾아 관찰한다(MutationObserver).
export function useScrollReveal(dependency) {
  useEffect(() => {
    const root = document.documentElement
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce || !('IntersectionObserver' in window)) {
      root.classList.remove('motion')
      return undefined
    }
    root.classList.add('motion')

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('in')
            observer.unobserve(entry.target)
          }
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.1 },
    )

    const observeAll = () => {
      document.querySelectorAll('.rv:not(.in)').forEach((element) => observer.observe(element))
    }
    observeAll()

    const mutations = new MutationObserver(observeAll)
    const appRoot = document.getElementById('root')
    if (appRoot) mutations.observe(appRoot, { childList: true, subtree: true })

    return () => {
      observer.disconnect()
      mutations.disconnect()
    }
  }, [dependency])
}
