import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0', // 외부 접속 허용 (다른 PC에서 IP:3002 접속 가능)
    port: 3002,
    strictPort: true, // 3002 사용 중이면 실패(다음 포트로 넘어가지 않음)
    allowedHosts: true, // 모든 Host 허용 (127.0.0.1, 192.168.x.x, dlab 등)
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
      '/static': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
