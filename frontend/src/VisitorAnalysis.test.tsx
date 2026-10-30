import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import VisitorAnalysis from './VisitorAnalysis'
import type { Trial } from './types'

const trial = { nct_id: 'NCT00000001', snapshot: 'fixture/response.json', snapshot_sha256: 'a'.repeat(64) } as Trial
const quote = { analysis_id: 'a'.repeat(64), model: 'NVIDIA software fixture', request_count: 2, maximum_cost_usd: '0.02', max_output_tokens_per_request: 4096, expires_in_seconds: 600 }
afterEach(() => vi.unstubAllGlobals())

test('explicit cost approval, single submission, clearing and no browser persistence', async () => {
  const local = vi.spyOn(Storage.prototype, 'setItem')
  const fetcher = vi.fn(async () => new Response(JSON.stringify(quote)))
  vi.stubGlobal('fetch', fetcher)
  render(<VisitorAnalysis trial={trial} />)
  expect(fetcher).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Run NVIDIA Analysis' }))
  const field = await screen.findByLabelText('Connect Nebius API Key')
  expect(screen.getByText(/Planned provider requests: 2/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Approve cost and analyze' })).toBeDisabled()
  fireEvent.change(field, { target: { value: 'non-secret-test-credential' } })
  expect(screen.getByRole('button', { name: 'Approve cost and analyze' })).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox'))
  let finish: (value: Response) => void = () => undefined
  fetcher.mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve }))
  const run = screen.getByRole('button', { name: 'Approve cost and analyze' })
  fireEvent.click(run); fireEvent.click(run)
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(screen.queryByDisplayValue('non-secret-test-credential')).not.toBeInTheDocument()
  const options = fetcher.mock.calls[1] as unknown as [string, RequestInit]
  expect(JSON.parse(options[1].body as string)).toMatchObject({ confirmed: true, maximum_cost_usd: '0.02' })
  finish(new Response(JSON.stringify({ status: 'complete', human_review_required: true, sections: [{ section: 1, status: 'validated', criteria: [{ criterion_id: 'one', original_text: 'source passage' }] }] })))
  expect(await screen.findByText('source passage')).toBeVisible()
  expect(local).not.toHaveBeenCalled()
  local.mockRestore()
})

test('failure is generic and requires a new approval; disconnect clears the key', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => quote }).mockRejectedValueOnce(new Error('non-secret-private-echo')).mockResolvedValue({ ok: true, json: async () => ({ removed: true }) })
  vi.stubGlobal('fetch', fetcher)
  render(<VisitorAnalysis trial={trial} />)
  fireEvent.click(screen.getByRole('button', { name: 'Run NVIDIA Analysis' }))
  fireEvent.change(await screen.findByLabelText('Connect Nebius API Key'), { target: { value: 'non-secret-test-credential' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: 'Approve cost and analyze' }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No automatic retry'))
  expect(screen.queryByText('non-secret-private-echo')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Approve cost and analyze' })).not.toBeInTheDocument()
  expect(fetcher).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Remove Key Now' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})



test('incomplete extraction shows safe validation reasons and keeps validated sections', async () => {
  const result = { status: 'incomplete', full_source_coverage_validated: false, sections: [
    { section: 1, status: 'validated', criteria: [{ criterion_id: 'first', original_text: 'Retained source quotation', logical_operator: null }] },
    { section: 2, status: 'failed', error: 'source_validation_failed', diagnostics: [{ code: 'unsupported_original_text', message: 'A quotation does not match the exact source text and character offsets.' }], criteria: [] },
    { section: 3, status: 'not_requested', criteria: [] },
  ], merge_diagnostics: [{ code: 'lost_cohort_scope', message: 'A nested condition lost its parent cohort scope.' }] }
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(quote))).mockResolvedValueOnce(new Response(JSON.stringify(result)))
  vi.stubGlobal('fetch', fetcher)
  render(<VisitorAnalysis trial={trial} />)
  fireEvent.click(screen.getByRole('button', { name: 'Run NVIDIA Analysis' }))
  fireEvent.change(await screen.findByLabelText('Connect Nebius API Key'), { target: { value: 'non-secret-test-credential' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: 'Approve cost and analyze' }))
  expect(await screen.findByText('Retained source quotation')).toBeVisible()
  expect(screen.getByText(/A quotation does not match/)).toBeVisible()
  expect(screen.getByText(/Combined source validation: A nested condition/)).toBeVisible()
  expect(screen.getByText('Section 3: not requested')).toBeVisible()
  expect(screen.getByText('Full source coverage: incomplete or unverified.')).toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(2)
})



for (const diagnostics of [undefined, []]) {
  test(`source-validation failure without diagnostics is explicitly marked (${diagnostics === undefined ? 'missing' : 'empty'})`, async () => {
    const result = { status: 'incomplete', full_source_coverage_validated: false, sections: [
      { section: 1, status: 'failed', error: 'source_validation_failed', diagnostics, criteria: [] },
      { section: 2, status: 'not_requested', criteria: [] },
    ] }
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(quote))).mockResolvedValueOnce(new Response(JSON.stringify(result)))
    vi.stubGlobal('fetch', fetcher)
    render(<VisitorAnalysis trial={trial} />)
    fireEvent.click(screen.getByRole('button', { name: 'Run NVIDIA Analysis' }))
    fireEvent.change(await screen.findByLabelText('Connect Nebius API Key'), { target: { value: 'non-secret-contract-fixture' } })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Approve cost and analyze' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The server did not provide validation details.')
    expect(screen.getByText('Section 2: not requested')).toBeVisible()
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
}



