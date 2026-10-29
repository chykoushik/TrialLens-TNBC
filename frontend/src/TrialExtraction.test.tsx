import { openResearchSection } from './testNavigation'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import TrialExtraction from './TrialExtraction'

const text = 'Inclusion Criteria:\n\nSynthetic marker A\n'
const latest = {
  nct_id: 'NCT00000001', text, source_url: 'https://clinicaltrials.gov/study/NCT00000001',
  source_snapshot: 'data/raw/trials/latest/response.json', retrieval_timestamp: '2026-10-23T12:00:00Z',
  sha256: 'a'.repeat(64), is_synthetic: true,
}
const older = { ...latest, source_snapshot: 'data/raw/trials/older/response.json', retrieval_timestamp: '2026-10-20T12:00:00Z', sha256: 'b'.repeat(64) }
const span = { start: text.indexOf('Synthetic marker A'), end: text.indexOf('Synthetic marker A') + 'Synthetic marker A'.length }
const candidate = {
  criteria: [{ criterion_id: 'mock-section-1', original_text: 'Synthetic marker A', criterion_type: 'inclusion', cohort: null, logical_operator: null, dependencies: null, biomarker: null, assay: null, comparator: null, threshold: null, unit: null, temporal_constraint: null }],
  evidence: [{ criterion_id: 'mock-section-1', original_span: span, polarity_span: { start: 0, end: 19 }, fields: {} }],
}
const report = {
  source: latest, manifest: { status: 'validation_failed', prompt_version: 'trial-criteria-v1', requested_model: 'mock-no-model', returned_model: 'mock-no-model', mode: 'mock' },
  mock_version: 'verbatim-sections-v1', validated: null, candidate,
  validation_errors: [{ code: 'unresolved_logical_operator', criterion_id: 'mock-section-1', field: null }],
  unsupported_criteria: [{ criterion_id: 'mock-section-1', reason: 'unreviewed_semantics_no_execution_mapping' }],
  assessment_allowed: false, assessment_block_reason: 'Human-reviewed executable bindings and compatible synthetic evidence are required.', output_directory: 'results/extraction/synthetic-ui-fixture',
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => {
    if (url.endsWith('/extractions')) return structuredClone(report)
    const source = url.includes('older%2F') ? older : latest
    return { source, mock_version: 'verbatim-sections-v1', warnings: [], snapshots: [
      { snapshot: 'latest/response.json', retrieved_at: latest.retrieval_timestamp },
      { snapshot: 'older/response.json', retrieved_at: older.retrieval_timestamp },
    ] }
  } })))
})

function renderExtraction() {
  render(<TrialExtraction nctId="NCT00000001" snapshot="latest/response.json" />)
}

test('snapshot choices remain available after a source failure and support repeated recovery', async () => {
  renderExtraction()
  await screen.findByText(latest.sha256)
  const originalFetch = fetch
  let failed = true
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => failed && url.includes('older%2F')
    ? { ok: false, status: 500, json: async () => ({ detail: 'Saved snapshot unavailable' }) } : originalFetch(url, options)))
  fireEvent.change(screen.getByLabelText('Snapshot history'), { target: { value: 'older/response.json' } })
  await screen.findByText('Saved source unavailable')
  expect(screen.getByLabelText('Snapshot history')).toBeEnabled()
  fireEvent.change(screen.getByLabelText('Snapshot history'), { target: { value: 'latest/response.json' } })
  await screen.findByText(latest.sha256)
  failed = false
  fireEvent.change(screen.getByLabelText('Snapshot history'), { target: { value: 'older/response.json' } })
  await screen.findByText(older.sha256)
  fireEvent.change(screen.getByLabelText('Snapshot history'), { target: { value: 'latest/response.json' } })
  await screen.findByText(latest.sha256)
  expect(screen.getByLabelText('Snapshot history')).toBeEnabled()
})

