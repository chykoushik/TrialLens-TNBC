import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import PaperPlanner from './PaperPlanner'

afterEach(() => vi.unstubAllGlobals())
test('manual exploration enables zero-weight feasible reports and keeps unavailable reports disabled', async () => {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/scenarios')) return { ok: true, json: async () => ({ scenarios: [{ id: 'one', criteria: 6, reports: 6 }] }) }
    const body = JSON.parse(options?.body as string)
    const reviewed = Object.keys(body.outcomes).length > 0
    return { ok: true, json: async () => ({
      reports: Array.from({ length: 6 }, (_, i) => ({ id: String(i), criterion: i+1, cost: 1, outcome: reviewed && i === 0 ? 1 : -1,
        selection_probability: !reviewed && i === 5 ? 1 : 0, feasible: !reviewed,
        unavailable_reason: reviewed ? i === 0 ? 'Already reviewed.' : 'Not enough review budget.' : null,
        permitted_outcomes: [0,1,2], expected_entropy_reduction: null })),
      manual_counterfactual: reviewed, recommendation_available: !reviewed, protocol_probabilities: reviewed ? [.7] : [.4],
      entropy_bits: 1, spent: reviewed ? 1 : 0, budget: 1, stop_probability: reviewed ? null : 0,
      expected_policy_metrics: { risk: .05, coverage: .6, utility: .5 }, numerical_gap: 0, risk_limit: .08,
      bdd_nodes: 10, cache: { hits: 0, misses: 1 }, scope: 'Synthetic model', policy_decisions: [], boolean_graph: [],
    }) }
  })
  vi.stubGlobal('fetch', fetcher)
  render(<PaperPlanner />)
  await waitFor(() => expect(screen.getByLabelText('Outcome for report 6')).toBeEnabled())
  expect(screen.getByLabelText('Outcome for report 1')).toBeDisabled()
  expect(screen.getByText(/Recommended by the optimizer/)).toBeVisible()
  fireEvent.click(screen.getByRole('checkbox'))
  await waitFor(() => expect(screen.getByLabelText('Outcome for report 1')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Outcome for report 1'), { target: { value: '1' } })
  expect(await screen.findByText(/Manual exploration results/)).toBeVisible()
  expect(screen.getByText(/70.0% probability/)).toBeVisible()
  expect(screen.getByLabelText('Outcome for report 2')).toBeDisabled()
  expect(screen.getAllByText('Not enough review budget.').length).toBeGreaterThan(0)
  expect(JSON.parse(fetcher.mock.calls.at(-1)?.[1]?.body as string)).toMatchObject({ manual: true, outcomes: { '0': 1 } })
})
