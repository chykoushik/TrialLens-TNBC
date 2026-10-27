import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App, { CriterionCard, StateBadge } from './App'
import type { Assessed, Evaluation, State } from './types'

const node: Assessed = { criterion_id: 'synthetic-er', criterion: { criterion_id: 'synthetic-er', criterion_type: 'exclusion', original_text: 'SYNTHETIC exclusion condition', source_url: null, cohort: null, logical_operator: 'NONE', biomarker: 'ER', assay: null, temporal_constraint: null }, state: 'unknown', explanation: null, reason_code: 'missing_compatible_evidence', evidence_ids: [], dependencies: [] }
const evaluation: Evaluation = { patient: { patient_id: 'synthetic-patient', evidence: [] }, assessment: { uncertainty: '1', decisions: [{ trial_id: 'synthetic-trial', decision: 'unresolved', assessment: { context: { as_of: '2026-10-23T12:00:00Z' }, assessments: [node], criteria_set: { source_snapshot: 'synthetic://test' } } }] }, candidates: [{ item_id: 'record', cost: '1', depends_on: [], description: 'Synthetic review', existing_record: { record_id: 'record', reference: 'synthetic://record' }, probability_basis: 'Synthetic assumption', outcomes: [{ outcome_id: 'positive', probability: '1', description: 'Synthetic positive' }] }], assumptions: ['Synthetic assumption'], cost_unit: 'synthetic units', trials: [{ bindings: [{ clinical_attribute: 'ER', criterion: node.criterion }] }], plan: { selected_items: ['record'], spent: '1', expected_reduction: '1', expected_utility: '1', expected_error_bound: '0', risk_weight: '0' }, spent: '0', remaining_budget: '2', plan_scope: 'nonadaptive', next_review: null, reliability: null, dependence_groups: [] }

function renderApp() { render(<App />); fireEvent.click(screen.getByRole('button', { name: 'Research Tools' })) }

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith('/health') ? { status: 'ok' } : url.endsWith('/research/cases') ? [{ case_id: 'synthetic-test', trial_count: 1, review_count: 1, budgets: ['1', '2'], unsupported: null }] : url.endsWith('/research/trials') ? { trials: [], warnings: [] } : evaluation })))
})

test('displays every five-state label', () => {
  const states: State[] = ['satisfied', 'violated', 'unknown', 'temporal', 'conflict']
  render(<>{states.map(state => <StateBadge key={state} state={state} />)}</>)
  states.forEach(state => expect(screen.getByText(state)).toBeInTheDocument())
})

test('preserves original compound text and nested conditions', () => {
  render(<CriterionCard node={{ ...node, criterion_id: 'root', criterion: { ...node.criterion, original_text: 'SYNTHETIC A AND (B OR C)', logical_operator: 'AND' }, dependencies: [node] }} />)
  expect(screen.getByText('SYNTHETIC A AND (B OR C)')).toBeInTheDocument()
  expect(screen.getByLabelText('Logical dependencies')).toHaveTextContent('SYNTHETIC exclusion condition')
})

test('dashboard connects and evidence keeps missing observations explicit', async () => {
  renderApp()
  await screen.findByRole('heading', { name: 'synthetic-test' })
  fireEvent.click(screen.getByRole('button', { name: /Patient evidence/ }))
  expect(await screen.findByText('No observed evidence in this synthetic case.')).toBeInTheDocument()
  expect(screen.getByText(/ER\. Assay compatibility/)).toBeInTheDocument()
})

test('keeps exclusion polarity separate from criterion state', async () => {
  renderApp()
  await screen.findByRole('heading', { name: 'synthetic-test' })
  fireEvent.click(screen.getByRole('button', { name: /Criterion assessments/ }))
  expect(await screen.findByText('Exclusion conditions')).toBeInTheDocument()
  expect(screen.getByText('SYNTHETIC exclusion condition')).toBeInTheDocument()
})

test('sends hypothetical review history and resets without writing evidence locally', async () => {
  renderApp()
  await screen.findByRole('heading', { name: 'synthetic-test' })
  fireEvent.click(screen.getByRole('button', { name: /Evidence prioritization/ }))
  fireEvent.change(await screen.findByLabelText('Simulated report for record'), { target: { value: 'positive' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply simulated review record' }))
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('/evaluate'), expect.objectContaining({ body: expect.stringContaining('"record":"positive"') })))
  fireEvent.click(screen.getByText('Reset hypothetical reviews'))
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ body: expect.stringContaining('"outcomes":{}') })))
})