test('extraction mode can toggle repeatedly without approval or inference and unlocks after a failed mock request', async () => {
  const originalFetch = fetch
  let rejectRun!: () => void
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/extractions')) return new Promise((_resolve, reject) => { rejectRun = () => reject(new Error('Software fixture request failed')) })
    const response = await originalFetch(url, options)
    const data = await response.json()
    return { ok: true, json: async () => ({ ...data, configuration: { ready: true, model: 'software-fixture-model', errors: [] } }) }
  }))
  renderExtraction()
  const mode = await screen.findByLabelText('Extraction mode')
  for (const value of ['live', 'mock', 'live', 'mock']) {
    mode.focus()
    fireEvent.keyDown(mode, { key: 'ArrowDown' })
    fireEvent.change(mode, { target: { value } })
    expect(mode).toHaveValue(value)
    expect(mode).toBeEnabled()
    if (value === 'live') expect(screen.getByLabelText('Approve one paid live extraction of this snapshot')).not.toBeChecked()
  }
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/extractions'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Run mock extraction' }))
  expect(mode).toBeDisabled()
  expect(screen.getByLabelText('Snapshot history')).toBeDisabled()
  expect(mode).toHaveAccessibleDescription(/locked only while/)
  await act(async () => { rejectRun() })
  await screen.findByText('Software fixture request failed')
  expect(mode).toBeEnabled()
  expect(screen.getByLabelText('Snapshot history')).toBeEnabled()
  fireEvent.change(mode, { target: { value: 'live' } })
  fireEvent.change(mode, { target: { value: 'mock' } })
  expect(mode).toHaveValue('mock')
  expect(JSON.parse(String(vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith('/extractions'))![1]?.body)).mode).toBe('mock')
})

test('snapshot selector survives pending loads and rejects obsolete responses in the same inspector', async () => {
  renderExtraction()
  await screen.findByText(latest.sha256)
  const history = screen.getByLabelText('Snapshot history')
  const originalFetch = fetch
  let resolveOlder!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.includes('older%2F')
    ? { ok: true, json: () => new Promise(resolve => { resolveOlder = resolve }) } : originalFetch(url, options)))
  fireEvent.change(history, { target: { value: 'older/response.json' } })
  await waitFor(() => expect(typeof resolveOlder).toBe('function'))
  expect(history).toBeEnabled()
  expect(screen.getByLabelText('Snapshot history')).toBe(history)
  fireEvent.change(history, { target: { value: 'latest/response.json' } })
  await screen.findByText(latest.sha256)
  await act(async () => { resolveOlder({ source: older, snapshots: [], warnings: [], mock_version: 'verbatim-sections-v1' }) })
  expect(history).toHaveValue('latest/response.json')
  expect(screen.queryByText(older.sha256)).not.toBeInTheDocument()
  fireEvent.change(history, { target: { value: 'latest/response.json' } })
  expect(screen.getByLabelText('Exact original eligibility text')).toBeInTheDocument()
})

test('preserves original source, snapshot identity and history selection', async () => {
  renderExtraction()
  await screen.findByText(latest.sha256)
  const history = screen.getByLabelText('Snapshot history')
  expect(screen.getByText(/Synthetic marker A/)).toBeInTheDocument()
  expect(screen.getByText(latest.sha256)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Original ClinicalTrials.gov record/ })).toHaveAttribute('href', latest.source_url)
  fireEvent.change(history, { target: { value: 'older/response.json' } })
  await screen.findByText(older.sha256)
  fireEvent.click(screen.getByText('Run mock extraction'))
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith('/api/saved-trials/NCT00000001/extractions', expect.objectContaining({
    body: JSON.stringify({ snapshot: 'older/response.json', snapshot_sha256: older.sha256, mode: 'mock', mock_version: 'verbatim-sections-v1' }),
  })))
})

