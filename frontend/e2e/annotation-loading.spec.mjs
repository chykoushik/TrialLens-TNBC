import { navigate } from './navigation.mjs'
import { test, expect } from '@playwright/test'

test('saved annotation sources use the configured backend and recover after failure', async ({ page, request }, info) => {
  const backend = process.env.DROPDOWN_BACKEND
  test.skip(!backend, 'Requires local FastAPI')
  const network = []
  page.on('response', response => {
    if (response.url().includes('/annotations/')) network.push({ url: response.url(), status: response.status() })
  })
  await page.goto('/')
  await navigate(page, 'Research Tools')
  await page.getByRole('button', { name: 'Protocol annotation', exact: true }).click()
  await expect(page.getByLabel('Annotation snapshot')).toBeEnabled()
  for (const nct of ['NCT02648477', 'NCT01770353']) {
    await page.getByLabel('Annotation study').selectOption(nct)
    await expect(page.getByLabel('Annotation snapshot')).toBeEnabled()
    const response = await request.get(`${backend}/annotations/${nct}`)
    expect(response.status()).toBe(200)
    const workspace = await response.json()
    for (const item of workspace.snapshots) {
      await page.getByLabel('Annotation snapshot').selectOption(item.snapshot)
      await expect(page.getByLabel('Annotation snapshot')).toBeEnabled()
      const selected = await request.get(`${backend}/annotations/${nct}?snapshot=${encodeURIComponent(item.snapshot)}`)
      const data = await selected.json()
      await page.getByText('Advanced Mode: annotation details', { exact: true }).click()
      await expect(page.getByLabel('Exact original eligibility text')).toHaveText(data.source.text)
      await expect(page.getByText(`Snapshot SHA-256: ${data.source.sha256}`)).toBeVisible()
      await page.getByText('Advanced Mode: annotation details', { exact: true }).click()
    }
  }
  await page.route('**/annotations/NCT02648477', route => route.fulfill({ status: 503, json: { detail: 'Temporary source failure' } }), { times: 1 })
  await page.getByLabel('Annotation study').selectOption('NCT02648477')
  await expect(page.getByRole('alert').filter({ hasText: 'Temporary source failure' })).toContainText('Temporary source failure')
  await page.getByRole('button', { name: 'Reload source', exact: true }).click()
  await expect(page.getByLabel('Annotation snapshot')).toBeEnabled()
  expect((await request.get(`${backend}/annotations/NCT00000001`)).status()).toBe(404)
  await info.attach('annotation-network', { body: JSON.stringify(network, null, 2), contentType: 'application/json' })
  if (process.env.VITE_API_BASE_URL) expect(network.every(item => item.url.startsWith(`${backend}/annotations/`))).toBe(true)
})

