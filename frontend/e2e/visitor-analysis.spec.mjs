import { test, expect } from '@playwright/test'
import { navigate } from './navigation.mjs'

test('real saved trial to source-only results, explicit visitor approval and research tools on desktop and mobile', async ({ page }, info) => {
  const posts = []
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/visitor-analysis/**', async route => {
    posts.push(route.request().postDataJSON())
    if (route.request().url().endsWith('/prepare')) {
      await route.fulfill({ json: { analysis_id: 'a'.repeat(64), model: 'NVIDIA mock transport only', request_count: 3, maximum_cost_usd: '0.03', max_output_tokens_per_request: 8192, expires_in_seconds: 600 } })
    } else {
      expect(route.request().postDataJSON()).toMatchObject({ api_key: 'non-secret-browser-fixture', confirmed: true, maximum_cost_usd: '0.03' })
      await route.fulfill({ json: { status: 'incomplete', human_review_required: true, sections: [
        { section: 1, status: 'validated', criteria: [{ criterion_id: 'fixture', original_text: 'MOCK SOFTWARE OUTPUT: not clinical evidence' }] },
        { section: 2, status: 'failed', error: 'incomplete_response', criteria: [] },
        { section: 3, status: 'not_requested', criteria: [] },
      ] } })
    }
  })
  for (const [name, size] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
    posts.length = 0
    await page.setViewportSize(size)
    await page.goto('/')
    await page.getByLabel('Search terms', { exact: true }).fill('NCT06774027')
    await page.getByRole('button', { name: 'Search trials', exact: true }).click()
    await page.getByRole('button', { name: 'Select NCT06774027', exact: true }).click()
    await page.getByRole('button', { name: 'Analyze trial', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Trial analysis results' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Eligibility reasoning' })).toBeVisible()
    expect(posts).toHaveLength(0)
    await page.getByRole('button', { name: 'Analyze with NVIDIA' }).click()
    await expect(page.getByText(/Planned provider requests: 3/)).toBeVisible()
    await page.getByLabel('Connect Nebius API Key').fill('non-secret-browser-fixture')
    await expect(page.getByRole('button', { name: 'Approve cost and analyze' })).toBeDisabled()
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: 'Approve cost and analyze' }).click()
    await expect(page.getByRole('heading', { name: 'NVIDIA extraction: incomplete' })).toBeVisible()
    await expect(page.getByText('MOCK SOFTWARE OUTPUT: not clinical evidence')).toBeVisible()
    expect(posts).toHaveLength(2)
    await expect(page.getByLabel('Connect Nebius API Key')).toHaveCount(0)
    expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain('non-secret-browser-fixture')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: info.outputPath(`analysis-${name}.png`), fullPage: true })
    await page.getByRole('button', { name: 'View Research Results', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'What the research shows' })).toBeVisible()
    await expect(page.getByText(/METABRIC: reviewing incomplete evidence/)).toBeVisible()
    await navigate(page, 'Evidence Review')
    await expect(page.getByRole('heading', { name: 'Available reports' })).toBeVisible()
    await expect(page.getByText(/current uncertainty/)).toBeVisible()
    await page.screenshot({ path: info.outputPath(`planner-${name}.png`), fullPage: true })
  }
  expect(errors).toEqual([])
})