test('labels mock output and shows unsupported criteria and source-span errors without repairs', async () => {
  renderExtraction()
  fireEvent.click(await screen.findByText('Run mock extraction'))
  expect(await screen.findByText('validation_failed')).toBeInTheDocument()
  expect(screen.getByText('unresolved_logical_operator')).toBeInTheDocument()
  expect(screen.getByText(/No validated criteria set/)).toBeInTheDocument()
  expect(screen.getByText(/unreviewed_semantics_no_execution_mapping/)).toBeInTheDocument()
  fireEvent.click(screen.getByText('Unvalidated mock candidates and source spans'))
  expect(screen.getByText(/"original_span"/)).toHaveTextContent('"threshold": null')
  expect(screen.getByText('Assessment blocked')).toBeInTheDocument()
  expect(screen.getByText(/not verified NVIDIA or Nebius inference/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /assess patient/i })).not.toBeInTheDocument()
})

test('validated structured output still requires reviewed executable mappings', async () => {
  const originalFetch = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.endsWith('/extractions') ? {
    ok: true, json: async () => ({ ...report, manifest: { ...report.manifest, status: 'validated' }, validation_errors: [],
      validated: { nct_id: latest.nct_id, original_text: text, source_snapshot: latest.source_snapshot,
        criteria: [{ ...candidate.criteria[0], logical_operator: 'NONE' }] } }),
  } : originalFetch(url, options)))
  renderExtraction()
  fireEvent.click(await screen.findByText('Run mock extraction'))
  await screen.findByText('validated')
  expect(screen.getByText(/No structural or source-span validation errors/)).toBeInTheDocument()
  expect(screen.getByText(/"logical_operator": "NONE"/)).toBeInTheDocument()
  expect(screen.getByText('Assessment blocked')).toBeInTheDocument()
  expect(screen.getByText('Passed / review required')).toBeInTheDocument()
  expect(screen.getByText('Passed')).toBeInTheDocument()
})

test('reports HTTP failure without displaying an invented extraction', async () => {
  const originalFetch = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.endsWith('/extractions')
    ? { ok: false, status: 409, json: async () => ({ detail: 'Snapshot hash changed; reload the selected source' }) }
    : originalFetch(url, options)))
  renderExtraction()
  fireEvent.click(await screen.findByText('Run mock extraction'))
  expect(await screen.findByRole('alert')).toHaveTextContent('Snapshot hash changed')
  expect(screen.queryByLabelText('Extraction result')).not.toBeInTheDocument()
})

test('Trial Explorer connects an NCT selection to the extraction workflow', async () => {
  const originalFetch = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes('/saved-trials/')) return originalFetch(url, options)
    return { ok: true, json: async () => url.endsWith('/health') ? { status: 'ok' } : url.endsWith('/cases') ? [] : {
      trials: [{ nct_id: latest.nct_id, title: 'Explicit synthetic UI source fixture', conditions: [], recruitment_status: null,
        eligibility_criteria: text, source_url: latest.source_url, snapshot: 'latest/response.json', retrieved_at: latest.retrieval_timestamp, is_synthetic: true, snapshot_count: 2 }], warnings: [],
    } }
  }))
  render(<App />)
  openResearchSection()
  fireEvent.click(screen.getByRole('button', { name: 'Source fixtures' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect extraction for NCT00000001' }))
  expect(await screen.findByLabelText('Snapshot history')).toBeInTheDocument()
  expect((await screen.findByText('Versions available')).nextElementSibling).toHaveTextContent('2')
})

test('Inspect extraction opens a dedicated NCT02648477 workspace, including repeat clicks', async () => {
  const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
  const scrollIntoView = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView })
  try {
    const nctId = 'NCT02648477'
    let resolveSource!: (value: unknown) => void
    const sourceResponse = new Promise(resolve => { resolveSource = resolve })
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/saved-trials/')) return { ok: true, json: () => sourceResponse }
      return { ok: true, json: async () => url.endsWith('/health') ? { status: 'ok' } : url.endsWith('/cases') ? [] : {
        trials: [{ nct_id: nctId, title: 'Explicit synthetic UI display fixture', conditions: [], recruitment_status: null,
          eligibility_criteria: text, source_url: `https://clinicaltrials.gov/study/${nctId}`, snapshot: 'latest/response.json',
          retrieved_at: latest.retrieval_timestamp, is_synthetic: true }], warnings: [],
      } }
    }))
    render(<App />)
    openResearchSection()
  fireEvent.click(screen.getByRole('button', { name: 'Source fixtures' }))
    const button = await screen.findByRole('button', { name: `Inspect extraction for ${nctId}` })
    fireEvent.click(button)
    const panel = await screen.findByRole('region', { name: `Extraction panel for ${nctId}` })
    expect(panel).toBeVisible()
    expect(panel).toHaveFocus()
    expect(button).toHaveAttribute('aria-controls', panel.id)
    expect(button).toHaveAttribute('aria-pressed', 'true')
    expect(button.closest('tr')).not.toContainElement(panel)
    expect(within(panel).getByText('Loading exact saved source…')).toBeVisible()
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' })
    expect(fetch).toHaveBeenCalledWith(`/api/saved-trials/${nctId}?snapshot=latest%2Fresponse.json`, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/extractions'))).toBe(false)
    resolveSource({ source: { ...latest, nct_id: nctId }, snapshots: [{ snapshot: 'latest/response.json', retrieved_at: latest.retrieval_timestamp }], warnings: [], mock_version: 'verbatim-sections-v1' })
    expect(await within(panel).findByText(`Saved source loaded for ${nctId}.`)).toBeVisible()
    expect(within(panel).getByText(latest.sha256)).toBeVisible()
    expect(within(panel).getByText('Simulated extraction')).toBeVisible()
    expect(within(panel).getByText(/No extraction has been run/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Change study' }))
    expect(button).toHaveFocus()
    scrollIntoView.mockClear()
    button.focus()
    fireEvent.click(button)
    expect(panel).toHaveFocus()
    expect(scrollIntoView).toHaveBeenCalledOnce()
    expect(screen.getAllByRole('region', { name: `Extraction panel for ${nctId}` })).toHaveLength(1)
  } finally {
    if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll)
    else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
  }
})

