import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

const fixture = JSON.parse(readFileSync(new URL('../src/fixtures/tnbc_demo.json', import.meta.url), 'utf8'))
const catalog = ['scenario-a', 'scenario-b', 'scenario-c'].map(case_id => ({ case_id, trial_count: 2, review_count: 2, budgets: ['3'], unsupported: null }))
const studies = ['RECRUITING', 'COMPLETED', 'NOT_YET_RECRUITING'].map((status, index) => ({
  nct_id: `NCT0000000${index + 1}`, title: `Software browser fixture ${index + 1}`, recruitment_status: status,
  conditions: ['Synthetic source fixture'], snapshot: 'latest/response.json', snapshot_count: 3,
  retrieved_at: '2026-10-23T12:00:00Z', is_synthetic: true,
}))
const versions = ['latest', 'older', 'oldest']
const fixturePages = new WeakSet()

test.beforeEach(async ({ browser, page }, info) => {
  await info.attach('browser-environment', { body: JSON.stringify({ version: browser.version(), userAgent: await page.evaluate(() => navigator.userAgent) }), contentType: 'application/json' })
})

test.afterEach(async ({ page }, info) => {
  if (info.status === info.expectedStatus || page.isClosed()) return
  await info.attach('all-selector-diagnostics', { body: JSON.stringify(await page.locator('select').evaluateAll(nodes => nodes.map(node => {
    const box = node.getBoundingClientRect()
    return { labels: [...node.labels].map(label => label.textContent), value: node.value, disabled: node.disabled, open: node.matches(':open'), inert: !!node.closest('[inert]'), pointerEvents: getComputedStyle(node).pointerEvents, hit: document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)?.outerHTML }
  })), null, 2), contentType: 'application/json' })
  await page.keyboard.press('Escape')
})

async function mockApi(page) {
  fixturePages.add(page)
  const state = { failCatalog: false, failSnapshot: false, failCalculation: false, posts: [] }
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    let data
    if (url.pathname === '/api/health') data = { status: 'ok' }
    else if (url.pathname === '/api/research/trials') data = { trials: studies, warnings: [] }
    else if (url.pathname.endsWith('/cases')) {
      if (state.failCatalog) return route.fulfill({ status: 503, json: { detail: 'Software fixture catalog failure' } })
      data = url.pathname.includes('/tnbc/') ? fixture.catalog : catalog
    } else if (url.pathname.endsWith('/evaluate')) {
      const body = request.postDataJSON()
      state.posts.push(body)
      if (state.failCalculation) return route.fulfill({ status: 409, json: { detail: 'Software fixture calculation failure' } })
      const reviewed = Boolean(body.outcomes['review-pdl1-report'])
      data = structuredClone(reviewed ? fixture.reviewed : fixture.baseline)
      data.remaining_budget = String(Number(body.budget) - Number(data.spent))
      data.next_review = body.algorithm.includes('adaptive') ? reviewed ? 'review-germline-report' : 'review-pdl1-report' : null
      data.plan.steps = [0, 1, 2].map(() => ({ selected: null, ranking: [] }))
    } else if (url.pathname.includes('/saved-trials/') && request.method() === 'GET') {
      const nctId = url.pathname.split('/').at(-1)
      const snapshot = url.searchParams.get('snapshot')
      if (state.failSnapshot && snapshot.includes('older/')) return route.fulfill({ status: 500, json: { detail: 'Software fixture snapshot failure' } })
      data = {
        source: { nct_id: nctId, text: 'Inclusion Criteria:\nSoftware fixture source only.', source_url: `https://clinicaltrials.gov/study/${nctId}`, source_snapshot: `data/raw/trials/${snapshot}`, retrieval_timestamp: '2026-10-23T12:00:00Z', sha256: 'a'.repeat(64), is_synthetic: true },
        snapshots: versions.map(version => ({ ...studies[0], nct_id: nctId, snapshot: `${version}/response.json` })),
        warnings: [], mock_version: 'verbatim-sections-v1', configuration: { ready: true, model: 'software-browser-fixture', errors: [] },
      }
    } else return route.fulfill({ status: 403, json: { detail: 'Browser test blocks this endpoint' } })
    await route.fulfill({ json: data })
  })
  return state
}

