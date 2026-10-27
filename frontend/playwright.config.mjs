import { defineConfig } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const temporary = fileURLToPath(new URL('../cache/playwright-tmp', import.meta.url))
mkdirSync(temporary, { recursive: true })
process.env.TEMP = temporary
process.env.TMP = temporary

const output = `../results/browser-dropdowns/${process.env.DROPDOWN_RUN ?? 'latest'}`

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 60000,
  globalTimeout: 120000,
  outputDir: `${output}/artifacts`,
  reporter: [['list'], ['json', { outputFile: `${output}/report.json` }]],
  use: {
    baseURL: process.env.DROPDOWN_BASE_URL ?? 'http://127.0.0.1:5187',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    { name: 'chrome', use: { channel: 'chrome' } },
    { name: 'edge', use: { channel: 'msedge' } },
  ],
  globalSetup: './e2e/server.mjs',
})