test('shows API failures without displaying stale assessments', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: !url.includes('/evaluate'), status: 409, json: async () => url.includes('/evaluate') ? { detail: 'unsupported synthetic model' } : url.endsWith('/health') ? { status: 'ok' } : url.endsWith('/cases') ? [{ case_id: 'synthetic-test', trial_count: 1, review_count: 1, budgets: ['1'], unsupported: null }] : { trials: [], warnings: [] } })))
  renderApp()
  expect(await screen.findByRole('alert')).toHaveTextContent('unsupported synthetic model')
})

test('algorithm selection delegates to the backend', async () => {
  renderApp()
  await screen.findByRole('heading', { name: 'synthetic-test' })
  fireEvent.click(screen.getByRole('button', { name: /Evidence prioritization/ }))
  fireEvent.change(screen.getByLabelText('Algorithm'), { target: { value: 'risk_exact' } })
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('/evaluate'), expect.objectContaining({ body: expect.stringContaining('"algorithm":"risk_exact"') })))
})

test('trial explorer preserves source text and original links after explicit selection', async () => {
  const originalFetch = fetch
  const trial = { nct_id: 'NCT00000001', title: 'Explicit synthetic fixture', recruitment_status: null, conditions: [], eligibility_criteria: 'SYNTHETIC original eligibility text', source_url: 'https://clinicaltrials.gov/study/NCT00000001', snapshot: 'synthetic/response.json', retrieved_at: null, is_synthetic: true }
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/research/trials')) return { ok: true, json: async () => ({ trials: [trial], warnings: [] }) }
    if (url.includes('/saved-trials/')) return { ok: true, json: async () => ({ source: { nct_id: trial.nct_id, text: trial.eligibility_criteria, source_url: trial.source_url, source_snapshot: 'data/raw/trials/synthetic/response.json', retrieval_timestamp: null, sha256: 'a'.repeat(64), is_synthetic: true }, snapshots: [trial], warnings: [], mock_version: 'verbatim-sections-v1' }) }
    return originalFetch(url, options)
  }))
  renderApp()
  fireEvent.click(screen.getByRole('button', { name: 'Source fixtures' }))
  expect(await screen.findByText('Select a study to inspect')).toBeInTheDocument()
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect extraction for NCT00000001' }))
  expect(await screen.findByText('SYNTHETIC original eligibility text')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Original ClinicalTrials.gov record' })).toHaveAttribute('href', trial.source_url)
})

test('overview uses loaded public records and distinguishes synthetic source fixtures', async () => {
  const originalFetch = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.endsWith('/research/trials') ? { ok: true, json: async () => ({ trials: [
    { nct_id: 'NCT00000001', title: 'Public record display fixture', recruitment_status: 'COMPLETED', conditions: [], snapshot: 'saved/response.json', snapshot_count: 2, retrieved_at: '2026-10-23T12:00:00Z', is_synthetic: null },
    { nct_id: 'NCT00000002', title: 'Explicit synthetic record fixture', recruitment_status: null, conditions: [], snapshot: 'synthetic/response.json', snapshot_count: 1, retrieved_at: null, is_synthetic: true },
  ], warnings: [] }) } : originalFetch(url, options)))
  renderApp()
  await screen.findByText('Public record display fixture')
  expect(screen.getByLabelText('Saved public study count')).toHaveTextContent('01')
  expect(screen.getByText('3 saved study versions / 1 synthetic source fixtures')).toBeInTheDocument()
  expect(screen.getByText('Synthetic fixture')).toBeInTheDocument()
  const status = screen.getByRole('region', { name: 'Workspace status' })
  expect(within(status).getByText('23 Oct 2026')).toBeInTheDocument()
  expect(within(status).getByText('Mock by default')).toBeInTheDocument()
  expect(screen.queryByText('No inference provider connected')).not.toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/extractions'))).toBe(false)
})

test('loading the source library does not present a fabricated zero count', async () => {
  const originalFetch = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.endsWith('/research/trials')
    ? new Promise<Response>(() => {}) : originalFetch(url, options)))
  renderApp()
  await screen.findByRole('heading', { name: 'synthetic-test' })
  expect(screen.getByLabelText('Saved public study count')).toHaveTextContent('\u2014')
  expect(screen.getByText('Loading source library')).toBeInTheDocument()
  expect(screen.queryByText('0 saved study versions')).not.toBeInTheDocument()
})

