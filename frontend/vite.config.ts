import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// В режиме разработки API проксируется на backend (uvicorn на :8000)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000', changeOrigin: true } },
  },
  build: { chunkSizeWarningLimit: 2000 },
})
