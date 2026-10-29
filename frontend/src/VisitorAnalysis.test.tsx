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
