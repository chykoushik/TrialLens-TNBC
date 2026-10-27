import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import ProtocolAnnotation from './ProtocolAnnotation'
import ProtocolSource from './ProtocolSource'
import { captureSpan, criterion, slots, unreviewed } from './annotation'
import type { Bundle, Workspace } from './annotation'

const text = 'Inclusion Criteria:\nSoftware fixture 🧬 α ≥ 10 μg\nExclusion Criteria:\nSoftware only.'
const snapshot = 'software-fixture/response.json'
const workspace: Workspace = {
  source: { text, nct_id: 'NCT01770353', sha256: 'a'.repeat(64), source_snapshot: `data/raw/trials/${snapshot}`, source_url: 'https://clinicaltrials.gov/study/NCT01770353', retrieval_timestamp: null, is_synthetic: null },
  reference: { annotation_version: 'eligibility-reference-v1', annotation_revision: 1, nct_id: 'NCT01770353', snapshot_sha256: 'a'.repeat(64), annotation_origin: 'manual', inventory_review: unreviewed(), criteria: [] },
  candidates: [{ id: 'clause-20', original: { span: { start: 20, end: 44 }, text: Array.from(text).slice(20, 44).join('') }, suggested_polarity: 'inclusion', heading: null, context: null, warnings: [] }],
  slots, snapshots: [{ snapshot, retrieved_at: null }], versions: [],
}
let saved: Bundle | null = null

beforeEach(() => {
  saved = null
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : null
    if (url.endsWith('/versions')) {
      saved = { bundle_version: 'eligibility-review-bundle-v1', snapshot, source: workspace.source, reference: body.reference,
        audit: { version: 'b'.repeat(32), parent: body.parent, stage: body.stage, reviewer: body.reviewer, note: body.note, saved_at: '2026-10-25T00:00:00Z', operation: body.operation, reference_sha256: 'c'.repeat(64) } }
      return { ok: true, json: async () => ({ bundle: saved, export_json: JSON.stringify(saved), path: 'cache/software-test/export.json' }) }
    }
    if (url.endsWith('/validate')) return { ok: true, json: async () => ({ valid: true, coverage: { unreviewed_slots: 11 } }) }
    if (url.endsWith('/import')) return body.source.sha256 !== workspace.source.sha256
      ? { ok: false, status: 409, json: async () => ({ detail: 'Imported source provenance mismatch' }) }
      : { ok: true, json: async () => ({ reference: body.reference, stage: 'draft', message: 'Imported claims are unverified.' }) }
    return { ok: true, json: async () => structuredClone(workspace) }
  }))
})

async function click(name: string) {
  const button = screen.getByRole('button', { name })
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.click(button)
  await waitFor(() => expect(button).toBeEnabled())
}

async function create() {
  render(<ProtocolAnnotation active trials={[]} />)
  await screen.findByText(/Snapshot SHA-256/)
  fireEvent.click(screen.getByText('Advanced Mode: annotation details'))
  fireEvent.change(screen.getByLabelText('Span start'), { target: { value: '20' } })
  fireEvent.change(screen.getByLabelText('Span end'), { target: { value: '44' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create criterion from span' }))
  await screen.findByText('Boundary: unreviewed')
}

test('creates and edits schema-compatible drafts, explicitly reviews and exports a new version', async () => {
  await create()
  fireEvent.change(screen.getByLabelText(/Field value/), { target: { value: 'inclusion' } })
  await click('Set draft field value')
  fireEvent.click(screen.getByRole('button', { name: 'Add selected source evidence' }))
  fireEvent.change(screen.getByLabelText('Reviewer identifier or pseudonym'), { target: { value: 'software-tester' } })
  fireEvent.change(screen.getByLabelText('Review and audit note'), { target: { value: 'Software regression only' } })
  fireEvent.change(screen.getByLabelText('Explicit review status'), { target: { value: 'reviewed' } })
  await click('Set boundary review status')
  await screen.findByText('Boundary: reviewed')
  await click('Set field review status')
  fireEvent.change(screen.getByLabelText('Save stage'), { target: { value: 'reviewed' } })
  expect(screen.getByRole('button', { name: 'Save new version & export JSON' })).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox', { name: /I explicitly approve/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Save new version & export JSON' }))
  await waitFor(() => expect(saved).not.toBeNull())
  expect(saved!.reference.criteria[0].boundary_review.status).toBe('reviewed')
  expect(saved!.reference.inventory_review.status).toBe('unreviewed')
  expect(saved!.reference.criteria[0].unit).toMatchObject({ value: null, review: { status: 'unreviewed' } })
  expect(saved!.reference.criteria[0].polarity).toMatchObject({ value: 'inclusion', review: { status: 'reviewed', reviewer: 'software-tester' } })
})

