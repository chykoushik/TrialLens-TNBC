import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import NemotronReview from './NemotronReview'
import type { Trial } from './types'

const trial: Trial = { nct_id: 'NCT00000001', title: 'Software extraction fixture', conditions: [], recruitment_status: null,
  eligibility_criteria: 'Software source fixture only.', source_url: 'https://clinicaltrials.gov/study/NCT00000001',
  snapshot: 'fixture/response.json', snapshot_sha256: 'a'.repeat(64), retrieved_at: null, is_synthetic: true }
const report = { source: { nct_id: trial.nct_id, sha256: trial.snapshot_sha256, source_snapshot: 'data/raw/trials/fixture/response.json', text: trial.eligibility_criteria, source_url: trial.source_url, is_synthetic: true },
  manifest: { mode: 'mock', status: 'validation_failed' }, candidate: { criteria: [{ criterion_id: 'software-rule', original_text: trial.eligibility_criteria, criterion_type: 'inclusion', logical_operator: null }] },
  validated: null, validation_errors: [], review_checks_passed: false, attempt_sha256: 'b'.repeat(64), mapping_reviews: {}, output_directory: 'results/extraction/test-attempt' }
afterEach(() => vi.unstubAllGlobals())
function setup(ready = false, scope: Record<string, unknown> = {}) {
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => ({ ok: true, json: async () => String(url).includes('/inference?') ? {
    snapshot_sha256: trial.snapshot_sha256, configuration: { ready, missing_variables: [], request_available: ready, maximum_estimated_cost_usd: ready ? 0.02 : null, operator_configured: ready, cost_controls_ready: ready, ...scope },
    attempts: [{ id: 'test-attempt', mode: 'mock', status: 'validation_failed', timestamp: 'Software test only' }],
  } : options?.method === 'POST' ? report : report })))
}

test('unavailable inference never sends a request or pretends a saved mock is live', async () => {
  setup()
  render(<NemotronReview trial={trial} />)
  expect(await screen.findByText(/Live extraction is unavailable/)).toBeVisible()
  fireEvent.click(screen.getByText('Operator access and live request controls'))
  expect(screen.getByRole('button', { name: 'Request NVIDIA extraction' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Saved extraction'), { target: { value: 'test-attempt' } })
  expect(await screen.findByText('Offline mock output')).toBeVisible()
  fireEvent.change(screen.getByLabelText('Extracted condition'), { target: { value: '0' } })
  expect(screen.getByRole('button', { name: 'Approve supported mapping' })).toBeDisabled()
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method)).toBe(true)
})

test('a live request requires explicit operator approval and is sent only once with source identity', async () => {
  setup(true, { maximum_estimated_cost_usd: 0.0145728, authorization_id: 'c'.repeat(32), authorized_maximum_estimated_cost_usd: '0.0145728', remaining_authorized_requests: 1 })
  render(<NemotronReview trial={trial} />)
  await screen.findByText(/Live extraction is configured/)
  fireEvent.click(screen.getByText('Operator access and live request controls'))
  fireEvent.change(screen.getByLabelText('Operator access code'), { target: { value: 'software-test-operator-code' } })
  const button = screen.getByRole('button', { name: 'Request NVIDIA extraction' })
  expect(button).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox', { name: /I authorize one paid Nebius request/ }))
  fireEvent.click(button)
  fireEvent.click(button)
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1))
  const [, options] = vi.mocked(fetch).mock.calls.find(([, options]) => options?.method === 'POST')!
  expect(JSON.parse(String(options?.body))).toMatchObject({ mode: 'live', live_approved: true, snapshot: trial.snapshot, snapshot_sha256: trial.snapshot_sha256, authorization_id: 'c'.repeat(32), maximum_estimated_cost_usd: '0.0145728' })
  expect(options?.headers).toHaveProperty('Authorization', 'Bearer software-test-operator-code')
  await waitFor(() => expect(button).toBeDisabled())
  expect(Object.values(localStorage).join('')).not.toContain('software-test-operator-code')
})

test('recovered partial output is review-only and cannot expose mapping approval', async () => {
  setup()
  const original = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => String(url).includes('/inference?') ? original(url, options) : {
    ok: true, json: async () => ({ ...report, manifest: { mode: 'live', status: 'failed' }, candidate: null,
      partial_recovery: { complete_top_level_objects: 1, exact_source_top_level_objects: 1, scope: 'Software partial-response fixture only.',
        objects: [{ candidate: { criterion_id: 'software-rule', original_text: trial.eligibility_criteria }, source_checks: [{ exact_match_count: 1 }] }] } }),
  }))
  render(<NemotronReview trial={trial} />)
  await screen.findByLabelText('Saved extraction')
  fireEvent.change(screen.getByLabelText('Saved extraction'), { target: { value: 'test-attempt' } })
  expect(await screen.findByRole('heading', { name: 'Partial recovery · review only' })).toBeVisible()
  fireEvent.click(screen.getByText('Inspect intact recovered objects'))
  expect(screen.getByText(trial.eligibility_criteria!)).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Approve supported mapping' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Extracted condition')).not.toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method)).toBe(true)
})
