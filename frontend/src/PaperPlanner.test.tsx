import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import PaperPlanner from './PaperPlanner'

let requests: { scenario: string; budget: number; outcomes: Record<string, number>; manual: boolean }[]
beforeEach(() => {
  requests = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/scenarios')) return { ok: true, json: async () => ({ scenarios: [{ id: 'one', criteria: 6, reports: 6 }, { id: 'two', criteria: 4, reports: 6 }] }) }
    const body = JSON.parse(options?.body as string)
    requests.push(body)
    const spent = Object.keys(body.outcomes).length
    return { ok: true, json: async () => ({
      reports: Array.from({ length: 6 }, (_, i) => ({ id: String(i), criterion: i+1, cost: i === 3 ? 2 : 1,
        outcome: body.outcomes[String(i)] ?? -1,
        selection_probability: !spent && i === 5 && body.budget > 0 ? 1 : 0,
        feasible: body.outcomes[String(i)] === undefined && spent + (i === 3 ? 2 : 1) <= body.budget,
        unavailable_reason: body.outcomes[String(i)] !== undefined ? 'Already reviewed.' : 'Not enough review budget.',
        permitted_outcomes: i === 4 ? [0,2] : [0,1,2], expected_entropy_reduction: .125 })),
      manual_counterfactual: body.manual && spent > 0, recommendation_available: !body.manual || !spent,
      protocol_probabilities: spent ? [.7] : [.4], entropy_bits: 1, spent, budget: body.budget,
      stop_probability: body.manual && spent ? null : 0, expected_policy_metrics: { risk: .05, coverage: .6, utility: .5 },
      numerical_gap: 0, risk_limit: .08, bdd_nodes: 10, cache: { hits: 0, misses: 1 },
      scope: 'Synthetic model', policy_decisions: [{ weight: 1, decisions: [-1, 1] }], boolean_graph: [['AND', 0, 1]],
    }) }
  }))
})
afterEach(() => vi.unstubAllGlobals())

async function ready() {
  render(<PaperPlanner />)
  await waitFor(() => expect(screen.getByLabelText('Outcome for report 6')).toBeEnabled())
}