async function choose(page, label, value, testInfo, lockedAfter = false) {
  const select = page.getByRole('combobox', { name: label, exact: true })
  await expect(select).toBeEnabled()
  const options = await select.locator('option').evaluateAll(nodes => nodes.map(node => ({ value: node.value, disabled: node.disabled })))
  const index = options.findIndex(option => option.value === value)
  expect(index, `${label}: requested option exists`).toBeGreaterThanOrEqual(0)
  expect(options[index].disabled).toBe(false)
  await select.click()
  try {
    await expect.poll(() => select.evaluate(node => node.matches(':open')), { message: `${label}: native popup reopened` }).toBe(true)
    await page.keyboard.press('Home')
    for (let position = 0; position < index; position++) {
      if (!options[position + 1].disabled) await page.keyboard.press('ArrowDown')
    }
    await page.keyboard.press('Enter')
    await expect(select).toHaveValue(value)
    if (lockedAfter) {
      await page.getByRole('button', { name: `Apply simulated review ${label.replace('Simulated report for ', '')}`, exact: true }).click()
      await expect(select).toBeDisabled()
    }
    else await expect(select).toBeEnabled()
  } catch (error) {
    await testInfo.attach('selector-diagnostics', { body: JSON.stringify(await select.evaluate(node => {
      const box = node.getBoundingClientRect()
      const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
      return { value: node.value, disabled: node.disabled, open: node.matches(':open'), inert: !!node.closest('[inert]'), focused: node === document.activeElement, pointerEvents: getComputedStyle(node).pointerEvents, hit: hit?.outerHTML, select: node.outerHTML }
    }), null, 2), contentType: 'application/json' })
    await page.keyboard.press('Escape')
    throw error
  }
}


async function openView(page, name) {
  if (name === 'Trial explorer') {
    if (fixturePages.has(page)) {
      await page.getByRole('button', { name: 'Research Tools', exact: true }).click()
      await page.getByRole('button', { name: 'Source fixtures', exact: true }).click()
    } else { await page.getByRole('button', { name: 'Explore Trials', exact: true }).click(); await page.getByText('Advanced Mode: source & extraction tools', { exact: true }).click() }
    return
  }
  if (await page.getByRole('heading', { name: 'Try Demo', exact: true }).count()) {
    if (!await page.getByRole('navigation', { name: 'Demo steps' }).isVisible()) await page.getByText('Advanced Mode', { exact: true }).click()
    const names = { 'Patient evidence': 'Explore patient evidence', 'Criterion assessments': 'Understand criterion uncertainty', 'Evidence prioritization': 'Prioritize existing record reviews' }
    await page.getByRole('navigation', { name: 'Demo steps' }).getByRole('button', { name: new RegExp(names[name]) }).click()
    const details = page.getByText('Research Details', { exact: true }).locator('..')
    if (!await details.evaluate(node => node.open)) await details.locator('summary').first().click()
  } else await page.getByRole('button', { name, exact: true }).click()
}

async function cycle(page, label, values, info) {
  for (const value of values) await choose(page, label, value, info)
}

