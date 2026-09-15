import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 백엔드는 CORS를 열어 두었으므로(backend/main.py) 프록시 없이 VITE_API_BASE_URL로 직접 부른다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
})
