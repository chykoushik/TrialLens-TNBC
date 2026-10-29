import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import RealTrialReview from './RealTrialReview'
import type { Trial } from './types'

const trial: Trial = { nct_id: 'NCT00000001', title: 'Registry source software test fixture',
  eligibility_criteria: 'SOFTWARE TEST SOURCE ONLY\nInclusion Criteria:\nA AND (B OR C)\nExclusion Criteria:\nNo item D.',
  source_url: 'https://clinicaltrials.gov/study/NCT00000001', snapshot: 'software-fixture/response.json', snapshot_sha256: 'a'.repeat(64),
  conditions: [], recruitment_status: null, retrieved_at: null, is_synthetic: null }
const hash = trial.snapshot_sha256!
const review = { source: { nct_id: trial.nct_id, sha256: hash, text: trial.eligibility_criteria }, source_passages: [], reviewed_source_criteria: [], executable_mapping_count: 0,
  assessment_available: false, complete_eligibility_available: false, saved_extractions: [], patient_evidence: [], planning: { available: false, selected_reports: [], missing_inputs: ['Reviewed executable bindings', 'Authorized patient evidence'] } }
beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith('/health') ? { status: 'ok' } : url.endsWith('/research/trials') ? { trials: [trial], warnings: [] } : url.includes('/review?') ? review : {} })))
})
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

test('the primary workflow selects and analyzes a real source without a fictional assessment', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith('/health') ? { status: 'ok' } : url.endsWith('/research/trials') ? { trials: [trial], warnings: [] } : { ...review, scope: 'Source review only', inference: { explanation: 'Saved source analysis; no paid request.' } } })))
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: /Select NCT00000001/ }))
  expect(screen.getByText(/A AND/, { selector: '.source-text' }).textContent).toBe(trial.eligibility_criteria)
  fireEvent.click(screen.getByRole('button', { name: 'Analyze trial' }))
  expect(await screen.findByRole('heading', { name: 'Trial analysis results' })).toBeVisible()
  expect(screen.getByText(/Patient assessment is unavailable/)).toBeVisible()
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method)).toBe(true)
  expect(vi.mocked(fetch).mock.calls.some(([url]) => /\/(tnbc|research)\/cases/.test(String(url)))).toBe(false)
})

test('missing real sources and changed snapshot identities never substitute a demo', () => {
  const props = { trials: [] as Trial[], status: 'ready' as const, warnings: [], retry: vi.fn(), home: vi.fn(), demo: vi.fn() }
  const view = render(<RealTrialReview {...props} />)
  expect(screen.getByText(/No real trial records are available/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  view.unmount()
  localStorage.setItem('triallens.real-source-review.v1', JSON.stringify({ nct: trial.nct_id, snapshot: trial.snapshot, hash: '0'.repeat(64), step: 4 }))
  render(<RealTrialReview {...props} trials={[trial]} />)
  expect(screen.getByText(/same identity/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  expect(props.demo).not.toHaveBeenCalled()
})