test('native popups reopen across all five workspaces', async ({ page }, info) => {
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Research Tools', exact: true }).click()
  await expect(page.getByLabel('Synthetic portfolio')).toBeEnabled()
  await cycle(page, 'Synthetic portfolio', ['scenario-b', 'scenario-c', 'scenario-b', 'scenario-a'], info)
  await cycle(page, 'Application mode', ['tnbc', 'research', 'tnbc'], info)
  await cycle(page, 'Fictional TNBC case', ['tnbc-record-gaps', 'tnbc-stale-labs', 'tnbc-record-gaps'], info)
  await openView(page, 'Patient evidence')
  await cycle(page, 'Evidence category', ['Laboratory', 'Biomarkers', 'Laboratory', 'All categories'], info)
  await cycle(page, 'Evidence availability / limitation', ['Missing', 'Observed', 'Missing', 'All evidence'], info)
  await openView(page, 'Criterion assessments')
  await cycle(page, 'Assessment state', ['unknown', 'violated', 'unknown', 'All states'], info)
  await cycle(page, 'Criterion type', ['exclusion', 'inclusion', 'exclusion', 'All types'], info)
  await cycle(page, 'Fictional protocol', ['demo-pdl1', 'demo-brca', 'demo-pdl1', 'All protocols'], info)
  await openView(page, 'Evidence prioritization')
  await cycle(page, 'Algorithm', ['joint_greedy', 'adaptive_replan', 'joint_greedy', 'exact_nonadaptive'], info)
  await page.getByText('Backend ranking and selection trace', { exact: true }).click()
  await cycle(page, 'Forecast selection step', ['1', '2', '1', '0'], info)
  await openView(page, 'Trial explorer')
  await cycle(page, 'Registry status', ['RECRUITING', 'COMPLETED', 'RECRUITING', ''], info)
  for (const id of ['NCT00000001', 'NCT00000002', 'NCT00000001']) {
    await page.getByRole('button', { name: `Inspect extraction for ${id}`, exact: true }).click()
    await expect(page.getByLabel('Extraction mode')).toBeVisible()
    await page.getByRole('button', { name: 'Change study', exact: true }).click()
  }
  await page.getByRole('button', { name: 'Return to inspection', exact: true }).click()
  await cycle(page, 'Snapshot history', ['older/response.json', 'oldest/response.json', 'older/response.json', 'latest/response.json'], info)
  await cycle(page, 'Extraction mode', ['live', 'mock', 'live', 'mock'], info)
  await page.screenshot({ path: info.outputPath('all-pages.png'), fullPage: true })
})