test('source loading failures stay visible inside the extraction panel', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({ detail: 'Saved source unavailable' }) })))
  renderExtraction()
  expect(await screen.findByRole('alert')).toHaveTextContent('Saved source unavailable')
  expect(screen.getByLabelText('Saved-trial extraction')).toBeVisible()
  expect(screen.queryByText('Run mock extraction')).not.toBeInTheDocument()
})

test('empty eligibility text is explicit and cannot start extraction', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ source: { ...latest, text: '' }, snapshots: [], warnings: [], mock_version: 'verbatim-sections-v1' }) })))
  renderExtraction()
  expect(await screen.findByText('No eligibility text is available in this saved source.')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Run mock extraction' })).toBeDisabled()
})


test('live extraction requires explicit selection and approval, displays usage and consumes UI budget', async () => {
  const originalFetch = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/extractions')) return { ok: true, json: async () => ({ ...report,
      manifest: { ...report.manifest, mode: 'live', returned_model: 'nvidia/nemotron-3-super-120b-a12b',
        usage: { prompt_tokens: 100, completion_tokens: 200, total_tokens: 300 }, estimated_cost_usd: 0.00021 },
      validation_errors: [{ code: 'unsupported_conditional_or_exception' }] }) }
    const response = await originalFetch(url, options)
    const data = await response.json()
    return { ok: true, json: async () => ({ ...data, configuration: { ready: true, model: 'nvidia/nemotron-3-super-120b-a12b', errors: [] } }) }
  }))
  renderExtraction()
  const mode = await screen.findByLabelText('Extraction mode')
  expect(mode).toHaveValue('mock')
  fireEvent.change(mode, { target: { value: 'live' } })
  const button = screen.getByRole('button', { name: 'Run one live NVIDIA Nemotron extraction' })
  expect(button).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Operator access code'), { target: { value: 'operator-test-token' } })
  fireEvent.click(screen.getByLabelText('Approve one paid live extraction of this snapshot'))
  fireEvent.click(button)
  expect(await screen.findByText(/Token usage: input 100/)).toBeVisible()
  expect(screen.getByText(/Estimated cost: \$0.000210 USD/)).toBeVisible()
  expect(screen.getByText('unsupported_conditional_or_exception')).toBeVisible()
  expect(screen.getByText('Assessment blocked')).toBeVisible()
  expect(button).toBeDisabled()
  expect(fetch).toHaveBeenLastCalledWith('/api/saved-trials/NCT00000001/extractions', expect.objectContaining({
    body: JSON.stringify({ snapshot: 'latest/response.json', snapshot_sha256: latest.sha256, mode: 'live', mock_version: 'verbatim-sections-v1', live_approved: true }),
  }))
})

