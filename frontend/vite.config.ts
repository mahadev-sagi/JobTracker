import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Inside Docker the backend is reachable as the compose service name, not as
// localhost — compose sets VITE_API_PROXY_TARGET=http://backend:8000.
const apiTarget = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
    // Bind-mounted source on Windows/Docker doesn't emit inotify events.
    watch: process.env.VITE_USE_POLLING ? { usePolling: true } : undefined,
  },
})
