import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'
import PatientEvidence from './PatientEvidence'
import fixture from './fixtures/tnbc_demo.json'
import type { Evaluation } from './types'

const softwareFixture = (name: 'baseline' | 'conflict' | 'stale') => structuredClone(fixture[name]) as Evaluation
const timeline = () => screen.getByRole('navigation', { name: 'Timeline dates' }).parentElement!
const inspector = () => screen.getByRole('region', { name: 'Evidence record inspector' })

test('orders actual timestamps and keeps unknown dates separate without inventing observations', () => {
  render(<PatientEvidence data={softwareFixture('baseline')} />)
  const dates = within(screen.getByRole('navigation', { name: 'Timeline dates' })).getAllByRole('link')
  expect(dates.at(-1)).toHaveTextContent('Date unknown')
  fireEvent.change(screen.getByLabelText('Evidence availability / limitation'), { target: { value: 'Missing' } })
  expect(within(timeline()).getAllByRole('button').length).toBeGreaterThan(0)
  expect(inspector()).toHaveTextContent('No observed value')
  expect(inspector()).toHaveTextContent('Not recorded')
  expect(screen.queryByText('satisfied')).not.toBeInTheDocument()
})

test('selects conflicting records together and exposes only actual protocol links', () => {
  render(<PatientEvidence data={softwareFixture('conflict')} />)
  fireEvent.change(screen.getByLabelText('Evidence availability / limitation'), { target: { value: 'Conflicting' } })
  const records = within(timeline()).getAllByRole('button')
  expect(records).toHaveLength(2)
  fireEvent.click(records[1])
  expect(records[1]).toHaveAttribute('aria-pressed', 'true')
  expect(within(inspector()).getByRole('heading', { name: 'Conflicting source records' })).toBeInTheDocument()
  expect(inspector()).toHaveTextContent('no adjudication or authority rule')
  expect(inspector()).toHaveTextContent('demo-brca-ecog')
  expect(inspector()).not.toHaveTextContent('demo-brca-hemoglobin')
})

test('explains assay mismatch and supports category filtering with recovery', () => {
  render(<PatientEvidence data={softwareFixture('baseline')} />)
  fireEvent.change(screen.getByLabelText('Evidence availability / limitation'), { target: { value: 'Assay-incompatible' } })
  expect(within(timeline()).getAllByRole('button')).toHaveLength(1)
  expect(inspector()).toHaveTextContent('22C3 CPS and SP142 IC')
  fireEvent.change(screen.getByLabelText('Evidence category'), { target: { value: 'Laboratory' } })
  expect(screen.getByText('No matching records')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
  expect(within(timeline()).getAllByRole('button').length).toBeGreaterThan(1)
})

test('labels stale only with an explicit freshness mapping and backend timing failure', () => {
  const data = softwareFixture('stale')
  for (const trial of data.trials) for (const binding of trial.bindings) {
    if (binding.clinical_attribute === 'hemoglobin') binding.temporal_rule = { kind: 'freshness', max_age_days: '14', source_text: binding.criterion.temporal_constraint! }
  }
  render(<PatientEvidence data={data} />)
  const dates = within(screen.getByRole('navigation', { name: 'Timeline dates' })).getAllByRole('link')
  expect(dates[0]).toHaveTextContent('2026-08-01')
  fireEvent.change(screen.getByLabelText('Evidence availability / limitation'), { target: { value: 'Stale' } })
  expect(within(timeline()).getAllByRole('button')).toHaveLength(1)
  expect(inspector()).toHaveTextContent('Hemoglobin')
  expect(inspector()).toHaveTextContent('Record reliabilityNot supplied')
})