test('live extraction is disabled when server configuration is unavailable', async () => {
  renderExtraction()
  const mode = await screen.findByLabelText('Extraction mode')
  expect(mode).toHaveValue('mock')
  expect(screen.getByRole('option', { name: 'Live NVIDIA Nemotron (Nebius)' })).toBeDisabled()
})

test('selecting an unvalidated criterion highlights only its verified quote and scrolls it into view', async () => {
  const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
  const scroll = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll })
  try {
    renderExtraction()
    fireEvent.click(await screen.findByText('Run mock extraction'))
    fireEvent.click(await screen.findByRole('button', { name: 'Inspect criterion mock-section-1' }))
    const passage = screen.getByLabelText('Verified source passage')
    expect(passage).toHaveTextContent('Synthetic marker A')
    expect(screen.getByLabelText('Exact original eligibility text').textContent).toBe(text)
    expect(scroll).toHaveBeenCalledWith({ behavior: 'auto', block: 'center', inline: 'nearest' })
    expect(screen.getByText(/Exact source quote verified at characters/)).toBeInTheDocument()
    expect(screen.getByText('Not validated')).toBeInTheDocument()
    expect(screen.getByText('Accepted structure')).toBeInTheDocument()
    expect(screen.getByText('Request succeeded')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear highlight' }))
    expect(screen.queryByLabelText('Verified source passage')).not.toBeInTheDocument()
  } finally {
    if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll)
    else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
  }
})

test.each(['outside', 'negative', 'fractional', 'missing', 'duplicate_evidence', 'wrong_text', 'wrong_hash', 'wrong_snapshot', 'wrong_nct', 'duplicate_id'])('never highlights an unsafe span: %s', async mutation => {
  const changed = structuredClone(report)
  if (mutation === 'outside') changed.candidate.evidence[0].original_span.end = 100000
  if (mutation === 'negative') changed.candidate.evidence[0].original_span.start = -1
  if (mutation === 'fractional') changed.candidate.evidence[0].original_span.start = 1.5
  if (mutation === 'missing') changed.candidate.evidence = []
  if (mutation === 'duplicate_evidence') changed.candidate.evidence.push(structuredClone(changed.candidate.evidence[0]))
  if (mutation === 'wrong_text') changed.candidate.criteria[0].original_text = 'Synthetic marker B'
  if (mutation === 'wrong_hash') changed.source.sha256 = 'c'.repeat(64)
  if (mutation === 'wrong_snapshot') changed.source.source_snapshot = older.source_snapshot
  if (mutation === 'wrong_nct') changed.source.nct_id = 'NCT00000002'
  if (mutation === 'duplicate_id') changed.candidate.criteria.push(structuredClone(changed.candidate.criteria[0]))
  const originalFetch = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.endsWith('/extractions')
    ? { ok: true, json: async () => changed } : originalFetch(url, options)))
  renderExtraction()
  fireEvent.click(await screen.findByText('Run mock extraction'))
  fireEvent.click((await screen.findAllByRole('button', { name: 'Inspect criterion mock-section-1' }))[0])
  expect(screen.queryByLabelText('Verified source passage')).not.toBeInTheDocument()
  expect(screen.getByText(/No passage highlighted/)).toBeInTheDocument()
  expect(screen.getByLabelText('Exact original eligibility text').textContent).toBe(text)
})

