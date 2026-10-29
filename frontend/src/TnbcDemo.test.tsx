import { openResearchSection, openDemo } from './testNavigation'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import fixture from './fixtures/tnbc_demo.json'

const researchIds = ['synthetic-breadth-versus-resolution', 'synthetic-prerequisite-records', 'ratio_trap', 'complementarity', 'adaptive_branch', 'noisy_review', 'misspecified_reliability', 'correlated_duplicates', 'overlap_without_joint']

function openLegacy(name: string) {
  const steps: Record<string, string> = { 'Patient evidence': 'Explore patient evidence', 'Criterion assessments': 'Understand criterion uncertainty', 'Evidence prioritization': 'Prioritize existing record reviews' }
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Demo steps' })).getByRole('button', { name: new RegExp(steps[name]) }))
  const summary = screen.getByText('Research Details', { selector: 'summary' })
  if (!summary.parentElement?.hasAttribute('open')) fireEvent.click(summary)
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const body = options?.body ? JSON.parse(String(options.body)) : {}
    let data: unknown
    if (url.endsWith('/health')) data = { status: 'ok' }
    else if (url.endsWith('/research/trials')) data = {
      trials: [{ nct_id: 'NCT00000001', title: 'Source display fixture', recruitment_status: 'RECRUITING', conditions: [], eligibility_criteria: 'Unmodified source display fixture', source_url: 'https://clinicaltrials.gov/study/NCT00000001', snapshot: 'retrieved/response.json', retrieved_at: '2026-10-23T12:00:00Z', is_synthetic: null }], warnings: [],
    }
    else if (url.includes('/saved-trials/')) data = { source: { nct_id: 'NCT00000001', text: 'Unmodified source display fixture', source_url: 'https://clinicaltrials.gov/study/NCT00000001', source_snapshot: 'data/raw/trials/retrieved/response.json', retrieval_timestamp: '2026-10-23T12:00:00Z', sha256: 'a'.repeat(64), is_synthetic: null }, snapshots: [{ snapshot: 'retrieved/response.json', retrieved_at: '2026-10-23T12:00:00Z' }], warnings: [], mock_version: 'verbatim-sections-v1' }
    else if (url.endsWith('/research/cases')) data = researchIds.map(case_id => ({ case_id, trial_count: 1, review_count: 1, budgets: ['1', '2'], unsupported: case_id === 'overlap_without_joint' ? 'missing_joint_distribution' : null }))
    else if (url.endsWith('/tnbc/cases')) data = fixture.catalog
    else if (url.includes('/tnbc/cases/tnbc-conflicting-records/')) data = fixture.conflict
    else if (url.includes('/tnbc/cases/tnbc-stale-labs/')) data = fixture.stale
    else if (url.includes('/tnbc/cases/')) data = body.outcomes?.['review-pdl1-report'] ? fixture.reviewed : fixture.baseline
    else data = { ...fixture.baseline, case_title: undefined, case_description: undefined, display_labels: undefined, protocol_titles: undefined }
    return { ok: true, json: async () => structuredClone(data) }
  }))
})

async function openTnbcCase(caseId = 'tnbc-record-gaps') {
  render(<App />)
  openDemo()
  fireEvent.click(screen.getByText('Advanced Mode', { selector: 'summary' }))
  await waitFor(() => expect(screen.getByLabelText('Fictional TNBC case')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Fictional TNBC case'), { target: { value: caseId } })
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining(`/tnbc/cases/${caseId}/evaluate`), expect.any(Object)))
  await waitFor(() => expect(screen.queryByText('Evaluating synthetic portfolio…')).not.toBeInTheDocument())
}

test('keeps four TNBC cases separate and preserves all nine research scenario choices', async () => {
  await openTnbcCase()
  expect(within(screen.getByLabelText('Fictional TNBC case')).getAllByRole('option')).toHaveLength(4)
  fireEvent.change(screen.getByLabelText('Application mode'), { target: { value: 'research' } })
  const selector = await screen.findByLabelText('Synthetic portfolio')
  await waitFor(() => expect(within(selector).getAllByRole('option')).toHaveLength(9))
  researchIds.forEach(id => expect(within(selector).getByRole('option', { name: new RegExp(id) })).toBeInTheDocument())
  expect(screen.queryByLabelText('Fictional TNBC case')).not.toBeInTheDocument()
})

