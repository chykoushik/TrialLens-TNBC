import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [react()],
  envDir: false,
  cacheDir: '../cache/vite',
  server: {
    fs: { allow: ['.', '../cache/vite', '../results/benchmark', '../results/prioritization'].map(path => fileURLToPath(new URL(path, import.meta.url))) },
    proxy: { '/api': { target: process.env.TRIALLENS_API_TARGET ?? 'http://127.0.0.1:8000', rewrite: path => path.replace(/^\/api/, '') } },
  },
  test: { include: ['src/**/*.test.{ts,tsx}'], environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], cache: false },
})
