import { test, expect } from '@playwright/test'
import { navigate } from './navigation.mjs'

test('public production build: live registry, analysis, actual adaptive review and research on desktop and mobile', async ({ page }, info) => {
  const errors = []
  const visitorRequests = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => {
    if (/visitor-analysis|tokenfactory|\/operator\//.test(request.url())) visitorRequests.push(request.url())
  })
  const assertPublic = async () => {
    await expect(page.getByText('Operator tools', { exact: true })).toHaveCount(0)
    await expect(page.getByLabel('Operator access code', { exact: true })).toHaveCount(0)
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  for (const [name, size] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
    await page.setViewportSize(size)
    await page.goto('/')
    await page.getByLabel('Search terms', { exact: true }).fill('triple-negative breast cancer')
    const registryResponse = page.waitForResponse(response => response.url().includes('/clinical-trials/search?'))
    await page.getByRole('button', { name: 'Search trials', exact: true }).click()
    const response = await registryResponse
    expect(response.status()).toBe(200)
    const records = await response.json()
    expect(records.origin).toBe('ClinicalTrials.gov API v2')
    expect(records.trials.length).toBeGreaterThan(0)
    const trial = records.trials.find(row => row.eligibility_criteria)
    expect(trial.nct_id).toMatch(/^NCT\d{8}$/)
    await page.getByRole('button', { name: `Select ${trial.nct_id}`, exact: true }).click()
    await page.getByRole('button', { name: 'Analyze trial', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Trial analysis results' })).toBeVisible()
    await expect(page.getByText(/Public BYOK is currently disabled/)).toBeVisible()
    await assertPublic()
    await page.getByRole('button', { name: 'Back to Search', exact: true }).click()
    await page.getByLabel('Search terms', { exact: true }).fill('NCT04331067')
    await page.getByRole('button', { name: 'Search trials', exact: true }).click()
    await page.getByRole('button', { name: 'Select NCT04331067', exact: true }).click()
    const analysisResponse = page.waitForResponse(response => response.url().includes('/NCT04331067/analysis?'))
    await page.getByRole('button', { name: 'Analyze trial', exact: true }).click()
    const analysis = await (await analysisResponse).json()
    expect(analysis.inference.request_sent).toBe(false)
    expect(analysis.assessment_available).toBe(false)
    expect(analysis.source.source_url).toBe('https://clinicaltrials.gov/study/NCT04331067')
    for (const saved of analysis.saved_extractions) {
      if (saved.saved_status === 'failed') expect(saved.source_structure_valid).toBe(false)
    }
    await page.getByText(/View source passages and unresolved conditions/).click()
    await expect(page.getByText(/Absolute neutrophil count/).last()).toBeAttached()
    await assertPublic()
    await page.screenshot({ path: info.outputPath(`public-analysis-${name}.png`), fullPage: true })
    await page.getByRole('button', { name: 'Explore the research planner', exact: true }).click()
    const outcomes = page.locator('select[aria-label^="Outcome for report"]:enabled')
    await expect(outcomes.first()).toBeEnabled()
    const before = await page.locator('.planner-summary').innerText()
    const evaluation = page.waitForResponse(response => response.url().includes('/research/planner/evaluate'))
    await outcomes.first().selectOption('1')
    const after = await (await evaluation).json()
    expect(after.spent).toBeGreaterThan(0)
    expect(after.spent).toBeLessThanOrEqual(after.budget)
    expect(after.bdd_nodes).toBeGreaterThan(2)
    expect(after.expected_policy_metrics.max_model_risk).toBeLessThanOrEqual(.08000001)
    await expect(page.locator('.planner-summary')).not.toHaveText(before)
    await page.getByText('Risk, abstention and reproducibility', { exact: true }).click()
    await expect(page.getByText(/Cached diagram hits/)).toBeVisible()
    await page.getByRole('combobox', { name: 'Review budget', exact: true }).selectOption('0')
    await expect(page.locator('.planner-summary')).toContainText('100.0%')
    await expect(page.locator('select[aria-label^="Outcome for report"]:enabled')).toHaveCount(0)
    await assertPublic()
    await page.screenshot({ path: info.outputPath(`public-planner-${name}.png`), fullPage: true })
    await navigate(page, 'Research Results')
    await expect(page.getByRole('heading', { name: 'METABRIC: reviewing incomplete evidence' })).toBeVisible()
    const selector = page.getByRole('combobox', { name: 'Study and result table', exact: true })
    for (const identifier of ['paper-means', 'metabric', 'tcga-expanded', 'paper-benchmarks', 'continuous', 'paper-ordering']) {
      const current = await selector.inputValue()
      if (current !== identifier) {
        const artifact = page.waitForResponse(response => response.url().includes(`/research/evaluation/${identifier}?`))
        await selector.selectOption(identifier)
        expect((await artifact).status()).toBe(200)
      }
      await expect(page.getByRole('region', { name: 'Saved experiment table', exact: true }).getByRole('table')).toBeVisible()
    }
    await assertPublic()
    await page.screenshot({ path: info.outputPath(`public-research-${name}.png`), fullPage: true })
    await navigate(page, 'Explore Trials')
    await expect(page.getByText('Advanced Mode: source & extraction tools', { exact: true })).toHaveCount(0)
    await assertPublic()
  }
  expect(visitorRequests).toEqual([])
  expect(errors).toEqual([])
})