test('native popups with actual local backend data and no extraction requests', async ({ page }, info) => {
  test.skip(!process.env.DROPDOWN_BACKEND, 'Set DROPDOWN_BACKEND to the local backend URL')
  const backend = new URL(process.env.DROPDOWN_BACKEND)
  expect(['127.0.0.1', 'localhost']).toContain(backend.hostname)
  const forbidden = []
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api/, '')
    const allowed = request.method() === 'GET' && (/^\/(health|research\/cases|tnbc\/cases|research\/trials)$/.test(path) || /^\/saved-trials\/NCT\d{8}$/.test(path))
      || request.method() === 'POST' && /^\/(research|tnbc)\/cases\/[^/]+\/evaluate$/.test(path)
    if (!allowed) { forbidden.push(path); return route.fulfill({ status: 403, json: { detail: 'Extraction blocked by browser test' } }) }
    await route.fulfill({ response: await route.fetch({ url: `${backend.origin}${path}${url.search}` }) })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Research Tools', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Synthetic portfolio', exact: true })).toBeEnabled()
  const scenarios = await page.getByRole('combobox', { name: 'Synthetic portfolio', exact: true }).locator('option').evaluateAll(nodes => nodes.map(node => node.value))
  await cycle(page, 'Synthetic portfolio', [scenarios[1], scenarios[2], scenarios[1], scenarios[0]], info)
  await cycle(page, 'Application mode', ['tnbc', 'research', 'tnbc'], info)
  await cycle(page, 'Fictional TNBC case', ['tnbc-record-gaps', 'tnbc-stale-labs', 'tnbc-record-gaps'], info)
  await openView(page, 'Patient evidence')
  await cycle(page, 'Evidence category', ['Biomarkers', 'Laboratory', 'Biomarkers', 'All categories'], info)
  await cycle(page, 'Evidence availability / limitation', ['Missing', 'Observed', 'Missing', 'All evidence'], info)
  await openView(page, 'Criterion assessments')
  await cycle(page, 'Assessment state', ['unknown', 'violated', 'unknown', 'All states'], info)
  await cycle(page, 'Criterion type', ['exclusion', 'inclusion', 'exclusion', 'All types'], info)
  await cycle(page, 'Fictional protocol', ['demo-pdl1', 'demo-brca', 'demo-pdl1', 'All protocols'], info)
  await openView(page, 'Evidence prioritization')
  await page.getByLabel('Total review budget').fill('3')
  await cycle(page, 'Algorithm', ['joint_greedy', 'adaptive_replan', 'exact_nonadaptive', 'adaptive_replan'], info)
  await choose(page, 'Simulated report for review-pdl1-report', 'cps-15', info, true)
  await page.getByRole('button', { name: 'Reset hypothetical reviews', exact: true }).click()
  await expect(page.getByLabel('Simulated report for review-pdl1-report')).toBeEnabled()
  await cycle(page, 'Algorithm', ['exact_nonadaptive', 'joint_greedy', 'exact_nonadaptive'], info)
  await openView(page, 'Trial explorer')
  await expect(page.getByRole('combobox', { name: 'Registry status', exact: true })).toBeEnabled()
  const statuses = await page.getByRole('combobox', { name: 'Registry status', exact: true }).locator('option').evaluateAll(nodes => nodes.map(node => node.value))
  await cycle(page, 'Registry status', [statuses[1], statuses.at(-1), statuses[1], ''], info)
  const study = page.getByRole('button', { name: /Inspect extraction for NCT/ }).first()
  await study.click()
  await expect(page.getByLabel('Extraction mode')).toBeVisible()
  const snapshots = await page.getByRole('combobox', { name: 'Snapshot history', exact: true }).locator('option').evaluateAll(nodes => nodes.map(node => node.value))
  expect(snapshots.length).toBeGreaterThan(1)
  await cycle(page, 'Snapshot history', [snapshots[1], snapshots[0], snapshots[1], snapshots[0]], info)
  await cycle(page, 'Extraction mode', ['mock', 'mock', 'mock'], info)
  expect(forbidden).toEqual([])
  await page.screenshot({ path: info.outputPath('actual-backend.png'), fullPage: true })
})

test('native popups reopen after simulation, reset, navigation and recoverable errors', async ({ page }, info) => {
  const state = await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Research Tools', exact: true }).click()
  await openView(page, 'Evidence prioritization')
  await page.getByLabel('Total review budget').fill('3')
  await choose(page, 'Simulated report for review-pdl1-report', 'cps-15', info, true)
  await expect(page.getByLabel('Simulated report for review-pdl1-report')).toBeDisabled()
  await cycle(page, 'Synthetic portfolio', ['scenario-a', 'scenario-a', 'scenario-a'], info)
  await page.getByRole('button', { name: 'Reset hypothetical reviews', exact: true }).click()
  await expect(page.getByLabel('Simulated report for review-pdl1-report')).toBeEnabled()
  await cycle(page, 'Algorithm', ['adaptive_replan', 'joint_greedy', 'exact_nonadaptive'], info)
  state.failCalculation = true
  await choose(page, 'Algorithm', 'joint_greedy', info)
  await expect(page.getByRole('alert')).toContainText('Software fixture calculation failure')
  state.failCalculation = false
  await cycle(page, 'Algorithm', ['adaptive_replan', 'exact_nonadaptive', 'adaptive_replan'], info)
  state.failCatalog = true
  await page.getByRole('button', { name: 'Refresh connection', exact: true }).click()
  await expect(page.locator('#case-selection-status')).toContainText('refresh failed')
  await cycle(page, 'Synthetic portfolio', ['scenario-b', 'scenario-c', 'scenario-a'], info)
  await openView(page, 'Trial explorer')
  await page.getByRole('button', { name: 'Inspect extraction for NCT00000001', exact: true }).click()
  await expect(page.getByLabel('Extraction mode')).toBeVisible()
  state.failSnapshot = true
  await choose(page, 'Snapshot history', 'older/response.json', info)
  await expect(page.getByRole('alert')).toContainText('Software fixture snapshot failure')
  await cycle(page, 'Snapshot history', ['oldest/response.json', 'latest/response.json', 'oldest/response.json'], info)
})

