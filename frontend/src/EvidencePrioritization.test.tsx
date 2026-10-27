import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import EvidencePrioritization, { algorithms, modelNumber } from './EvidencePrioritization'
import fixture from './fixtures/tnbc_demo.json'
import type { Evaluation } from './types'

const softwareFixture = () => structuredClone(fixture.baseline) as Evaluation
function props(data: Evaluation | null = softwareFixture()) {
  return { data, algorithm: 'exact_nonadaptive', mode: 'research' as const, budget: '3', outcomes: {}, selectedId: null, selectReview: vi.fn(), changeAlgorithm: vi.fn(), simulate: vi.fn(), loading: false, failed: false }
}

test('preserves exact backend plan order without inventing individual rankings or benefits', () => {
  const data = softwareFixture()
  render(<EvidencePrioritization {...props(data)} />)
  const list = screen.getByRole('heading', { name: 'Existing records to investigate' }).closest('section')!
  const records = within(list).getAllByRole('button', { name: /Inspect review/ })
  expect(records[0]).toHaveAttribute('aria-label', `Inspect review ${data.plan.selected_items[0]}`)
  expect(records[1]).toHaveAttribute('aria-label', `Inspect review ${data.plan.selected_items[1]}`)
  expect(screen.getByRole('region', { name: 'Next proposed review' })).toHaveTextContent('not an independently optimal next-record ranking')
  fireEvent.click(screen.getByText('Backend ranking and selection trace'))
  expect(screen.getByText(/No per-record ranking trace returned/)).toBeVisible()
  expect(screen.getAllByText('Not returned')).toHaveLength(1)
})

test('shows exact rational values and marks before/after and additional spending as forecasts', () => {
  const data = softwareFixture()
  data.plan.expected_final_uncertainty = '1/5'
  render(<EvidencePrioritization {...props(data)} />)
  expect(screen.getByRole('region', { name: 'Review budget accounting' })).toHaveTextContent('Total budget / input3Already spent0Remaining3Proposed additional cost3')
  const chart = screen.getByRole('figure', { name: 'Portfolio uncertainty: current versus expected' })
  expect(chart).toHaveTextContent('After proposed set / forecast1/5')
  expect(screen.getByRole('figure', { name: 'Review cost tradeoff' })).toHaveTextContent('Proposed additional cost / forecast3')
  expect(modelNumber('9/5')).toBe(1.8)
  expect(modelNumber('0')).toBe(0)
  expect(modelNumber('1/0')).toBeNull()
})

test('inspects only declared protocol targets, provenance and actual assay limitations', () => {
  render(<EvidencePrioritization {...props()} selectedId="review-pdl1-report" />)
  const inspector = screen.getByRole('region', { name: 'Review record inspector' })
  expect(inspector).toHaveTextContent('demo-pdl1-pdl1')
  expect(inspector).not.toHaveTextContent('demo-brca-ecog')
  expect(inspector).toHaveTextContent('22C3 CPS and SP142 IC remain distinct')
  fireEvent.click(within(inspector).getByText('Record provenance & assumptions'))
  expect(within(inspector).getByText('synthetic://tnbc/records/review-pdl1-report')).toBeVisible()
  expect(inspector).toHaveTextContent('No review reliability model supplied')
})

test('shows returned bundle trace scores without converting utility into uncertainty reduction', () => {
  const data = softwareFixture()
  data.plan.trace = [
    { selected: 'review-pdl1-report', ranking: [{ item_id: 'review-pdl1-report', bundle: ['review-pdl1-report'], cost: '1', score: '3/5', delta: '3/5' }] },
    { selected: null, ranking: [{ item_id: 'review-germline-report', bundle: ['review-germline-report'], cost: '2', delta_U: '2/5', status: 'feasible' }] },
  ]
  render(<EvidencePrioritization {...props(data)} algorithm="joint_greedy" />)
  fireEvent.click(screen.getByText('Backend ranking and selection trace'))
  const trace = screen.getByRole('region', { name: 'Backend bundle ranking' })
  expect(trace).toHaveTextContent('Strategy score: 3/5')
  expect(trace).toHaveTextContent('Marginal utility: 3/5')
  expect(trace).not.toHaveTextContent('Expected reduction')
  fireEvent.change(screen.getByLabelText('Forecast selection step'), { target: { value: '1' } })
  expect(trace).toHaveTextContent('Expected reduction: 2/5')
  for (const value of ['0', '1', '0']) {
    const selector = screen.getByLabelText('Forecast selection step')
    selector.focus()
    fireEvent.keyDown(selector, { key: 'ArrowDown' })
    fireEvent.change(selector, { target: { value } })
    expect(selector).toHaveValue(value)
    expect(selector).toBeEnabled()
  }
})

