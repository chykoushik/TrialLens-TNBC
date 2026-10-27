import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import fixture from './fixtures/tnbc_demo.json'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith('/health') ? { status: 'ok' } : url.endsWith('/research/trials') ? { trials: [
    { nct_id: 'NCT00000001', title: 'Public source software fixture', conditions: [], snapshot: 'saved/response.json', is_synthetic: null },
    { nct_id: 'NCT00000002', title: 'Explicit synthetic source fixture', conditions: [], snapshot: 'fixture/response.json', is_synthetic: true },
  ], warnings: [] } : url.endsWith('/tnbc/cases') ? fixture.catalog : url.endsWith('/research/cases') ? ['math-a', 'math-b'].map(case_id => ({ case_id, trial_count: 1, review_count: 1, budgets: ['3'], unsupported: null })) : structuredClone(fixture.baseline) })))
})

test('Home has four destinations, clear source boundaries and no duplicated workspace controls', async () => {
  render(<App />)
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  expect(within(screen.getByRole('navigation', { name: 'Main navigation' })).getAllByRole('button').map(button => button.textContent)).toEqual(['Try Demo', 'Explore Trials', 'Review Evidence', 'Research Tools'])
  expect(screen.getByRole('button', { name: 'Try the demo' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Browse saved trials' })).toBeInTheDocument()
  expect(screen.queryByLabelText('Application mode')).not.toBeInTheDocument()
  expect(screen.getByText(/No clinical use/)).toBeInTheDocument()
  expect(within(screen.getByRole('contentinfo')).getByRole('link', { name: 'GitHub' })).toHaveAttribute('href', 'https://github.com/chykoushik/TrialLens-TNBC')
  fireEvent.click(screen.getByRole('button', { name: 'Try the demo' }))
  fireEvent.click(screen.getByText('Advanced Mode', { selector: 'summary' }))
  await waitFor(() => expect(screen.getByLabelText('Fictional TNBC case')).toHaveValue('tnbc-record-gaps'))
  expect(screen.getAllByLabelText('Fictional TNBC case')).toHaveLength(1)
  expect(screen.getByRole('heading', { name: 'Try Demo', level: 1 })).toHaveFocus()
  expect(screen.getByRole('navigation', { name: 'Demo steps' }).querySelector('[aria-current=step]')).toHaveTextContent('Select fictional TNBC case')
})

test('demo and Lab retain independent case, budget and drafts while navigation preserves the guided step', async () => {
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Try the demo' }))
  fireEvent.click(screen.getByText('Advanced Mode', { selector: 'summary' }))
  await waitFor(() => expect(screen.getByLabelText('Fictional TNBC case')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Fictional TNBC case'), { target: { value: 'tnbc-stale-labs' } })
  fireEvent.change(screen.getByLabelText('Total review budget'), { target: { value: '5' } })
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Demo steps' })).getByRole('button', { name: /Simulate a review/ }))
  const select = await screen.findByLabelText('Fictional report outcome')
  const value = (select as HTMLSelectElement).options[1].value
  const count = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/evaluate')).length
  fireEvent.change(select, { target: { value } })
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/evaluate'))).toHaveLength(count)
  fireEvent.click(screen.getByRole('button', { name: 'Research Tools' }))
  await waitFor(() => expect(screen.getByLabelText('Synthetic portfolio')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Synthetic portfolio'), { target: { value: 'math-b' } })
  fireEvent.change(screen.getByLabelText('Total review budget'), { target: { value: '1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Try Demo' }))
  await waitFor(() => expect(screen.getByLabelText('Fictional report outcome')).toHaveValue(value))
  expect(screen.getByLabelText('Fictional TNBC case')).toHaveValue('tnbc-stale-labs')
  expect(screen.getByLabelText('Total review budget')).toHaveValue(5)
  fireEvent.click(screen.getByRole('button', { name: 'Apply simulated review' }))
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('/tnbc/cases/tnbc-stale-labs/evaluate'), expect.objectContaining({ body: expect.stringContaining(value) })))
  fireEvent.click(screen.getByRole('button', { name: 'Research Tools' }))
  expect(screen.getByLabelText('Synthetic portfolio')).toHaveValue('math-b')
  expect(screen.getByLabelText('Total review budget')).toHaveValue(1)
})

test('Explore Trials excludes explicit fixtures and Research Tools preserves their inspection access', async () => {
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Browse saved trials' }))
  expect(await screen.findByText('Public source software fixture')).toBeInTheDocument()
  expect(screen.queryByText('Explicit synthetic source fixture')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Fictional TNBC case')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Research Tools' }))
  fireEvent.click(screen.getByRole('button', { name: 'Source fixtures' }))
  expect(await screen.findByText('Explicit synthetic source fixture')).toBeInTheDocument()
  expect(screen.queryByText('Public source software fixture')).not.toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/extractions'))).toBe(false)
})

test('Research Tools retains all technical views and saved report access', async () => {
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Research Tools' }))
  for (const title of ['Patient evidence', 'Criterion assessments', 'Evidence prioritization', 'Reports & benchmarks', 'Source fixtures']) expect(within(screen.getByRole('navigation', { name: 'Research Tools sections' })).getByRole('button', { name: title })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Reports & benchmarks' }))
  expect(screen.getByRole('heading', { name: 'Reports & benchmarks' })).toBeInTheDocument()
  expect(screen.getByText(/No benchmark is run/)).toBeInTheDocument()
})

test('failed Apply preserves the draft and confirmed history; explicit retry commits once', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  let rejectReview = true
  let release: (() => void) | undefined
  let reviewRequests = 0
  vi.mocked(fetch).mockImplementation(async (...args) => {
    const body = args[1]?.body ? JSON.parse(String(args[1].body)) : null
    if (body && Object.keys(body.outcomes).length) {
      reviewRequests++
      await new Promise<void>(resolve => { release = resolve })
      if (rejectReview) return { ok: false, status: 503, json: async () => ({ detail: 'Offline test failure' }) } as Response
    }
    return original(...args)
  })
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Try the demo' }))
  fireEvent.click(screen.getByText('Advanced Mode', { selector: 'summary' }))
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Demo steps' })).getByRole('button', { name: /Simulate a review/ }))
  const select = await screen.findByLabelText('Fictional report outcome')
  const value = (select as HTMLSelectElement).options[1].value
  fireEvent.change(select, { target: { value } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply simulated review' }))
  await waitFor(() => expect(reviewRequests).toBe(1))
  expect(screen.getByText('0 hypothetical reviews applied')).toBeInTheDocument()
  release!()
  expect(await screen.findByText(/Review not applied. Draft retained/)).toBeInTheDocument()
  expect(await screen.findByLabelText('Fictional report outcome')).toHaveValue(value)
  expect(screen.getByText('0 hypothetical reviews applied')).toBeInTheDocument()
  rejectReview = false
  fireEvent.click(screen.getByRole('button', { name: 'Apply simulated review' }))
  await waitFor(() => expect(reviewRequests).toBe(2))
  release!()
  expect(await screen.findByText('1 hypothetical reviews applied')).toBeInTheDocument()
  expect(reviewRequests).toBe(2)
})

test('an empty backend plan never invents a next review from remaining candidates', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.mocked(fetch).mockImplementation(async (...args) => {
    if (String(args[0]).endsWith('/evaluate')) {
      const result = structuredClone(fixture.baseline)
      result.plan.selected_items = []
      return { ok: true, json: async () => result } as Response
    }
    return original(...args)
  })
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Try the demo' }))
  fireEvent.click(screen.getByText('Advanced Mode', { selector: 'summary' }))
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Demo steps' })).getByRole('button', { name: /Simulate a review/ }))
  expect(await screen.findByText('No further record review available')).toBeInTheDocument()
  expect(screen.queryByLabelText('Fictional report outcome')).not.toBeInTheDocument()
})

test('restoring a valid budget clears a failed calculation without losing confirmed evidence', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.mocked(fetch).mockImplementation(async (...args) => {
    if (args[1]?.body && JSON.parse(String(args[1].body)).budget === '0') {
      return { ok: false, status: 503, json: async () => ({ detail: 'Offline budget failure' }) } as Response
    }
    return original(...args)
  })
  render(<App />)
  fireEvent.click(screen.getByRole('button', { name: 'Try the demo' }))
  fireEvent.click(screen.getByText('Advanced Mode', { selector: 'summary' }))
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Demo steps' })).getByRole('button', { name: /Simulate a review/ }))
  await screen.findByLabelText('Fictional report outcome')
  fireEvent.change(screen.getByLabelText('Total review budget'), { target: { value: '0' } })
  expect(await screen.findByRole('alert')).toHaveTextContent('Offline budget failure')
  fireEvent.change(screen.getByLabelText('Total review budget'), { target: { value: '3' } })
  await screen.findByLabelText('Fictional report outcome')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
