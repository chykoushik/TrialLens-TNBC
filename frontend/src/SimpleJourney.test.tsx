import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import fixture from './fixtures/tnbc_demo.json'
import type { Evaluation } from './types'
import SimpleDemo from './SimpleDemo'

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : null
    const result = structuredClone(body?.outcomes?.['review-pdl1-report'] ? fixture.reviewed : fixture.baseline)
    result.plan.selected_items = ['review-pdl1-report']
    return { ok: true, json: async () => url.endsWith('/health') ? { status: 'ok' } : url.endsWith('/research/trials') ? { trials: [], warnings: [] } : url.endsWith('/cases') ? fixture.catalog : result }
  }))
})

test('three-action first visit stages without recalculation and applies a real before/after summary', async () => {
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Try the demo' }))
  const radios = await screen.findAllByRole('radio')
  expect(screen.queryByLabelText('Total review budget')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Application mode')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Algorithm')).not.toBeInTheDocument()
  expect(screen.queryByRole('navigation', { name: 'Demo steps' })).not.toBeInTheDocument()
  expect(within(screen.getByLabelText('Fictional evidence summary')).getByText('Missing', { exact: true })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Apply fictional report' })).toBeDisabled()
  const before = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/evaluate')).length
  fireEvent.click(radios[0])
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/evaluate'))).toHaveLength(before)
  expect(screen.queryByLabelText('What changed')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Apply fictional report' }))
  const result = await screen.findByLabelText('What changed')
  expect(result).toHaveTextContent('2 → 1 unclear checks')
  expect(result).toHaveTextContent('Missing information → Clause met')
  expect(result).toHaveTextContent('not an eligibility decision')
})

test('failed Apply retains the selection and commits no success message', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.mocked(fetch).mockImplementation(async (...args) => args[1]?.body && Object.keys(JSON.parse(String(args[1].body)).outcomes ?? {}).length ? { ok: false, status: 503, json: async () => ({ detail: 'Software failure' }) } as Response : original(...args))
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Try the demo' }))
  fireEvent.click((await screen.findAllByRole('radio'))[0])
  fireEvent.click(screen.getByRole('button', { name: 'Apply fictional report' }))
  await screen.findByText(/Review not applied. Draft retained/)
  await waitFor(() => expect(screen.getAllByRole('radio')[0]).toBeChecked())
  expect(screen.queryByLabelText('What changed')).not.toBeInTheDocument()
})

test('empty plans never fabricate a report and nonfinite cost cannot enable Apply', () => {
  const data = structuredClone(fixture.baseline) as Evaluation
  data.plan.selected_items = []; data.next_review = null
  const props = { data, cases: [], caseId: '', chooseCase: vi.fn(), drafts: {}, stage: vi.fn(), apply: vi.fn(), outcomes: {}, loading: false, lastReview: null, reviewEvidence: vi.fn(), restart: vi.fn() }
  const view = render(<SimpleDemo {...props} />)
  expect(screen.getByText('No further report proposed')).toBeInTheDocument()
  expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  data.plan.selected_items = [data.candidates[0].item_id]; data.candidates[0].cost = 'invalid'
  view.rerender(<SimpleDemo {...props} data={data} drafts={{ [data.candidates[0].item_id]: data.candidates[0].outcomes[0].outcome_id }} />)
  expect(screen.getByRole('button', { name: 'Apply fictional report' })).toBeDisabled()
})