test('Python Unicode spans select the second repeated passage after a non-BMP character', async () => {
  const unicodeText = 'Inclusion Criteria:\n\n🧬 Synthetic marker A\nSynthetic marker A\nExclusion Criteria:\nNo condition B'
  const secondStart = Array.from(unicodeText.slice(0, unicodeText.lastIndexOf('Synthetic marker A'))).length
  const unicodeSource = { ...latest, text: unicodeText }
  const unicodeCandidate = structuredClone(candidate)
  unicodeCandidate.evidence[0].original_span = { start: secondStart, end: secondStart + Array.from('Synthetic marker A').length }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith('/extractions')
    ? { ...report, source: unicodeSource, candidate: unicodeCandidate }
    : { source: unicodeSource, snapshots: [{ snapshot: 'latest/response.json', retrieved_at: latest.retrieval_timestamp }], warnings: [], mock_version: 'verbatim-sections-v1' } })))
  renderExtraction()
  fireEvent.click(await screen.findByText('Run mock extraction'))
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect criterion mock-section-1' }))
  const source = screen.getByLabelText('Exact original eligibility text')
  const mark = screen.getByLabelText('Verified source passage')
  const range = document.createRange()
  range.setStart(source, 0); range.setEndBefore(mark)
  expect(Array.from(range.toString()).length).toBe(secondStart)
  expect(mark.textContent).toBe('Synthetic marker A')
  expect(source.textContent).toBe(unicodeText)
  fireEvent.click(screen.getByRole('button', { name: 'Jump to exclusion' }))
  expect(source.querySelector('[data-section="exclusion"]')).toHaveFocus()
})

test('snapshot switching clears highlights and results without running extraction', async () => {
  renderExtraction()
  fireEvent.click(await screen.findByText('Run mock extraction'))
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect criterion mock-section-1' }))
  expect(screen.getByLabelText('Verified source passage')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Snapshot history'), { target: { value: 'older/response.json' } })
  await screen.findByText(older.sha256)
  expect(screen.queryByLabelText('Verified source passage')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Extraction result')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Extraction mode')).toHaveValue('mock')
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/extractions'))).toHaveLength(1)
  expect(screen.getByText('No extraction has been run for this snapshot.')).toBeInTheDocument()
})

test.each(['schema', 'provider'])('separates request success from %s failure', async type => {
  const originalFetch = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.endsWith('/extractions')
    ? { ok: true, json: async () => ({ ...report, candidate: null,
      manifest: { ...report.manifest, status: type === 'schema' ? 'validation_failed' : 'failed' },
      validation_errors: [{ code: type === 'schema' ? 'invalid_json_or_schema' : 'authentication_error' }] }) }
    : originalFetch(url, options)))
  renderExtraction()
  fireEvent.click(await screen.findByText('Run mock extraction'))
  expect(await screen.findByText('Request succeeded')).toBeInTheDocument()
  expect(screen.getByText(type === 'schema' ? 'Failed' : 'Not confirmed')).toBeInTheDocument()
  expect(screen.getByText('Not validated')).toBeInTheDocument()
  expect(screen.getByText('No structured criteria returned')).toBeInTheDocument()
  expect(screen.queryByLabelText('Verified source passage')).not.toBeInTheDocument()
})

test('an earlier source response cannot replace the selected historical snapshot', async () => {
  let resolveLatest!: (value: unknown) => void
  const pending = new Promise(resolve => { resolveLatest = resolve })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: () => url.includes('older%2F')
    ? Promise.resolve({ source: older, snapshots: [], warnings: [], mock_version: 'verbatim-sections-v1' }) : pending })))
  const view = render(<TrialExtraction key="latest" nctId="NCT00000001" snapshot="latest/response.json" />)
  view.rerender(<TrialExtraction key="older" nctId="NCT00000001" snapshot="older/response.json" />)
  await screen.findByText(older.sha256)
  await act(async () => { resolveLatest({ source: latest, snapshots: [], warnings: [], mock_version: 'verbatim-sections-v1' }) })
  expect(screen.queryByText(latest.sha256)).not.toBeInTheDocument()
})

