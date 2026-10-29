import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import TrialSearch from './TrialSearch'
import type { Trial } from './types'

const trial: Trial = { nct_id: 'NCT00000001', title: 'Software registry display fixture', recruitment_status: 'COMPLETED', conditions: ['Software fixture'],
  eligibility_criteria: 'Original software fixture criteria', source_url: 'https://clinicaltrials.gov/study/NCT00000001', snapshot: 'fixture/response.json',
  snapshot_sha256: 'a'.repeat(64), retrieved_at: null, is_synthetic: null }
afterEach(() => vi.unstubAllGlobals())

test('search forwards treatment and recruitment filters and offers selection', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ trials: [trial], next_page_token: 'cursor', origin: 'Software API fixture' }) })))
  render(<TrialSearch trials={[]} research={vi.fn()} demo={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Search by'), { target: { value: 'intervention' } })
  fireEvent.change(screen.getByLabelText('Search terms'), { target: { value: 'software treatment' } })
  fireEvent.change(screen.getByLabelText('Study status'), { target: { value: 'COMPLETED' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search trials' }))
  expect(await screen.findByRole('button', { name: 'Select NCT00000001' })).toBeVisible()
  expect(vi.mocked(fetch).mock.calls[0][0]).toContain('intervention=software+treatment')
  expect(vi.mocked(fetch).mock.calls[0][0]).toContain('status=COMPLETED')
  fireEvent.click(screen.getByRole('button', { name: 'Next results' }))
  expect(vi.mocked(fetch).mock.calls[1][0]).toContain('page_token=cursor')
})

test('network failure leaves genuine saved choices available and does not substitute records', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 504, json: async () => ({ detail: 'Registry timeout' }) })))
  render(<TrialSearch trials={[trial]} research={vi.fn()} demo={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Search terms'), { target: { value: 'software fixture' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search trials' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Registry timeout')
  expect(screen.getByRole('button', { name: 'Select NCT00000001' })).toBeVisible()
  expect(screen.queryByLabelText('Operator access code')).not.toBeInTheDocument()
  expect(screen.queryByText('Request NVIDIA extraction')).not.toBeInTheDocument()
})

test('a record without eligibility text cannot start an unsupported analysis', () => {
  render(<TrialSearch trials={[{ ...trial, eligibility_criteria: null }]} research={vi.fn()} demo={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Select NCT00000001' }))
  expect(screen.getByRole('button', { name: 'Analyze trial' })).toBeDisabled()
  expect(screen.getByText(/Choose another trial/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Back to Search' }))
  expect(screen.getByRole('button', { name: 'Search trials' })).toBeVisible()
})
