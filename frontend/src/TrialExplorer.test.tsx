import { useState } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import TrialExplorer from './TrialExplorer'
import type { Trial } from './types'

const studies: Trial[] = [
  { nct_id: 'NCT00000001', title: 'Software fixture: breast protocol A', recruitment_status: 'RECRUITING', conditions: ['Triple-negative breast cancer'], eligibility_criteria: 'Inclusion Criteria:\nSynthetic marker A', source_url: 'https://clinicaltrials.gov/study/NCT00000001', snapshot: 'latest/response.json', retrieved_at: '2026-10-23T12:00:00Z', is_synthetic: true, snapshot_count: 2 },
  { nct_id: 'NCT00000002', title: 'Software fixture: solid tumor protocol B', recruitment_status: 'COMPLETED', conditions: ['Solid tumors'], eligibility_criteria: 'Exclusion Criteria:\nSynthetic marker B', source_url: 'https://clinicaltrials.gov/study/NCT00000002', snapshot: 'latest/response.json', retrieved_at: '2026-10-22T12:00:00Z', is_synthetic: true, snapshot_count: 1 },
]

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    expect(options?.method).toBeUndefined()
    const trial = studies.find(item => url.includes(item.nct_id!))!
    const historical = url.includes('older%2F')
    return { ok: true, json: async () => ({
      source: { nct_id: trial.nct_id, text: historical ? 'Inclusion Criteria:\nHistorical synthetic marker' : trial.eligibility_criteria,
        source_url: trial.source_url, source_snapshot: historical ? 'data/raw/trials/older/response.json' : 'data/raw/trials/latest/response.json',
        retrieval_timestamp: historical ? '2026-10-20T12:00:00Z' : trial.retrieved_at, is_synthetic: true, sha256: (historical ? 'b' : 'a').repeat(64) },
      snapshots: [trial, ...(trial.snapshot_count === 2 ? [{ ...trial, snapshot: 'older/response.json', title: 'Historical software fixture title', conditions: ['Historical fixture condition'], recruitment_status: 'NOT_YET_RECRUITING', retrieved_at: '2026-10-20T12:00:00Z' }] : [])],
      warnings: [], mock_version: 'verbatim-sections-v1',
    }) }
  }))
})

function Harness() {
  const [selected, setSelected] = useState<Trial | null>(null)
  return <TrialExplorer trials={studies} status="ready" warnings={[]} selected={selected} onSelect={setSelected} retry={() => {}} />
}

test('registry status remains changeable repeatedly and after returning from inspection', async () => {
  render(<Harness />)
  for (const value of ['COMPLETED', 'RECRUITING', '', 'COMPLETED', '']) {
    const status = screen.getByLabelText('Registry status')
    status.focus()
    expect(status).toHaveFocus()
    fireEvent.keyDown(status, { key: 'ArrowDown' })
    fireEvent.change(status, { target: { value } })
    expect(status).toHaveValue(value)
    expect(status).toBeEnabled()
  }
  fireEvent.click(screen.getByRole('button', { name: 'Inspect extraction for NCT00000001' }))
  await screen.findByLabelText('Exact original eligibility text')
  fireEvent.click(screen.getByRole('button', { name: 'Change study' }))
  fireEvent.change(screen.getByLabelText('Registry status'), { target: { value: 'COMPLETED' } })
  fireEvent.change(screen.getByLabelText('Registry status'), { target: { value: 'RECRUITING' } })
  expect(screen.getByRole('button', { name: 'Inspect extraction for NCT00000001' })).toBeEnabled()
})

