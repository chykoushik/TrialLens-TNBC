import { test, expect } from '@playwright/test'

test.skip(!process.env.DROPDOWN_BACKEND, 'Requires the real local offline backend')

async function select(page, label, value) {
  const control = page.getByRole('combobox', { name: label, exact: true })
  const values = await control.locator('option').evaluateAll(nodes => nodes.map(node => node.value))
  const index = values.indexOf(value)
  expect(index).toBeGreaterThanOrEqual(0)
  const calculated = ['Algorithm', 'Fictional TNBC case'].includes(label)
    ? page.waitForResponse(response => response.url().endsWith('/evaluate') && response.status() === 200) : null
  await control.click()
  await expect.poll(() => control.evaluate(node => node.matches(':open'))).toBe(true)
  await page.keyboard.press('Home')
  for (let i = 0; i < index; i++) await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(control).toHaveValue(value)
  if (calculated) await calculated
}

async function setup(page) {
  expect(['127.0.0.1', 'localhost']).toContain(new URL(process.env.DROPDOWN_BACKEND).hostname)
  const state = { evaluations: [], last: null, failApply: false, extractions: 0 }
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api/, '')
    const body = request.method() === 'POST' ? request.postDataJSON() : null
    const evaluation = /^\/(tnbc|research)\/cases\/[^/]+\/evaluate$/.test(path)
    const mock = /^\/saved-trials\/NCT\d{8}\/extractions$/.test(path) && body?.mode === 'mock' && !body.live_approved
    const read = request.method() === 'GET' && (/^\/(health|(tnbc|research)\/cases|research\/trials)$/.test(path) || /^\/saved-trials\/NCT\d{8}$/.test(path))
    expect(read || (request.method() === 'POST' && (evaluation || mock)), `Offline allowlist: ${path}`).toBe(true)
    if (evaluation) state.evaluations.push(body)
    if (state.failApply && evaluation && Object.keys(body.outcomes).length) {
      return route.fulfill({ status: 503, json: { detail: 'Injected recoverable backend failure' } })
    }
    if (mock) state.extractions++
    const response = await route.fetch({ url: `${process.env.DROPDOWN_BACKEND}${path}${url.search}` })
    if (evaluation && response.ok()) state.last = await response.json()
    await route.fulfill({ response })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Try the demo', exact: true }).click()
  await expect.poll(() => state.last?.case_id).toBe('tnbc-record-gaps')
  return state
}

async function step(page, name) {
  if (!await page.getByRole('navigation', { name: 'Demo steps' }).isVisible()) await page.getByText('Advanced Mode', { exact: true }).click()
  await page.getByRole('navigation', { name: 'Demo steps' }).getByRole('button', { name: new RegExp(name) }).click()
}

function states(data) {
  const nodes = {}
  const visit = node => { nodes[node.criterion_id] = node.state; node.dependencies.forEach(visit) }
  data.assessment.decisions.forEach(decision => decision.assessment.assessments.forEach(visit))
  return nodes
}

