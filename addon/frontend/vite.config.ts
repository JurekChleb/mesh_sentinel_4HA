import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Relative base: Home Assistant Ingress serves the app under a generated
// path prefix, so nothing may assume it lives at the root.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8099' },
  },
})
