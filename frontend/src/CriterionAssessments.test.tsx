import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import CriterionAssessments from './CriterionAssessments'
import fixture from './fixtures/tnbc_demo.json'
import type { Evaluation, State } from './types'

const softwareFixture = () => structuredClone(fixture.baseline) as Evaluation
const inspector = () => screen.getByRole('region', { name: 'Criterion reasoning inspector' })
const select = (id: string) => fireEvent.click(screen.getByRole('button', { name: `Inspect ${id}` }))

test.each<State>(['satisfied', 'violated', 'unknown', 'temporal', 'conflict'])('preserves the backend %s state and filters without recomputing it', state => {
  const data = softwareFixture()
  const node = data.assessment.decisions[0].assessment.assessments[2]
  node.state = state
  render(<CriterionAssessments data={data} inspectEvidence={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Assessment state'), { target: { value: state } })
  select(node.criterion_id)
  expect(within(inspector()).getAllByText(state, { selector: '.badge' }).length).toBeGreaterThan(0)
  expect(within(inspector()).getByText(node.reason_code, { selector: 'code' })).toBeInTheDocument()
})

test('retains exact clause text, nested AND/OR branches and unresolved leaves', () => {
  render(<CriterionAssessments data={softwareFixture()} inspectEvidence={vi.fn()} />)
  select('demo-brca-tnbc')
  expect(within(inspector()).getByText('FICTIONAL DEMO ONLY: (ER < 1% AND PR < 1%) AND an explicitly reviewed HER2-negative interpretation.')).toBeInTheDocument()
  const tree = within(inspector()).getByRole('list', { name: 'Logical reasoning tree' })
  expect(tree).toHaveTextContent('AND / demo-brca-receptors')
  fireEvent.click(within(tree).getByRole('button', { name: 'demo-brca-er satisfied' }))
  expect(within(inspector()).getByRole('heading', { name: 'demo-brca-er' })).toBeInTheDocument()
  select('demo-brca-brca')
  expect(within(inspector()).getByRole('list', { name: 'Logical reasoning tree' })).toHaveTextContent('OR / demo-brca-brca')
  expect(inspector()).toHaveTextContent('unknown')
  fireEvent.click(within(inspector()).getByText('OR / demo-brca-brca'))
  expect(within(inspector()).getByText('OR / demo-brca-brca').parentElement).not.toHaveAttribute('open')
})

test('keeps exclusion polarity independent of truth and reports only actual top-level counts', () => {
  render(<CriterionAssessments data={softwareFixture()} inspectEvidence={vi.fn()} />)
  select('demo-pdl1-cns')
  expect(inspector()).toHaveTextContent('excluding condition not met; not an exclusion blocker')
  expect(screen.getByRole('region', { name: 'Engine portfolio summary' })).toHaveTextContent('15 top-level clauses')
  fireEvent.click(screen.getByText('Read states and inclusion / exclusion polarity'))
  expect(screen.getByText(/Neither establishes overall eligibility/)).toBeVisible()
})

test('filters protocol and polarity with clear recovery', () => {
  render(<CriterionAssessments data={softwareFixture()} inspectEvidence={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Fictional protocol'), { target: { value: 'demo-pdl1' } })
  fireEvent.change(screen.getByLabelText('Criterion type'), { target: { value: 'exclusion' } })
  expect(screen.queryByRole('button', { name: 'Inspect demo-brca-cns' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Inspect demo-pdl1-cns' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Assessment state'), { target: { value: 'conflict' } })
  expect(screen.getByText('No matching clauses')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
  expect(screen.getByRole('button', { name: 'Inspect demo-brca-cns' })).toBeInTheDocument()
})

test('links only available backend evidence IDs and explains PD-L1 assay mismatch and missing values', () => {
  const inspectEvidence = vi.fn()
  render(<CriterionAssessments data={softwareFixture()} inspectEvidence={inspectEvidence} />)
  select('demo-pdl1-pdl1')
  expect(inspector()).toHaveTextContent('22C3 CPS and SP142 IC are not interchangeable')
  expect(inspector()).toHaveTextContent('not a negative finding')
  const link = within(inspector()).getByRole('button', { name: 'Inspect evidence fictional-PD-L1-baseline' })
  fireEvent.click(link)
  expect(inspectEvidence).toHaveBeenCalledWith('fictional-PD-L1-baseline')
})

test('does not infer symbolic operands from original prose or create links for unavailable IDs', () => {
  const data = softwareFixture()
  const node = data.assessment.decisions[0].assessment.assessments[2]
  node.evidence_ids = ['unavailable-record']
  render(<CriterionAssessments data={data} inspectEvidence={vi.fn()} />)
  select(node.criterion_id)
  expect(inspector()).toHaveTextContent('Complete symbolic operands not supplied')
  expect(inspector()).toHaveTextContent('Linked record unavailable: unavailable-record')
  expect(within(inspector()).queryByRole('button', { name: /Inspect evidence/ })).not.toBeInTheDocument()
})

test('renders supplied symbolic operands exactly without changing the backend assessment', () => {
  const data = softwareFixture()
  const node = data.assessment.decisions[0].assessment.assessments[2]
  node.criterion.comparator = '<='
  node.criterion.threshold = '1'
  node.criterion.unit = 'ECOG'
  render(<CriterionAssessments data={data} inspectEvidence={vi.fn()} />)
  select(node.criterion_id)
  expect(within(inspector()).getByText('ECOG <= 1 ECOG', { selector: 'code' })).toBeInTheDocument()
  expect(inspector()).toHaveTextContent(node.reason_code)
})

test.each(['real-set', 'nct-id', 'source-url', 'empty-real-set'])('blocks %s records without offering assessment or evidence actions', kind => {
  const data = softwareFixture()
  const assessment = data.assessment.decisions[0].assessment
  if (kind === 'real-set' || kind === 'empty-real-set') assessment.criteria_set.is_synthetic = false
  if (kind === 'nct-id') assessment.criteria_set.nct_id = 'NCT00000001'
  if (kind === 'source-url') assessment.assessments[0].criterion.source_url = 'https://clinicaltrials.gov/study/NCT00000001'
  if (kind === 'empty-real-set') assessment.assessments = []
  render(<CriterionAssessments data={data} inspectEvidence={vi.fn()} />)
  expect(screen.getByRole('alert')).toHaveTextContent('Real-protocol assessment blocked')
  expect(screen.queryByLabelText('Assessment state')).not.toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})