test('study selection opens one dedicated workspace and never runs extraction automatically', async () => {
  render(<Harness />)
  expect(screen.getByText('Select a study to inspect')).toBeInTheDocument()
  expect(screen.queryByLabelText('Exact original eligibility text')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Inspect extraction for NCT00000001' }))
  expect(await screen.findByLabelText('Exact original eligibility text')).toHaveTextContent('Synthetic marker A')
  expect(screen.getByRole('region', { name: 'Extraction panel for NCT00000001' })).toHaveFocus()
  fireEvent.click(screen.getByRole('button', { name: 'Change study' }))
  fireEvent.click(screen.getByRole('button', { name: 'Inspect extraction for NCT00000002' }))
  expect(await screen.findByLabelText('Exact original eligibility text')).toHaveTextContent('Synthetic marker B')
  expect(screen.queryByRole('region', { name: 'Extraction panel for NCT00000001' })).not.toBeInTheDocument()
  expect(screen.getAllByLabelText('Saved-trial extraction')).toHaveLength(1)
  expect(fetch).toHaveBeenCalledTimes(2)
})

test.each([
  ['NCT00000002', 'NCT00000002'], ['solid tumor', 'NCT00000002'], ['completed', 'NCT00000002'],
  ['triple-negative', 'NCT00000001'], ['2026-10-22', 'NCT00000002'],
])('searches saved metadata: %s', (query, expectedId) => {
  render(<Harness />)
  fireEvent.change(screen.getByLabelText('Search trials'), { target: { value: query } })
  expect(screen.getByRole('button', { name: `Inspect extraction for ${expectedId}` })).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: /Inspect extraction for/ })).toHaveLength(1)
  expect(fetch).not.toHaveBeenCalled()
})

test('status filtering has a recoverable no-match state and preserves the selected inspection', async () => {
  render(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: 'Inspect extraction for NCT00000001' }))
  await screen.findByLabelText('Snapshot history')
  fireEvent.click(screen.getByRole('button', { name: 'Change study' }))
  fireEvent.change(screen.getByLabelText('Registry status'), { target: { value: 'COMPLETED' } })
  expect(screen.queryByRole('button', { name: 'Inspect extraction for NCT00000001' })).not.toBeInTheDocument()
  expect(screen.getByText(/selected study is outside the current filter/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Search trials'), { target: { value: 'unmatched' } })
  expect(screen.getByText('No matching studies')).toBeInTheDocument()
  expect(screen.getByLabelText('Exact original eligibility text')).toHaveTextContent('Synthetic marker A')
  fireEvent.click(screen.getByRole('button', { name: 'Clear study filters' }))
  expect(screen.getAllByRole('button', { name: /Inspect extraction for/ })).toHaveLength(2)
})

test('selection collapses the library and returning restores focus without resetting inspection', async () => {
  render(<Harness />)
  const first = screen.getByRole('button', { name: 'Inspect extraction for NCT00000001' })
  fireEvent.click(first)
  await screen.findByLabelText('Snapshot history')
  expect(screen.getByRole('button', { name: 'Change study' })).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('region', { name: 'Saved study selection' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Back to study list' }))
  expect(screen.getByRole('region', { name: 'Saved study selection' })).toBeVisible()
  expect(first).toHaveFocus()
  expect(screen.getByLabelText('Exact original eligibility text')).toHaveTextContent('Synthetic marker A')
  fireEvent.click(screen.getByRole('button', { name: 'Return to inspection' }))
  expect(screen.getByRole('region', { name: 'Extraction panel for NCT00000001' })).toHaveFocus()
  expect(fetch).toHaveBeenCalledTimes(1)
})

test('study buttons support directional keyboard focus without changing selection', () => {
  render(<Harness />)
  const first = screen.getByRole('button', { name: 'Inspect extraction for NCT00000001' })
  const second = screen.getByRole('button', { name: 'Inspect extraction for NCT00000002' })
  first.focus()
  fireEvent.keyDown(first, { key: 'ArrowDown' })
  expect(second).toHaveFocus()
  fireEvent.keyDown(second, { key: 'Home' })
  expect(first).toHaveFocus()
  fireEvent.keyDown(first, { key: 'End' })
  expect(second).toHaveFocus()
  expect(fetch).not.toHaveBeenCalled()
})

test('historical snapshot metadata and exact source replace the latest version', async () => {
  render(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: 'Inspect extraction for NCT00000001' }))
  await screen.findByRole('option', { name: /older\/response.json/ })
  fireEvent.change(screen.getByLabelText('Snapshot history'), { target: { value: 'older/response.json' } })
  const panel = screen.getByRole('region', { name: 'Extraction panel for NCT00000001' })
  expect(await within(panel).findByRole('heading', { name: 'Historical software fixture title' })).toBeInTheDocument()
  expect(within(panel).getByText('Historical fixture condition')).toBeInTheDocument()
  expect(within(panel).getByText('NOT YET RECRUITING')).toBeInTheDocument()
  expect(within(panel).getByLabelText('Exact original eligibility text')).toHaveTextContent('Historical synthetic marker')
  expect(within(panel).getByText('b'.repeat(64))).toBeInTheDocument()
  expect(within(panel).getByRole('link', { name: 'Original ClinicalTrials.gov record' })).toHaveAttribute('href', studies[0].source_url)
  expect(fetch).toHaveBeenCalledTimes(2)
})

