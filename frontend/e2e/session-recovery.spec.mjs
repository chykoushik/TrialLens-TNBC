import { test, expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { fileURLToPath } from 'node:url'
import { once } from 'node:events'

test.skip(!process.env.DROPDOWN_BACKEND, 'Requires the real local offline backend')

let owned
test.afterEach(async () => { if (owned && owned.exitCode === null) { const exited = once(owned, 'exit'); owned.kill(); await exited } })

async function startBackend(port) {
  const root = fileURLToPath(new URL('../../', import.meta.url))
  owned = spawn(`${root}/.venv/Scripts/python.exe`, ['-B', '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: root, windowsHide: true, stdio: 'ignore', env: { ...process.env, NEBIUS_LIVE_EXTRACTION: '0' },
  })
  await expect.poll(async () => {
    if (owned.exitCode !== null) throw new Error('Local test backend exited')
    try { return (await fetch(`http://127.0.0.1:${port}/health`)).ok } catch { return false }
  }, { timeout: 15000 }).toBe(true)
}

async function choose(page, value) {
  const select = page.getByRole('combobox', { name: 'Fictional report outcome', exact: true })
  await expect(select).toBeVisible()
  const values = await select.locator('option').evaluateAll(nodes => nodes.map(node => node.value))
  const index = values.indexOf(value)
  expect(index).toBeGreaterThan(0)
  await select.click()
  await expect.poll(() => select.evaluate(node => node.matches(':open'))).toBe(true)
  await page.keyboard.press('Home')
  for (let i = 0; i < index; i++) await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(select).toHaveValue(value)
}

test('headed real backend: reload and reopen replay only committed fictional outcomes; failure and reset recover', async ({ page, context }, info) => {
  expect(['127.0.0.1', 'localhost']).toContain(new URL(process.env.DROPDOWN_BACKEND).hostname)
  const reservation = createServer()
  reservation.listen(0, '127.0.0.1')
  await once(reservation, 'listening')
  const port = reservation.address().port
  await new Promise(resolve => reservation.close(resolve))
  await startBackend(port)
  const backend = `http://127.0.0.1:${port}`
  const state = { last: null, fail: false, commits: 0, restores: 0 }
  async function routes(tab) {
    await tab.route('**/api/**', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname.replace(/^\/api/, '')
      const restore = path === '/tnbc/session/restore'
      const evaluation = /^\/(tnbc|research)\/cases\/[^/]+\/evaluate$/.test(path)
      const read = request.method() === 'GET' && /^\/(health|(tnbc|research)\/cases|research\/trials)$/.test(path)
      expect(read || (request.method() === 'POST' && (restore || evaluation)), `Offline route: ${path}`).toBe(true)
      if (restore) state.restores++
      if (state.fail && restore) return route.fulfill({ status: 503, json: { detail: 'Recoverable restart simulation' } })
      const response = await route.fetch({ url: `${backend}${path}${url.search}` })
      if (evaluation && response.ok()) { state.last = await response.json(); state.commits++ }
      await route.fulfill({ response })
    })
  }
  await routes(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Try the demo', exact: true }).click()
  await page.getByText('Advanced Mode', { exact: true }).click()
  await expect.poll(() => state.last?.spent).toBe('0')
  await page.getByRole('navigation', { name: 'Demo steps' }).getByRole('button', { name: /Simulate a review/ }).click()
  await choose(page, 'brca1-pathogenic')
  const before = state.commits
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('triallens.fictional-demo.v1'))?.drafts['review-germline-report'])).toBe('brca1-pathogenic')
  expect(state.commits).toBe(before)
  await page.reload()
  await page.getByRole('button', { name: 'Try the demo', exact: true }).click()
  await page.getByText('Advanced Mode', { exact: true }).click()
  await expect(page.getByLabel('Fictional report outcome')).toHaveValue('brca1-pathogenic')
  await expect.poll(() => state.last?.spent).toBe('0')
  await page.getByRole('button', { name: 'Apply simulated review', exact: true }).click()
  await expect.poll(() => state.last?.spent).toBe('2')
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('triallens.fictional-demo.v1'))?.outcomes['review-germline-report'])).toBe('brca1-pathogenic')
  await page.reload()
  await page.getByRole('button', { name: 'Try the demo', exact: true }).click()
  await page.getByText('Advanced Mode', { exact: true }).click()
  await expect(page.getByText('1 hypothetical reviews applied', { exact: true })).toBeVisible()
  await choose(page, 'cps-15')
  await page.getByRole('button', { name: 'Apply simulated review', exact: true }).click()
  await expect.poll(() => state.last?.spent).toBe('3')
  expect(state.last.remaining_budget).toBe('0')
  expect(state.last.assessment.uncertainty).toBe('0')
  await expect.poll(() => page.evaluate(() => Object.keys(JSON.parse(localStorage.getItem('triallens.fictional-demo.v1'))?.outcomes ?? {}).length)).toBe(2)
  state.fail = true
  await page.reload()
  await page.getByRole('button', { name: 'Retry saved demonstration' }).waitFor()
  await page.getByRole('button', { name: 'Try the demo', exact: true }).click()
  await page.getByText('Advanced Mode', { exact: true }).click()
  await expect(page.getByText('0 hypothetical reviews applied', { exact: true })).toBeVisible()
  state.fail = false
  const exited = once(owned, 'exit')
  owned.kill()
  await exited
  await startBackend(port)
  await page.getByRole('button', { name: 'Retry saved demonstration' }).click()
  await expect(page.getByText('2 hypothetical reviews applied', { exact: true })).toBeVisible()
  const reopened = await context.newPage()
  await routes(reopened)
  await page.close()
  await reopened.goto('/')
  await reopened.getByRole('button', { name: 'Try the demo', exact: true }).click()
  await reopened.getByText('Advanced Mode', { exact: true }).click()
  await expect(reopened.getByText('2 hypothetical reviews applied', { exact: true })).toBeVisible()
  await info.attach('restored-accounting', { body: JSON.stringify({ spent: state.last.spent, remaining: state.last.remaining_budget, uncertainty: state.last.assessment.uncertainty, restores: state.restores }), contentType: 'application/json' })
  await reopened.getByRole('button', { name: 'Start new demonstration', exact: true }).click()
  await expect(reopened.getByText('0 hypothetical reviews applied', { exact: true })).toBeVisible()
  await expect.poll(() => state.last?.spent).toBe('0')
})