test('import is a draft and mismatched hashes remain visibly rejected without losing edits', async () => {
  await create()
  fireEvent.click(screen.getByText('Deterministic JSON export / import'))
  const bundle = { bundle_version: 'eligibility-review-bundle-v1', snapshot, source: { ...workspace.source, sha256: '0'.repeat(64) }, reference: workspace.reference }
  fireEvent.change(screen.getByLabelText('Review bundle JSON'), { target: { value: JSON.stringify(bundle) } })
  fireEvent.click(screen.getByRole('button', { name: 'Import as local draft' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Imported source provenance mismatch')
  expect(screen.getByText('Boundary: unreviewed')).toBeInTheDocument()
  bundle.source.sha256 = workspace.source.sha256
  fireEvent.change(screen.getByLabelText('Review bundle JSON'), { target: { value: JSON.stringify(bundle) } })
  fireEvent.click(screen.getByRole('button', { name: 'Import as local draft' }))
  expect(await screen.findByText('Imported claims are unverified.')).toBeInTheDocument()
  expect(screen.getByLabelText('Save stage')).toHaveValue('draft')
})

test('nested correction clears approvals and invalid source spans cannot be highlighted', async () => {
  await create()
  fireEvent.click(screen.getByText('Nested criterion JSON / correction'))
  const node = criterion('manual-1', { span: { start: 20, end: 44 }, text: Array.from(text).slice(20, 44).join('') })
  node.boundary_review = { status: 'reviewed', reviewer: 'software-test', reviewed_at: '2026-10-25T00:00:00Z', note: null }
  node.dependencies.push(criterion('child', { span: { start: 20, end: 22 }, text: Array.from(text).slice(20, 22).join('') }))
  fireEvent.change(screen.getByLabelText('Criterion JSON'), { target: { value: JSON.stringify(node) } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply criterion correction' }))
  expect(await screen.findByText('Boundary: unreviewed')).toBeInTheDocument()
  expect(screen.getByRole('option', { name: /child.*unreviewed/ })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Span end'), { target: { value: '9999' } })
  expect(screen.getByRole('button', { name: 'Create criterion from span' })).toBeDisabled()
  expect(screen.queryByLabelText('Verified source passage')).not.toBeInTheDocument()
})

test('DOM selection offsets match Unicode code points across source rendering spans', () => {
  render(<ProtocolSource text={text} highlight={null} />)
  const pre = screen.getByLabelText('Exact original eligibility text')
  const walker = document.createTreeWalker(pre, NodeFilter.SHOW_TEXT)
  let node: Node | null = walker.nextNode()
  while (node && !node.textContent?.includes('🧬')) node = walker.nextNode()
  expect(node).not.toBeNull()
  const start = node!.textContent!.indexOf('α')
  const range = document.createRange(); range.setStart(node!, start); range.setEnd(node!, start + 'α ≥ 10 μg'.length)
  const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
  const quote = captureSpan(pre, selection, text)!
  expect(quote.text).toBe('α ≥ 10 μg')
  expect(quote.span.start).toBe(Array.from(text.slice(0, text.indexOf('α'))).length)
  expect(Array.from(text).slice(quote.span.start, quote.span.end).join('')).toBe(quote.text)
})

test('source loading reports unknown studies and Reload source retries the same request', async () => {
  const fetcher = vi.mocked(fetch)
  fetcher.mockResolvedValueOnce({ ok: false, status: 404, json: async () => ({ detail: 'Study outside saved benchmark' }) } as Response)
  render(<ProtocolAnnotation active trials={[]} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Study outside saved benchmark')
  await click('Reload source')
  await screen.findByLabelText('Annotation snapshot')
  expect(fetcher.mock.calls[0][0]).toBe('/api/annotations/NCT01770353')
  expect(fetcher.mock.calls[1][0]).toBe('/api/annotations/NCT01770353')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('snapshot requests encode the exact identity and recover from a temporary error', async () => {
  const fetcher = vi.mocked(fetch)
  const second = 'second-snapshot/response.json'
  fetcher.mockResolvedValueOnce({ ok: true, json: async () => ({ ...workspace, snapshots: [...workspace.snapshots, { snapshot: second, retrieved_at: null }] }) } as Response)
  render(<ProtocolAnnotation active trials={[]} />)
  await screen.findByLabelText('Annotation snapshot')
  fetcher.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: 'Temporary source failure' }) } as Response)
  fireEvent.change(screen.getByLabelText('Annotation snapshot'), { target: { value: second } })
  expect(await screen.findByRole('alert')).toHaveTextContent('Temporary source failure')
  await click('Reload source')
  await screen.findByLabelText('Annotation snapshot')
  expect(fetcher.mock.calls.slice(-2).map(call => call[0])).toEqual(Array(2).fill(`/api/annotations/NCT01770353?snapshot=${encodeURIComponent(second)}`))
  fireEvent.click(screen.getByText('Advanced Mode: annotation details'))
  expect(screen.getByRole('button', { name: 'Validate annotation' })).toBeEnabled()
})

async function chooseCandidate() {
  render(<ProtocolAnnotation active trials={[]} />)
  const card = await screen.findByRole('button', { name: /1\. inclusion/ })
  fireEvent.click(card)
  return card
}

test('clause selection is exact and draft confirmation and saving never approve labels', async () => {
  await chooseCandidate()
  expect(screen.getByLabelText('Selected clause quotation')).toHaveTextContent(Array.from(text).slice(20, 44).join(''))
  expect(screen.getByLabelText('Criterion polarity')).toHaveValue('')
  fireEvent.change(screen.getByLabelText('Criterion polarity'), { target: { value: 'inclusion' } })
  fireEvent.change(screen.getByLabelText('Value'), { target: { value: '10' } })
  fireEvent.change(screen.getByLabelText('Reviewer identifier or pseudonym'), { target: { value: 'software-tester' } })
  expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled()
  await click('Confirm draft')
  expect(screen.getByRole('button', { name: 'Save draft' })).toBeEnabled()
  expect(screen.getByText(/1 of 1 candidate clauses have drafts/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Reviewer identifier or pseudonym'), { target: { value: 'software-tester' } })
  await click('Save draft')
  await screen.findByText(/Draft saved\./)
  expect(saved!.audit.stage).toBe('draft')
  expect(saved!.reference.inventory_review.status).toBe('unreviewed')
  expect(saved!.reference.criteria[0].original.span).toEqual({ start: 20, end: 44 })
  expect(saved!.reference.criteria[0].boundary_review.status).toBe('unreviewed')
  expect((saved!.reference.criteria[0].polarity as { review: { status: string } }).review.status).toBe('unreviewed')
})

test('ambiguous drafts, deletion and undo preserve incomplete review status', async () => {
  await chooseCandidate()
  await click('Mark ambiguous')
  await click('Delete draft')
  expect(screen.getByText(/0 of 1 candidate clauses have drafts/)).toBeInTheDocument()
  await click('Undo last draft change')
  expect(screen.getByText(/1 of 1 candidate clauses have drafts/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Reviewer identifier or pseudonym'), { target: { value: 'software-tester' } })
  await click('Save draft')
  expect(saved!.reference.inventory_review.status).toBe('unreviewed')
  expect(saved!.reference.criteria[0].boundary_review.status).toBe('unreviewed')
})

test('boundary corrections require exact unique source text and skip creates no criterion', async () => {
  await chooseCandidate()
  fireEvent.click(screen.getByText('Correct clause boundary'))
  fireEvent.change(screen.getByLabelText('Exact passage within this clause'), { target: { value: 'invented' } })
  await click('Use corrected passage')
  expect(screen.getByRole('alert')).toHaveTextContent('exact, unique passage')
  fireEvent.change(screen.getByLabelText('Exact passage within this clause'), { target: { value: Array.from(text).slice(22, 30).join('') } })
  await click('Use corrected passage')
  await click('Confirm draft')
  await click('Skip')
  expect(screen.getByText(/1 skipped this session/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Reviewer identifier or pseudonym'), { target: { value: 'software-tester' } })
  await click('Save draft')
  expect(saved!.reference.criteria).toHaveLength(1)
  expect(saved!.reference.criteria[0].original.span).toEqual({ start: 22, end: 30 })
})

test('accidental document-wide selection requires explicit advanced acknowledgement', async () => {
  const long = { ...workspace, source: { ...workspace.source, text: 'x'.repeat(9000) } }
  vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: async () => long } as Response)
  render(<ProtocolAnnotation active trials={[]} />)
  await screen.findByText(/Snapshot SHA-256/)
  fireEvent.click(screen.getByText('Advanced Mode: annotation details'))
  fireEvent.change(screen.getByLabelText('Span start'), { target: { value: '21' } })
  fireEvent.change(screen.getByLabelText('Span end'), { target: { value: '8968' } })
  expect(screen.getByRole('button', { name: 'Create criterion from span' })).toBeDisabled()
  expect(screen.getByRole('checkbox', { name: /This selection is long/ })).not.toBeChecked()
})

test('anonymous draft autosave creates a draft only and cannot assert human review', async () => {
  await chooseCandidate()
  await click('Confirm draft')
  await waitFor(() => expect(saved).not.toBeNull(), { timeout: 2000 })
  expect(saved!.audit.reviewer).toMatch(/^local-draft-/)
  expect(saved!.audit.stage).toBe('draft')
  expect(saved!.reference.criteria[0].boundary_review.status).toBe('unreviewed')
  expect(screen.getByText(/Draft saved locally/)).toBeInTheDocument()
  fireEvent.click(screen.getByText('Advanced Mode: annotation details'))
  fireEvent.change(screen.getByLabelText('Annotation criterion'), { target: { value: 'clause-20' } })
  fireEvent.change(screen.getByLabelText('Explicit review status'), { target: { value: 'reviewed' } })
  await click('Set boundary review status')
  expect(screen.getByRole('alert')).toHaveTextContent('human reviewer identifier')
})

test('autosave failure stays unsaved and manual retry creates a draft without approving it', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  let fail = true
  vi.mocked(fetch).mockImplementation(async (...args) => String(args[0]).endsWith('/versions') && fail
    ? { ok: false, status: 503, json: async () => ({ detail: 'Temporary draft storage failure' }) } as Response : original(...args))
  await chooseCandidate()
  await click('Confirm draft')
  await screen.findByText('Draft not saved. Retry when the local server is available.')
  expect(saved).toBeNull()
  fail = false
  await click('Save draft')
  await waitFor(() => expect(saved).not.toBeNull())
  expect(saved!.audit.stage).toBe('draft')
  expect(saved!.reference.inventory_review.status).toBe('unreviewed')
})
