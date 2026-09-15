import { Button, Card } from '../shared/components/index.js'

// 결과 없이 결과 화면 주소로 들어왔을 때(새로고침 등).
export default function EmptyResult({ navigate }) {
  return (
    <div className="container results-page">
      <Card title="검사 결과가 없습니다" description="결과는 브라우저에 저장하지 않아서 새로고침하면 사라집니다.">
        <Button onClick={() => navigate('')}>문서 올리러 가기</Button>
      </Card>
    </div>
  )
}