test('overview scenario filtering has an explicit empty state and clear action', async () => {
  renderApp()
  await screen.findByRole('heading', { name: 'synthetic-test' })
  fireEvent.change(screen.getByLabelText('Filter scenarios'), { target: { value: 'no-such-scenario' } })
  expect(screen.getByText('No matching scenarios')).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'synthetic-test' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Clear filter' }))
  expect(screen.getByRole('heading', { name: 'synthetic-test' })).toBeInTheDocument()
})

test('overview links navigate without inferring or extracting real eligibility', async () => {
  renderApp()
  await screen.findByRole('heading', { name: 'synthetic-test' })
  fireEvent.click(screen.getByRole('button', { name: 'Explore trials' }))
  const heading = screen.getByRole('heading', { name: 'Explore Trials', level: 1 })
  expect(heading).toHaveFocus()
  expect(screen.getByRole('button', { name: 'Explore Trials' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('button', { name: 'Home' })).not.toHaveAttribute('aria-current')
  expect(document.title).toBe('Explore Trials | TrialLens-TNBC')
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/extractions'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Research Tools' }))
  fireEvent.click(screen.getByRole('button', { name: 'Patient evidence' }))
  expect(screen.getByRole('heading', { name: 'Research Tools', level: 1 })).toHaveFocus()
})

test('mobile navigation manages focus, traps tab and closes with Escape', async () => {
  renderApp()
  await screen.findByRole('heading', { name: 'synthetic-test' })
  const menu = screen.getByRole('button', { name: 'Open navigation' })
  fireEvent.click(menu)
  expect(menu).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('main', { hidden: true })).toHaveAttribute('inert')
  const brand = screen.getByRole('button', { name: 'TrialLens home' })
  expect(brand).toHaveFocus()
  fireEvent.keyDown(brand, { key: 'Tab', shiftKey: true })
  expect(screen.getByRole('button', { name: 'Research Tools' })).toHaveFocus()
  fireEvent.keyDown(document.activeElement!, { key: 'Tab' })
  expect(brand).toHaveFocus()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(menu).toHaveFocus()
  expect(menu).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByRole('main')).not.toHaveAttribute('inert')
})

test('overview counts top-level states without double-counting nested conditions', async () => {
  const originalFetch = fetch
  const updated = structuredClone(evaluation)
  updated.assessment.decisions[0].assessment.assessments = [
    { ...node, dependencies: [{ ...node, criterion_id: 'nested-condition' }] },
    { ...node, criterion_id: 'satisfied-condition', state: 'satisfied' },
    { ...node, criterion_id: 'temporal-condition', state: 'temporal' },
  ]
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.includes('/evaluate')
    ? { ok: true, json: async () => updated } : originalFetch(url, options)))
  renderApp()
  const counts = await screen.findByLabelText('Synthetic criterion state counts')
  expect(within(counts).getByLabelText('unknown criteria')).toHaveTextContent('1')
  expect(within(counts).getByLabelText('satisfied criteria')).toHaveTextContent('1')
  expect(within(counts).getByLabelText('temporal criteria')).toHaveTextContent('1')
  expect(within(counts).getByLabelText('violated criteria')).toHaveTextContent('0')
  fireEvent.click(screen.getByText('How to read these states'))
  expect(screen.getByText(/A satisfied exclusion condition is a blocker/)).toBeInTheDocument()
})

test('source errors remain visible and retry uses existing endpoints', async () => {
  const originalFetch = fetch
  let failing = true
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.endsWith('/research/trials') && failing
    ? { ok: false, status: 500, json: async () => ({ detail: 'Saved source storage unavailable' }) } : originalFetch(url, options)))
  renderApp()
  expect(await screen.findByRole('alert')).toHaveTextContent('Saved source storage unavailable')
  expect(screen.getByLabelText('Saved public study count')).toHaveTextContent('\u2014')
  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await screen.findByText('No saved protocols')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Saved public study count')).toHaveTextContent('00')
})

test('skip link activation transfers focus to content and does not remain focused while browsing', async () => {
  renderApp()
  await screen.findByRole('heading', { name: 'synthetic-test' })
  const skip = screen.getByRole('link', { name: 'Skip to content' })
  expect(skip).toHaveAttribute('href', '#workspace-content')
  expect(skip).not.toHaveFocus()
  skip.focus()
  expect(skip).toHaveFocus()
  fireEvent.click(skip)
  expect(document.getElementById('workspace-content')).toHaveFocus()
  expect(skip).not.toHaveFocus()
  fireEvent.click(screen.getByRole('button', { name: 'Explore Trials' }))
  expect(screen.getByRole('heading', { name: 'Explore Trials', level: 1 })).toHaveFocus()
  expect(skip).not.toHaveFocus()
})
