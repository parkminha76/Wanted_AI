// 화면 맨 위에 붙는 작은 알약 태그. 앞의 점이 깜빡여서 "지금 살아 있는 화면"처럼 보이게 한다.
// 첫 화면·훈련 모드·이용 가이드가 같은 모양을 쓴다. 움직임 줄이기 설정이면 점은 켜진 채 멈춘다(components.css).
export default function Badge({ children }) {
  return (
    <p className="badge">
      <span className="badge__dot" aria-hidden="true" />
      {children}
    </p>
  )
}