test('shows assay-specific biomarker labels, missingness, specimen and source provenance', async () => {
  await openTnbcCase()
  openLegacy('Patient evidence')
  expect(screen.getAllByRole('heading', { name: 'Estrogen receptor (ER)' }).length).toBeGreaterThan(0)
  const timeline = screen.getByRole('navigation', { name: 'Timeline dates' }).parentElement!
  fireEvent.click(within(timeline).getByRole('button', { name: /PD-L1 expression.*22C3/ }))
  const inspector = screen.getByRole('region', { name: 'Evidence record inspector' })
  expect(within(inspector).getByText('Combined positive score (CPS)')).toBeInTheDocument()
  expect(within(inspector).getByText('unavailable')).toBeInTheDocument()
  expect(within(inspector).getByText('Fictional metastatic tumor biopsy')).toBeInTheDocument()
  fireEvent.click(within(inspector).getByText('Original record provenance'))
  expect(within(inspector).getByText('synthetic://tnbc/records/PD-L1-baseline')).toBeVisible()
  fireEvent.click(within(timeline).getByRole('button', { name: /PD-L1 expression.*SP142/ }))
  expect(within(inspector).getByText(/no conversion or substitution/)).toBeInTheDocument()
})

test('renders unknown, satisfied and violated conditions without flattening compound rules', async () => {
  await openTnbcCase()
  openLegacy('Criterion assessments')
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect demo-pdl1-pdl1' }))
  const inspector = screen.getByRole('region', { name: 'Criterion reasoning inspector' })
  expect(within(inspector).getAllByText('unknown', { selector: '.badge' }).length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('button', { name: 'Inspect demo-pdl1-tnbc' }))
  expect(within(inspector).getAllByLabelText('Logical dependencies')).toHaveLength(2)
  expect(within(inspector).getByText('FICTIONAL DEMO ONLY: (ER < 1% AND PR < 1%) AND an explicitly reviewed HER2-negative interpretation.')).toBeInTheDocument()
  expect(within(screen.getByRole('button', { name: 'Inspect demo-pdl1-er' }).closest('tr')!).getByText('satisfied')).toBeInTheDocument()
  expect(within(screen.getByRole('button', { name: 'Inspect demo-pdl1-cns' }).closest('tr')!).getByText('violated')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Original ClinicalTrials.gov record' })).not.toBeInTheDocument()
})

test('renders temporal evidence under its explicit fictional source window', async () => {
  await openTnbcCase('tnbc-stale-labs')
  openLegacy('Criterion assessments')
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect demo-brca-hemoglobin' }))
  const node = screen.getByRole('region', { name: 'Criterion reasoning inspector' })
  expect(within(node).getAllByText('temporal', { selector: '.badge' }).length).toBeGreaterThan(0)
  expect(node).toHaveTextContent('within 14 days')
})

test('renders contradictions and satisfied exclusion conditions independently', async () => {
  await openTnbcCase('tnbc-conflicting-records')
  openLegacy('Criterion assessments')
  expect(within((await screen.findByRole('button', { name: 'Inspect demo-brca-ecog' })).closest('tr')!).getByText('conflict')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Inspect demo-pdl1-checkpoint' }))
  const exclusion = screen.getByRole('region', { name: 'Criterion reasoning inspector' })
  expect(exclusion).toHaveTextContent('excluding condition observed')
  expect(screen.getByText(/Engine portfolio result: observed blocker/)).toBeInTheDocument()
  expect(screen.getAllByText('Exclusion conditions')).toHaveLength(2)
})

test('uses meaningful existing-record actions and resets hypothetical updates', async () => {
  await openTnbcCase()
  openLegacy('Evidence prioritization')
  expect(await screen.findAllByText('Read the existing fictional 22C3 CPS pathology report')).not.toHaveLength(0)
  fireEvent.change(await screen.findByLabelText('Simulated report for review-pdl1-report'), { target: { value: 'cps-15' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply simulated review review-pdl1-report' }))
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('/tnbc/cases/tnbc-record-gaps/evaluate'), expect.objectContaining({ body: expect.stringContaining('"review-pdl1-report":"cps-15"') })))
  openLegacy('Patient evidence')
  fireEvent.click(await screen.findByRole('button', { name: /PD-L1 expression.*22C3/ }))
  fireEvent.click(screen.getByText('Original record provenance'))
  expect(screen.getByText('synthetic://tnbc/records/PD-L1-review')).toBeVisible()
  fireEvent.click(screen.getByText('Reset hypothetical reviews'))
  fireEvent.click(await screen.findByRole('button', { name: /PD-L1 expression.*22C3/ }))
  fireEvent.click(screen.getByText('Original record provenance'))
  expect(screen.getByText('synthetic://tnbc/records/PD-L1-baseline')).toBeVisible()
  expect(screen.queryByText('synthetic://tnbc/records/PD-L1-review')).not.toBeInTheDocument()
})

test('public source view reads saved text directly and keeps extraction optional', async () => {
  await openTnbcCase()
  openResearchSection('Browse saved trials')
  fireEvent.click(await screen.findByRole('button', { name: /NCT00000001/ }))
  expect(screen.getByRole('link', { name: /Read the ClinicalTrials.gov record/ })).toHaveAttribute('href', 'https://clinicaltrials.gov/study/NCT00000001')
  expect(screen.getByText('Unmodified source display fixture', { selector: 'blockquote' })).toBeInTheDocument()
  expect(screen.queryByText('Sources & model limitations')).not.toBeInTheDocument()
  expect(screen.queryByText('Synthetic patient workspace')).not.toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/extractions'))).toBe(false)
})

test('switching cases resets evidence inspection and keeps fictional context explicit', async () => {
  await openTnbcCase()
  openLegacy('Patient evidence')
  fireEvent.change(screen.getByLabelText('Evidence availability / limitation'), { target: { value: 'Missing' } })
  fireEvent.change(screen.getByLabelText('Fictional TNBC case'), { target: { value: 'tnbc-conflicting-records' } })
  await waitFor(() => expect(screen.getByLabelText('Calculated scenario')).toHaveTextContent('Conflicting performance records'))
  expect(screen.getByLabelText('Evidence availability / limitation')).toHaveValue('All evidence')
  fireEvent.change(screen.getByLabelText('Evidence availability / limitation'), { target: { value: 'Conflicting' } })
  expect(screen.getByRole('region', { name: 'Evidence record inspector' })).toHaveTextContent('Conflicting source records')
  expect(screen.getByText('FICTIONAL TNBC DEMO')).toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/extractions'))).toBe(false)
})

test('criterion evidence navigation selects the linked record and preserves budget and review history', async () => {
  await openTnbcCase()
  openLegacy('Evidence prioritization')
  fireEvent.change(screen.getByLabelText('Total review budget'), { target: { value: '3' } })
  fireEvent.change(await screen.findByLabelText('Simulated report for review-pdl1-report'), { target: { value: 'cps-15' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply simulated review review-pdl1-report' }))
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('/evaluate'), expect.objectContaining({ body: expect.stringContaining('"review-pdl1-report":"cps-15"') })))
  openLegacy('Criterion assessments')
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect demo-pdl1-pdl1' }))
  fireEvent.click(screen.getByRole('button', { name: 'Inspect evidence fictional-PD-L1-review' }))
  const inspector = await screen.findByRole('region', { name: 'Evidence record inspector' })
  expect(within(inspector).getByRole('heading', { name: 'PD-L1 expression' })).toBeInTheDocument()
  expect(inspector).toHaveTextContent('15')
  await waitFor(() => expect(inspector).toHaveFocus())
  expect(screen.getByLabelText('Total review budget')).toHaveValue(3)
  openLegacy('Evidence prioritization')
  expect(screen.getByLabelText('Simulated report for review-pdl1-report')).toHaveValue('cps-15')
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/extractions'))).toBe(false)
})

test('case switching clears reasoning filters and changes the actual backend trace', async () => {
  await openTnbcCase()
  openLegacy('Criterion assessments')
  fireEvent.change(screen.getByLabelText('Assessment state'), { target: { value: 'unknown' } })
  fireEvent.change(screen.getByLabelText('Fictional TNBC case'), { target: { value: 'tnbc-conflicting-records' } })
  await waitFor(() => expect(screen.getByLabelText('Calculated scenario')).toHaveTextContent('Conflicting performance records'))
  expect(screen.getByLabelText('Assessment state')).toHaveValue('All states')
  fireEvent.click(screen.getByRole('button', { name: 'Inspect demo-brca-ecog' }))
  expect(screen.getByRole('region', { name: 'Criterion reasoning inspector' })).toHaveTextContent('contradictory_observations')
})

test('adaptive simulation requests a fresh next review and preserves record selection across pages', async () => {
  const originalFetch = fetch
  const originalRecords = structuredClone(fixture.baseline.patient.evidence)
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (!url.includes('/tnbc/cases/') || !url.endsWith('/evaluate')) return originalFetch(url, options)
    const body = JSON.parse(String(options?.body))
    const reviewed = Boolean(body.outcomes?.['review-pdl1-report'])
    const data = structuredClone(reviewed ? fixture.reviewed : fixture.baseline)
    const next = reviewed ? 'review-germline-report' : 'review-pdl1-report'
    return { ok: true, json: async () => ({ ...data, next_review: body.algorithm === 'adaptive_replan' ? next : null, plan_scope: 'conditional nonadaptive forecast; reveal one review then replan', remaining_budget: String(Number(body.budget) - Number(data.spent)) }) }
  }))
  await openTnbcCase()
  openLegacy('Evidence prioritization')
  fireEvent.change(screen.getByLabelText('Total review budget'), { target: { value: '3' } })
  fireEvent.change(screen.getByLabelText('Algorithm'), { target: { value: 'adaptive_replan' } })
  const proposal = await screen.findByRole('region', { name: 'Next proposed review' })
  await waitFor(() => expect(proposal).toHaveTextContent('Read the existing fictional 22C3 CPS pathology report'))
  expect(screen.getAllByText(/This is not a globally optimal adaptive policy/).length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('button', { name: 'Inspect review review-pdl1-report' }))
  fireEvent.change(screen.getByLabelText('Simulated report for review-pdl1-report'), { target: { value: 'cps-15' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply simulated review review-pdl1-report' }))
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('/evaluate'), expect.objectContaining({ body: expect.stringContaining('"review-pdl1-report":"cps-15"') })))
  const updated = await screen.findByRole('region', { name: 'Next proposed review' })
  expect(updated).toHaveTextContent(fixture.reviewed.candidates.find(item => item.item_id === 'review-germline-report')!.description)
  expect(screen.getByRole('region', { name: 'Review budget accounting' })).toHaveTextContent('Already spent1Remaining2')
  openLegacy('Patient evidence')
  openLegacy('Evidence prioritization')
  expect(screen.getByRole('region', { name: 'Review record inspector' })).toHaveTextContent('review-pdl1-report')
  expect(screen.getByLabelText('Total review budget')).toHaveValue(3)
  expect(screen.getByLabelText('Simulated report for review-pdl1-report')).toHaveValue('cps-15')
  fireEvent.click(screen.getByRole('button', { name: 'Reset hypothetical reviews' }))
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ body: expect.stringContaining('"outcomes":{}') })))
  expect(await screen.findByRole('region', { name: 'Next proposed review' })).toHaveTextContent('Read the existing fictional 22C3 CPS pathology report')
  expect(fixture.baseline.patient.evidence).toEqual(originalRecords)
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/extractions'))).toBe(false)
})
