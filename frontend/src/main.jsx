import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'

// 순서가 중요하다: 토큰 -> 기본 스타일 -> 공통 컴포넌트. 화면별 CSS는 각 화면 파일이 import한다.
import './shared/styles/tokens.css'
import './shared/styles/base.css'
import './shared/components/components.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
