import { test, expect } from '@playwright/test'

test('NCT04331067 clearly shows zero authorizations and never sends an inference request', async ({ page }) => {
  const attempts = []
  await page.route('**/api/**', route => {
    if (route.request().method() === 'POST' && route.request().url().includes('/extractions')) {
      attempts.push(route.request().url())
      return route.abort()
    }
    return route.continue()
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Start Evidence Review', exact: true }).click()
  await page.locator('.simple-trial-list button').filter({ hasText: 'NCT04331067' }).click()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByText(/Remaining authorized requests for this source:/)).toHaveText(/0/)
  await page.getByText('Operator access and live request controls', { exact: true }).click()
  await expect(page.getByText(/Maximum estimated request cost:/)).toContainText('$0.0145728')
  await expect(page.getByText(/original request reservation remains consumed/)).toBeVisible()
  await expect(page.getByText(/Live requests are disabled in the backend/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request NVIDIA extraction', exact: true })).toBeDisabled()
  expect(attempts).toEqual([])
})
