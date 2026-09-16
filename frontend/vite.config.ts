import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    // 0.0.0.0 so an iPad on the same LAN can reach the dev server.
    host: true,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: { outDir: 'dist' },
})