test('library loading, empty and error states stay distinct', () => {
  const retry = vi.fn()
  const view = render(<TrialExplorer trials={[]} status="loading" warnings={[]} selected={null} onSelect={() => {}} retry={retry} />)
  expect(screen.getByText('Loading saved studies')).toBeInTheDocument()
  view.rerender(<TrialExplorer trials={[]} status="ready" warnings={[]} selected={null} onSelect={() => {}} retry={retry} />)
  expect(screen.getByText('No saved studies')).toBeInTheDocument()
  view.rerender(<TrialExplorer trials={[]} status="error" warnings={['Local storage unavailable']} selected={null} onSelect={() => {}} retry={retry} />)
  expect(screen.getByRole('alert')).toHaveTextContent('Local storage unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'Retry library' }))
  expect(retry).toHaveBeenCalledTimes(1)
})

test('study selection and mock extraction expose validation failure and unsupported semantics', async () => {
  const originalFetch = fetch
  const source = { nct_id: studies[0].nct_id, text: studies[0].eligibility_criteria,
    source_url: studies[0].source_url, source_snapshot: 'data/raw/trials/latest/response.json',
    retrieval_timestamp: studies[0].retrieved_at, is_synthetic: true, sha256: 'a'.repeat(64) }
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (!url.endsWith('/extractions')) return originalFetch(url, options)
    expect(options?.method).toBe('POST')
    expect(JSON.parse(String(options?.body))).toEqual({ snapshot: 'latest/response.json', snapshot_sha256: source.sha256, mode: 'mock', mock_version: 'verbatim-sections-v1' })
    return { ok: true, json: async () => ({ source,
      manifest: { status: 'validation_failed', prompt_version: 'software-test', requested_model: 'mock-no-model', returned_model: 'mock-no-model', mode: 'mock' },
      mock_version: 'verbatim-sections-v1', validated: null,
      candidate: { criteria: [{ criterion_id: 'fixture-criterion', original_text: 'Synthetic marker A', criterion_type: 'inclusion', logical_operator: null, dependencies: null }],
        evidence: [{ criterion_id: 'fixture-criterion', original_span: { start: 20, end: 38 }, polarity_span: { start: 0, end: 19 }, fields: {} }] },
      validation_errors: [{ code: 'unresolved_logical_operator', criterion_id: 'fixture-criterion' }],
      unsupported_criteria: [{ criterion_id: 'fixture-criterion', reason: 'unreviewed_semantics_no_execution_mapping' }],
      assessment_allowed: false, assessment_block_reason: 'Human review and executable bindings are required.',
      output_directory: 'results/extraction/software-test-only',
    }) }
  }))
  render(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: 'Inspect extraction for NCT00000001' }))
  expect(await screen.findByLabelText('Extraction mode')).toHaveValue('mock')
  fireEvent.click(screen.getByRole('button', { name: 'Run mock extraction' }))
  expect(await screen.findByText('validation_failed')).toBeVisible()
  expect(screen.getByText('Request succeeded')).toBeVisible()
  expect(screen.getByText('Not validated')).toBeVisible()
  expect(screen.getByText('unresolved_logical_operator')).toBeVisible()
  expect(screen.getByText('unreviewed_semantics_no_execution_mapping')).toBeVisible()
  expect(screen.getByText('Assessment blocked')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Change study' }))
  expect(screen.getByText('validation_failed')).toBeVisible()
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/extractions'))).toHaveLength(1)
})