test('native popups reopen after mobile navigation, Escape and viewport changes', async ({ page }, info) => {
  await mockApi(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click()
  await page.getByRole('button', { name: 'Research Tools', exact: true }).click()
  await cycle(page, 'Application mode', ['tnbc', 'research', 'tnbc'], info)
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click()
  await page.getByRole('button', { name: 'Try Demo', exact: true }).click()
  await openView(page, 'Patient evidence')
  await cycle(page, 'Evidence category', ['Biomarkers', 'Laboratory', 'Biomarkers', 'All categories'], info)
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click()
  await page.keyboard.press('Escape')
  await cycle(page, 'Evidence availability / limitation', ['Missing', 'Observed', 'Missing', 'All evidence'], info)
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await expect(page.locator('main')).not.toHaveAttribute('inert')
  await cycle(page, 'Evidence category', ['Laboratory', 'Biomarkers', 'Laboratory', 'All categories'], info)
  await page.screenshot({ path: info.outputPath('mobile-to-desktop.png'), fullPage: true })
})

test('guided product flow preserves context and applies drafts explicitly', async ({ page }, info) => {
  const state = await mockApi(page)
  await page.goto('/')
  await expect(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button')).toHaveCount(4)
  await page.screenshot({ path: info.outputPath('home-desktop.png'), fullPage: true })
  await page.getByRole('button', { name: 'Try the demo', exact: true }).click()
  if (!await page.getByRole('navigation', { name: 'Demo steps' }).isVisible()) await page.getByText('Advanced Mode', { exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Fictional TNBC case', exact: true })).toHaveValue('tnbc-record-gaps')
  await expect(page.getByRole('combobox', { name: 'Fictional TNBC case', exact: true })).toHaveCount(1)
  await page.screenshot({ path: info.outputPath('demo-desktop.png'), fullPage: true })
  await page.getByRole('navigation', { name: 'Demo steps' }).getByRole('button', { name: /Simulate a review/ }).click()
  await expect(page.getByText('Updating the fictional research calculation…', { exact: true })).not.toBeVisible()
  const value = await page.getByLabel('Fictional report outcome').locator('option').nth(1).getAttribute('value')
  const requests = state.posts.length
  await choose(page, 'Fictional report outcome', value, info)
  expect(state.posts.length).toBe(requests)
  await page.getByRole('button', { name: 'Home', exact: true }).click()
  await page.getByRole('button', { name: 'Try Demo', exact: true }).click()
  await expect(page.getByLabel('Fictional report outcome')).toHaveValue(value)
  await page.getByRole('button', { name: 'Apply simulated review', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Hypothetical results applied' })).toBeVisible()
  await page.getByRole('button', { name: 'Research Tools', exact: true }).click()
  await choose(page, 'Synthetic portfolio', 'scenario-b', info)
  await page.getByRole('button', { name: 'Reports & benchmarks', exact: true }).click()
  await page.getByRole('navigation', { name: 'Saved report list' }).getByRole('button').first().click()
  await expect(page.locator('pre[aria-label="Original saved report"]')).toBeVisible()
  await page.getByRole('button', { name: 'Try Demo', exact: true }).click()
  await expect(page.getByLabel('Fictional TNBC case')).toHaveValue('tnbc-record-gaps')
  await expect(page.getByRole('status').filter({ hasText: 'Hypothetical results applied' })).toBeVisible()
  await page.getByRole('button', { name: 'Home', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('home-mobile.png'), fullPage: true })
  await page.getByRole('button', { name: 'Try the demo', exact: true }).click()
  if (!await page.getByRole('navigation', { name: 'Demo steps' }).isVisible()) await page.getByText('Advanced Mode', { exact: true }).click()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('demo-mobile.png'), fullPage: true })
})