test('schema errors show sanitized field and validation category without retrying', async () => {
  const result = { status:'incomplete', sections:[{ section:1, status:'failed', error:'source_validation_failed', criteria:[],
    diagnostics:[{ code:'schema_error', message:'The model response does not match the required criteria and evidence schema.', field:'criteria.0.threshold', category:'incorrect_type' },
      { code:'schema_error', message:'The model response does not match the required criteria and evidence schema.', field:'evidence.0.original_span.end', category:'missing_required_property' }] },
    { section:2, status:'not_requested', criteria:[] }] }
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(quote))).mockResolvedValueOnce(new Response(JSON.stringify(result)))
  vi.stubGlobal('fetch', fetcher)
  render(<VisitorAnalysis trial={trial} />)
  fireEvent.click(screen.getByRole('button', { name:'Run NVIDIA Analysis' }))
  fireEvent.change(await screen.findByLabelText('Connect Nebius API Key'), { target:{value:'non-secret-schema-fixture'} })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name:'Approve cost and analyze' }))
  expect(await screen.findByText(/Field: criteria.0.threshold./)).toHaveTextContent('Reason: incorrect type.')
  expect(screen.getByText(/Field: evidence.0.original_span.end./)).toHaveTextContent('Reason: missing required property.')
  expect(screen.getByText('Section 2: not requested')).toBeVisible()
  expect(screen.queryByDisplayValue('non-secret-schema-fixture')).not.toBeInTheDocument()
  expect(fetcher).toHaveBeenCalledTimes(2)
})



test.each([
  [422, 'Long cohort-scoped criteria require source review before splitting.', 'Long cohort-scoped criteria require source review before splitting.'],
  [429, 'Visitor preparation limit reached. Please wait ten minutes.', 'Visitor preparation limit reached. Please wait ten minutes.'],
  [503, 'Operator must configure verified provider pricing before visitor extraction.', 'Operator must configure verified provider pricing before visitor extraction.'],
  [403, 'Untrusted request origin.', 'Untrusted request origin.'],
  [404, 'non-secret-private-server-detail', 'The preparation endpoint was not found.'],
  [500, 'non-secret-private-server-detail', 'The analysis service could not prepare this request.'],
])('failed preparation %s shows a safe reason and never opens the key form', async (status, detail, expected) => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail }), { status }))
  vi.stubGlobal('fetch', fetcher)
  render(<VisitorAnalysis trial={trial} />)
  fireEvent.click(screen.getByRole('button', { name:'Run NVIDIA Analysis' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(`HTTP ${status}`)
  expect(screen.getByRole('alert')).toHaveTextContent(expected)
  expect(screen.getByRole('alert')).not.toHaveTextContent('non-secret-private-server-detail')
  expect(screen.queryByLabelText('Connect Nebius API Key')).not.toBeInTheDocument()
  expect(fetcher).toHaveBeenCalledTimes(1)
})


test('source inventory stays visible when interpretations are missing or unresolved', async () => {
  const result = { status: 'incomplete', source_inventory_complete: true, interpretation_complete: false,
    full_source_coverage_validated: false, source_passages: [
      { source_id: 'source-20-48', start: 20, end: 48, text: '  1. A AND (B OR C)', interpretation_status: 'unresolved', unresolved_reason: 'logic_requires_review' },
      { source_id: 'source-49-70', start: 49, end: 70, text: '2. Original omitted passage', interpretation_status: 'not_requested', unresolved_reason: 'not_requested' },
    ], sections: [{ section: 1, status: 'failed', criteria: [] }, { section: 2, status: 'not_requested', criteria: [] }] }
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(quote))).mockResolvedValueOnce(new Response(JSON.stringify(result)))
  vi.stubGlobal('fetch', fetcher)
  render(<VisitorAnalysis trial={trial} />)
  fireEvent.click(screen.getByRole('button', { name: 'Run NVIDIA Analysis' }))
  fireEvent.change(await screen.findByLabelText('Connect Nebius API Key'), { target: { value: 'non-secret-inventory-fixture' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: 'Approve cost and analyze' }))
  expect(await screen.findByText(/Original source inventory: complete/)).toHaveTextContent('Clinical interpretation: incomplete or unresolved.')
  fireEvent.click(screen.getByText('Original passages and interpretation coverage (2)'))
  expect(screen.getByText('2. Original omitted passage')).toBeVisible()
  expect(screen.getByText('Requires review: logic requires review.')).toBeVisible()
  expect(screen.getByText('Full source coverage: incomplete or unverified.')).toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(2)
})