test('real backend: complete budget-3 guided workflow, navigation and exact dependency chain', async ({ page }, info) => {
  const state = await setup(page)
  const baseline = structuredClone(state.last)
  expect([baseline.spent, baseline.remaining_budget, baseline.assessment.uncertainty]).toEqual(['0', '3', '2'])
  expect(baseline.plan.expected_reduction).toBe('9/5')
  await step(page, 'Explore patient evidence')
  await page.locator('.demo-observations button').filter({ hasText: 'PD-L1' }).first().click()
  await expect(page.locator('.demo-record')).toContainText('No value recorded')
  await expect(page.locator('.demo-record')).toContainText('22C3')
  await step(page, 'Understand criterion uncertainty')
  expect(states(baseline)['demo-pdl1-pdl1']).toBe('unknown')
  expect(states(baseline)['demo-brca-brca']).toBe('unknown')
  await step(page, 'Prioritize existing record reviews')
  await page.getByText('Research Details', { exact: true }).click()
  await expect(page.getByLabel('Algorithm')).toBeEnabled()
  await select(page, 'Algorithm', 'adaptive_replan')
  await expect.poll(() => state.last?.next_review).toBe('review-germline-report')
  await step(page, 'Simulate a review')
  const count = state.evaluations.length
  await select(page, 'Fictional report outcome', 'both-negative')
  await select(page, 'Fictional report outcome', 'report-unavailable')
  await select(page, 'Fictional report outcome', 'brca1-pathogenic')
  expect(state.evaluations.length).toBe(count)
  expect(state.last.patient).toEqual(baseline.patient)
  for (const destination of ['Home', 'Explore Trials', 'Research Tools', 'Try Demo']) {
    await page.getByRole('button', { name: destination, exact: true }).click()
    if (destination === 'Research Tools') await expect(page.getByLabel('Synthetic portfolio')).toBeEnabled()
  }
  await expect(page.getByLabel('Fictional report outcome')).toHaveValue('brca1-pathogenic')
  await expect(page.getByLabel('Total review budget')).toHaveValue('3')
  await page.getByRole('button', { name: 'Apply simulated review', exact: true }).click()
  await expect(page.getByText('1 hypothetical reviews applied', { exact: true })).toBeVisible()
  expect([state.last.spent, state.last.remaining_budget, state.last.assessment.uncertainty, state.last.next_review]).toEqual(['2', '1', '1', 'review-pdl1-report'])
  expect(states(state.last)['demo-brca-brca']).toBe('satisfied')
  expect(states(state.last)['demo-pdl1-pdl1']).toBe('unknown')
  const afterBrca = structuredClone(state.last)
  await select(page, 'Fictional report outcome', 'cps-15')
  await page.getByRole('button', { name: 'Apply simulated review', exact: true }).click()
  await expect(page.getByText('2 hypothetical reviews applied', { exact: true })).toBeVisible()
  expect([state.last.spent, state.last.remaining_budget, state.last.assessment.uncertainty, state.last.next_review]).toEqual(['3', '0', '0', null])
  expect(states(state.last)['demo-pdl1-pdl1']).toBe('satisfied')
  await expect(page.getByText('No further record review available', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Inspect updated evidence', exact: true }).click()
  await page.locator('.demo-observations button').filter({ hasText: 'PD-L1' }).click()
  await expect(page.locator('.demo-record')).toContainText('15 CPS')
  await expect(page.locator('.demo-record')).toContainText('22C3')
  await step(page, 'Understand criterion uncertainty')
  await expect(page.getByText(/No unresolved top-level clauses/)).toBeVisible()
  await step(page, 'Prioritize existing record reviews')
  await page.getByText('Research Details', { exact: true }).click()
  const accounting = page.getByLabel('Review budget accounting')
  await expect(accounting.locator('div').filter({ hasText: 'Already spent' }).locator('strong')).toHaveText('3')
  await expect(accounting.locator('div').filter({ hasText: 'Remaining' }).locator('strong')).toHaveText('0')
  for (const destination of ['Home', 'Explore Trials', 'Research Tools', 'Try Demo']) {
    await page.getByRole('button', { name: destination, exact: true }).click()
    if (destination === 'Research Tools') await expect(page.getByLabel('Synthetic portfolio')).toBeEnabled()
  }
  await expect(page.getByText('2 hypothetical reviews applied', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Review budget accounting')).toBeVisible()
  await expect.poll(() => state.last.assessment.uncertainty).toBe('0')
  await info.attach('actual-transitions', { body: JSON.stringify([baseline, afterBrca, state.last], null, 2), contentType: 'application/json' })
  await page.getByRole('button', { name: 'Reset hypothetical reviews', exact: true }).click()
  await expect(page.getByText('0 hypothetical reviews applied', { exact: true })).toBeVisible()
  await expect.poll(() => state.last.spent).toBe('0')
  expect(state.last.patient).toEqual(baseline.patient)
})

test('real backend: failed Apply recovery, insufficient budget, reset, case and algorithm switching', async ({ page }) => {
  const state = await setup(page)
  await step(page, 'Simulate a review')
  await select(page, 'Fictional report outcome', 'brca1-pathogenic')
  state.failApply = true
  await page.getByRole('button', { name: 'Apply simulated review', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Review not applied. Draft retained.')
  await expect(page.getByLabel('Fictional report outcome')).toHaveValue('brca1-pathogenic')
  await expect(page.getByText('0 hypothetical reviews applied', { exact: true })).toBeVisible()
  expect(state.last.spent).toBe('0')
  state.failApply = false
  await page.getByRole('button', { name: 'Apply simulated review', exact: true }).click()
  await expect(page.getByText('1 hypothetical reviews applied', { exact: true })).toBeVisible()
  await page.getByLabel('Total review budget').fill('1')
  await expect(page.getByRole('alert')).toContainText('exceeds total budget')
  await page.getByLabel('Total review budget').fill('3')
  await expect(page.getByLabel('Fictional report outcome')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(state.last.spent).toBe('2')
  await page.getByRole('button', { name: 'Reset hypothetical reviews', exact: true }).click()
  await expect.poll(() => state.last.spent).toBe('0')
  await page.getByLabel('Total review budget').fill('0')
  await expect(page.getByText('No further record review available', { exact: true })).toBeVisible()
  await page.getByLabel('Total review budget').fill('3')
  await expect(page.getByLabel('Fictional report outcome')).toBeEnabled()
  await select(page, 'Fictional TNBC case', 'tnbc-complete')
  await expect(page.getByText('No further record review available', { exact: true })).toBeVisible()
  await select(page, 'Fictional TNBC case', 'tnbc-record-gaps')
  await expect(page.getByLabel('Fictional report outcome')).toBeEnabled()
  await page.getByText('Research Details', { exact: true }).click()
  await select(page, 'Algorithm', 'joint_greedy')
  await expect(page.getByLabel('Algorithm')).toHaveValue('joint_greedy')
  await select(page, 'Algorithm', 'exact_nonadaptive')
  await expect(page.getByLabel('Algorithm')).toHaveValue('exact_nonadaptive')
  await expect(page.getByRole('button', { name: 'Apply simulated review review-germline-report', exact: true })).toBeVisible()
  expect(state.last.spent).toBe('0')
})

test('real backend: five studies, historical snapshots and blocked strict mock extraction', async ({ page }, info) => {
  const state = await setup(page)
  await page.getByRole('button', { name: 'Explore Trials', exact: true }).click()
  await page.getByText('Advanced Mode: source & extraction tools', { exact: true }).click()
  await expect(page.locator('button[data-study]')).toHaveCount(5)
  await page.getByRole('button', { name: 'Inspect extraction for NCT02648477', exact: true }).click()
  const snapshot = page.getByLabel('Snapshot history')
  await expect(snapshot.locator('option')).toHaveCount(2)
  const versions = await snapshot.locator('option').evaluateAll(nodes => nodes.map(node => node.value))
  for (const value of [versions[1], versions[0], versions[1]]) await select(page, 'Snapshot history', value)
  await expect(page.getByLabel('Extraction mode')).toHaveValue('mock')
  await page.getByRole('button', { name: /Run mock extraction/ }).click()
  const result = page.getByLabel('Extraction result')
  await expect(result).toContainText('validation_failed')
  await expect(result).toContainText('Not validated')
  await expect(page.getByText('Assessment blocked', { exact: true })).toBeVisible()
  expect(state.extractions).toBe(1)
  await info.attach('mock-validation', { body: await result.innerText(), contentType: 'text/plain' })
  await page.getByRole('button', { name: 'Try Demo', exact: true }).click()
  await expect.poll(() => state.last?.case_id).toBe('tnbc-record-gaps')
  expect(state.last.assessment.uncertainty).toBe('2')
})