test.each(algorithms)('retains the %s strategy identifier and dispatches the existing selector callback', algorithm => {
  const config = props()
  render(<EvidencePrioritization {...config} />)
  fireEvent.change(screen.getByLabelText('Algorithm'), { target: { value: algorithm } })
  expect(config.changeAlgorithm).toHaveBeenCalledWith(algorithm)
  expect(within(screen.getByLabelText('Algorithm')).getAllByRole('option')).toHaveLength(13)
})

test('keeps TNBC risk methods visible but disabled without reliability assumptions', () => {
  render(<EvidencePrioritization {...props()} mode="tnbc" />)
  for (const name of ['risk exact', 'risk greedy', 'risk adaptive']) expect(screen.getByRole('option', { name: `${name} (no reliability assumptions)` })).toBeDisabled()
})

test('enforces budget, prerequisites and completed-review locks without mutating supplied records', () => {
  const data = softwareFixture()
  const original = structuredClone(data)
  const config = props(data)
  render(<EvidencePrioritization {...config} />)
  fireEvent.change(screen.getByLabelText('Simulated report for review-pdl1-report'), { target: { value: 'cps-15' } })
  expect(config.simulate).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Apply simulated review review-pdl1-report' }))
  expect(config.simulate).toHaveBeenCalledWith('review-pdl1-report', 'cps-15')
  expect(data).toEqual(original)
})

test('disables over-budget, unmet prerequisite and completed simulations with useful text', () => {
  const data = softwareFixture()
  data.remaining_budget = '0'
  data.candidates[0].depends_on = ['review-germline-report']
  render(<EvidencePrioritization {...props(data)} outcomes={{ 'review-germline-report': 'simulated' }} />)
  expect(screen.getByText(/No remaining review budget/)).toBeInTheDocument()
  expect(screen.getByLabelText('Simulated report for review-pdl1-report')).toBeDisabled()
  expect(screen.getByLabelText('Simulated report for review-germline-report')).toBeDisabled()
  expect(screen.getByText(/Exceeds remaining budget/)).toBeInTheDocument()
})

test('retains unmet prerequisites even when an individual review is affordable', () => {
  const data = softwareFixture()
  data.candidates[0].depends_on = ['review-germline-report']
  render(<EvidencePrioritization {...props(data)} />)
  expect(screen.getByLabelText('Simulated report for review-pdl1-report')).toBeDisabled()
  expect(screen.getByText(/Prerequisite review required/)).toBeInTheDocument()
})

test('explains zero uncertainty, no candidates and empty plan without inventing reviews', () => {
  const data = softwareFixture()
  data.candidates = []
  data.plan.selected_items = []
  data.assessment.uncertainty = '0'
  render(<EvidencePrioritization {...props(data)} />)
  expect(screen.getByText(/Current engine uncertainty is zero/)).toBeInTheDocument()
  expect(screen.getByText('No reviewable existing records')).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Next proposed review' })).toHaveTextContent('No additional review proposed')
})

test('clears obsolete proposals on a failed calculation while keeping algorithm recovery available', () => {
  render(<EvidencePrioritization {...props(null)} failed />)
  expect(screen.getByText('No current plan available')).toBeInTheDocument()
  expect(screen.getByLabelText('Algorithm')).toBeEnabled()
  expect(screen.queryByRole('region', { name: 'Next proposed review' })).not.toBeInTheDocument()
})