test('initial view explains the synthetic demo and highlights only backend recommendations', async () => {
  await ready()
  expect(screen.getByText(/not actual patient records/)).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Recommended next: Report 6' })).toBeVisible()
  expect(screen.getAllByRole('heading', { level: 4 })[0]).toHaveTextContent('Report 6 - Recommended')
  expect(screen.getByText(/Checks synthetic condition 6/)).toBeVisible()
  expect(screen.getByLabelText('Outcome for report 1')).toBeDisabled()
  expect(screen.queryByLabelText('Outcome for report 4')).not.toBeInTheDocument()
  expect(screen.getByText('Report 4: Not enough review budget.')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Restart Review' })).toBeEnabled()
  expect(requests.at(-1)).toMatchObject({ manual: false, budget: 1, outcomes: {} })
})

test('manual exploration enables feasible zero-weight alternatives without inventing recommendations', async () => {
  await ready()
  fireEvent.click(screen.getByRole('checkbox'))
  await waitFor(() => expect(screen.getByLabelText('Outcome for report 1')).toBeEnabled())
  expect(screen.queryByLabelText('Outcome for report 4')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Outcome for report 5').querySelector('option[value="1"]')).toBeDisabled()
})

test.each([['0', 'Negative'], ['1', 'Positive'], ['2', 'Unavailable']])('recommended outcome %s updates estimates and ends the one-unit review', async (value, label) => {
  await ready()
  fireEvent.change(screen.getByLabelText('Outcome for report 6'), { target: { value } })
  expect(await screen.findByRole('heading', { name: 'Review budget exhausted' })).toBeVisible()
  expect(screen.getByText(/No further reports can be reviewed/)).toBeVisible()
  expect(screen.getByText(`Report 6: ${label} (1 review unit)`)).toBeVisible()
  expect(screen.getByText(/70.0% modeled probability/)).toBeVisible()
  expect(screen.queryByLabelText(/Outcome for report/)).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Hypothetical reports' })).not.toBeInTheDocument()
  expect(requests.at(-1)).toMatchObject({ manual: false, outcomes: { '5': Number(value) } })
  expect(screen.getByLabelText('Scenario')).toBeEnabled()
  expect(screen.getByLabelText('Review budget')).toBeEnabled()
})

test('manual outcomes use the existing backend and restart restores the original review', async () => {
  await ready()
  fireEvent.click(screen.getByRole('checkbox'))
  await waitFor(() => expect(screen.getByLabelText('Outcome for report 1')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Outcome for report 1'), { target: { value: '1' } })
  expect(await screen.findByText(/Manual exploration results/)).toBeVisible()
  expect(requests.at(-1)).toMatchObject({ manual: true, outcomes: { '0': 1 } })
  fireEvent.click(screen.getByRole('button', { name: 'Restart Review' }))
  await waitFor(() => expect(screen.getByLabelText('Outcome for report 1')).toBeEnabled())
  expect(screen.getByText(/40.0% modeled probability/)).toBeVisible()
  expect(requests.at(-1)?.outcomes).toEqual({})
  expect(screen.queryByRole('heading', { name: 'Your hypothetical review' })).not.toBeInTheDocument()
})

test('scenario and budget changes clear prior outcomes and request fresh calculations', async () => {
  await ready()
  fireEvent.change(screen.getByLabelText('Outcome for report 6'), { target: { value: '0' } })
  await screen.findByRole('heading', { name: 'Review budget exhausted' })
  fireEvent.change(screen.getByLabelText('Review budget'), { target: { value: '3' } })
  await waitFor(() => expect(screen.getByLabelText('Outcome for report 6')).toBeEnabled())
  expect(requests.at(-1)).toMatchObject({ budget: 3, outcomes: {} })
  fireEvent.change(screen.getByLabelText('Outcome for report 6'), { target: { value: '1' } })
  await screen.findByRole('heading', { name: 'Your hypothetical review' })
  fireEvent.change(screen.getByLabelText('Scenario'), { target: { value: 'two' } })
  await waitFor(() => expect(requests.at(-1)).toMatchObject({ scenario: 'two', budget: 3, outcomes: {} }))
  expect(await screen.findByRole('heading', { name: 'Starting model estimates' })).toBeVisible()
})

test('zero budget never presents reports for selection', async () => {
  await ready()
  fireEvent.change(screen.getByLabelText('Review budget'), { target: { value: '0' } })
  expect(await screen.findByRole('heading', { name: 'Review budget exhausted' })).toBeVisible()
  expect(screen.queryByLabelText(/Outcome for report/)).not.toBeInTheDocument()
})

test('research diagnostics remain accessible but collapsed by default', async () => {
  await ready()
  const summary = screen.getByText('Research Details')
  expect(summary.closest('details')).not.toHaveAttribute('open')
  expect(screen.getByText(/BDD nodes: 10/)).not.toBeVisible()
  expect(screen.getByText(/Boolean expressions from the frozen scenario/)).not.toBeVisible()
  expect(screen.getByText(/Sources: research/)).not.toBeVisible()
  fireEvent.click(summary)
  expect(screen.getByText(/BDD nodes: 10/)).toBeVisible()
  expect(screen.getByText(/Policy weight is how often/)).toBeVisible()
  expect(screen.getByText(/not guarantees conditional/)).toBeVisible()
})


test('manual review with remaining budget keeps feasible future actions available', async () => {
  await ready()
  fireEvent.change(screen.getByLabelText('Review budget'), { target: { value: '3' } })
  await waitFor(() => expect(screen.getByLabelText('Outcome for report 6')).toBeEnabled())
  fireEvent.click(screen.getByRole('checkbox'))
  await waitFor(() => expect(screen.getByLabelText('Outcome for report 1')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Outcome for report 1'), { target: { value: '0' } })
  await screen.findByText(/Manual exploration results/)
  expect(screen.getByLabelText('Outcome for report 2')).toBeEnabled()
  expect(screen.queryByRole('heading', { name: /Recommended next/ })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Outcome for report 2'), { target: { value: '1' } })
  await waitFor(() => expect(requests.at(-1)).toMatchObject({ manual: true, budget: 3, outcomes: { '0': 0, '1': 1 } }))
  expect(await screen.findByText('Report 2: Positive (1 review unit)')).toBeVisible()
})