test('source coverage and supported numeric fields are distinct from unresolved clinical interpretation', async () => {
  const criterion = { criterion_id: 'age', original_text: 'Age >=18 years', criterion_type: 'inclusion', logical_operator: null,
    threshold: '18', comparator: '>=', unit: 'years', biomarker: null, assay: null, cohort: null, temporal_constraint: null }
  const result = { status: 'review_required', source_inventory_complete: true, full_source_coverage_validated: true,
    interpretation_complete: false, source_passages: [{ source_id: 'age', start: 20, end: 33, text: 'Age >=18 years',
      interpretation_status: 'unresolved', unresolved_reason: 'logic_requires_review',
      field_status: { threshold: 'retained', biomarker: 'not_extracted_or_not_applicable' } }],
    sections: [{ section: 1, status: 'validated', criteria: [criterion] }] }
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(quote))).mockResolvedValueOnce(new Response(JSON.stringify(result)))
  vi.stubGlobal('fetch', fetcher)
  render(<VisitorAnalysis trial={trial} />)
  fireEvent.click(screen.getByRole('button', { name: 'Run NVIDIA Analysis' }))
  fireEvent.change(await screen.findByLabelText('Connect Nebius API Key'), { target: { value: 'non-secret-field-fixture' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: 'Approve cost and analyze' }))
  expect(await screen.findByText('Full source coverage: validated.')).toBeVisible()
  expect(screen.getByText(/Clinical interpretation: incomplete or unresolved/)).toBeVisible()
  expect(screen.getByText(/Structured clinical fields: 3 source-supported values/)).toBeVisible()
  expect(screen.getByText('18')).toBeVisible()
  expect(screen.getByText('years')).toBeVisible()
  expect(screen.getByText(/Unfilled fields may be inapplicable or not extracted/)).toBeVisible()
  expect(screen.getByText(/It does not establish complete clinical interpretation/)).toBeVisible()
  fireEvent.click(screen.getByText('Original passages and interpretation coverage (1)'))
  expect(screen.queryByRole('list', { name: 'Clinical field handling' })).not.toBeInTheDocument()
  expect(fetcher).toHaveBeenCalledTimes(2)
})


test('literal source facts are identified without claiming they were supplied by the model', async () => {
  const result = {status:'review_required',literal_source_rules_used:true,source_inventory_complete:true,
    interpretation_complete:false,full_source_coverage_validated:true,source_passages:[],sections:[]}
  vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(quote))).mockResolvedValueOnce(new Response(JSON.stringify(result))))
  render(<VisitorAnalysis trial={trial} />)
  fireEvent.click(screen.getByRole('button',{name:'Run NVIDIA Analysis'}))
  fireEvent.change(await screen.findByLabelText('Connect Nebius API Key'),{target:{value:'non-secret-literal-fixture'}})
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button',{name:'Approve cost and analyze'}))
  expect(await screen.findByText(/not supplied by the model/)).toBeVisible()
  expect(screen.getByText(/Clinical interpretation: incomplete or unresolved/)).toBeVisible()
})