test('a previous study extraction response cannot appear in the new study workspace', async () => {
  const originalFetch = fetch
  let resolveRun!: (value: unknown) => void
  const pending = new Promise(resolve => { resolveRun = resolve })
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.endsWith('/extractions')
    ? { ok: true, json: () => pending } : originalFetch(url, options)))
  const view = render(<TrialExtraction key="latest" nctId="NCT00000001" snapshot="latest/response.json" />)
  fireEvent.click(await screen.findByText('Run mock extraction'))
  view.rerender(<TrialExtraction key="older" nctId="NCT00000001" snapshot="older/response.json" />)
  await screen.findByText(older.sha256)
  await act(async () => { resolveRun(report) })
  expect(screen.queryByLabelText('Extraction result')).not.toBeInTheDocument()
})

test('live request failure consumes local approval and does not automatically retry', async () => {
  const originalFetch = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/extractions')) return { ok: false, status: 503, json: async () => ({ detail: 'Request outcome unavailable' }) }
    const response = await originalFetch(url, options)
    const source = await response.json()
    return { ok: true, json: async () => ({ ...source, configuration: { ready: true, model: 'nvidia/nemotron-3-super-120b-a12b', errors: [] } }) }
  }))
  renderExtraction()
  fireEvent.change(await screen.findByLabelText('Extraction mode'), { target: { value: 'live' } })
  fireEvent.change(screen.getByLabelText('Operator access code'), { target: { value: 'operator-test-token' } })
  fireEvent.click(screen.getByLabelText('Approve one paid live extraction of this snapshot'))
  fireEvent.click(screen.getByRole('button', { name: 'Run one live NVIDIA Nemotron extraction' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Request outcome unavailable')
  expect(screen.getByLabelText('Approve one paid live extraction of this snapshot')).not.toBeChecked()
  expect(screen.getByRole('button', { name: 'Run one live NVIDIA Nemotron extraction' })).toBeDisabled()
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/extractions'))).toHaveLength(1)
})

test('nested criteria remain selectable within their AND/OR dependency structure', async () => {
  const nestedText = 'Inclusion Criteria:\nSynthetic A AND (Synthetic B OR Synthetic C)'
  const source = { ...latest, text: nestedText }
  const node = (id: string, original_text: string, operator: string, dependencies: unknown[] | null) => ({
    ...candidate.criteria[0], criterion_id: id, original_text, logical_operator: operator, dependencies,
  })
  const root = node('root', 'Synthetic A AND (Synthetic B OR Synthetic C)', 'AND', [
    node('a', 'Synthetic A', 'NONE', null), node('branch', 'Synthetic B OR Synthetic C', 'OR', [node('b', 'Synthetic B', 'NONE', null), node('c', 'Synthetic C', 'NONE', null)]),
  ])
  const evidence = [['root', root.original_text], ['a', 'Synthetic A'], ['branch', 'Synthetic B OR Synthetic C'], ['b', 'Synthetic B'], ['c', 'Synthetic C']].map(([id, quote]) => ({
    criterion_id: id, original_span: { start: nestedText.indexOf(quote), end: nestedText.indexOf(quote) + quote.length }, polarity_span: { start: 0, end: 19 }, fields: {},
  }))
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith('/extractions')
    ? { ...report, source, candidate: { criteria: [root], evidence } }
    : { source, snapshots: [{ snapshot: 'latest/response.json', retrieved_at: latest.retrieval_timestamp }], warnings: [], mock_version: 'verbatim-sections-v1' } })))
  renderExtraction()
  fireEvent.click(await screen.findByText('Run mock extraction'))
  const branch = await screen.findByLabelText('Dependencies of branch')
  fireEvent.click(within(branch).getByRole('button', { name: 'Inspect criterion b' }))
  expect(screen.getByLabelText('Verified source passage').textContent).toBe('Synthetic B')
  expect(screen.getByText('Logic: AND')).toBeInTheDocument()
  expect(screen.getByText('Logic: OR')).toBeInTheDocument()
  expect(screen.getByLabelText('Exact original eligibility text').textContent).toBe(nestedText)
})
