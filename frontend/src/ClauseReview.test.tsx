import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import ClauseReview from './ClauseReview'
import { criterion, unreviewed } from './annotation'
import type { Candidate, Reference, Workspace } from './annotation'

const text = 'Inclusion Criteria:\n* ECOG 🧬 ≤ 1\n* Age ≥ 18\n  * Unless exception'
const points = Array.from(text)
function candidate(start: number, end: number, warnings: string[] = []): Candidate {
  return { id: `clause-${start}`, original: { text: points.slice(start, end).join(''), span: { start, end } }, suggested_polarity: 'inclusion', heading: { text: 'Inclusion Criteria:', span: { start: 0, end: 19 } }, context: null, warnings }
}
const secondStart = points.indexOf('*', 21)
const candidates = [candidate(20, secondStart - 1), candidate(secondStart, points.length, ['Nested clauses retained together'])]
const reference: Reference = { annotation_version: 'eligibility-reference-v1', annotation_revision: 1, nct_id: 'NCT01770353', snapshot_sha256: 'a'.repeat(64), annotation_origin: 'manual', inventory_review: unreviewed(), criteria: [] }
const workspace: Workspace = { source: { nct_id: reference.nct_id, text, sha256: reference.snapshot_sha256, source_snapshot: 'data/raw/trials/software/response.json', source_url: 'https://clinicaltrials.gov/study/NCT01770353', retrieval_timestamp: null, is_synthetic: null }, reference, candidates, slots: [], versions: [], snapshots: [] }
function Harness({ initial = reference, sourceWorkspace = workspace }: { initial?: Reference; sourceWorkspace?: Workspace }) {
  const [value, setValue] = useState(initial)
  return <><ClauseReview workspace={sourceWorkspace} reference={value} onChange={setValue} /><output data-testid="reference">{JSON.stringify(value)}</output></>
}
const result = () => JSON.parse(screen.getByTestId('reference').textContent!) as Reference

test('multiple clauses stay separate and exact, Unicode correction and typed evidence use code points', () => {
  render(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: /1\. inclusion/ }))
  expect(screen.getByLabelText('Value')).toHaveValue('')
  expect(screen.getByLabelText('Criterion polarity')).toHaveValue('')
  fireEvent.change(screen.getByLabelText('Value'), { target: { value: '1' } })
  fireEvent.change(screen.getByLabelText('Exception'), { target: { value: 'ECOG\n1' } })
  fireEvent.click(screen.getByText('Correct clause boundary'))
  fireEvent.change(screen.getByLabelText('Exact passage within this clause'), { target: { value: 'ECOG 🧬 ≤ 1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Use corrected passage' }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm draft' }))
  fireEvent.click(screen.getByRole('button', { name: /2\. inclusion/ }))
  expect(screen.getByText(/Nested clauses retained together\./)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Mark ambiguous' }))
  expect(result().criteria).toHaveLength(2)
  for (const item of result().criteria) expect(points.slice(item.original.span.start, item.original.span.end).join('')).toBe(item.original.text)
  const value = result().criteria[0].threshold_value as { evidence: { span: { start: number; end: number }; text: string }[]; review: { status: string } }
  expect(points.slice(value.evidence[0].span.start, value.evidence[0].span.end).join('')).toBe('1')
  expect(value.review.status).toBe('unreviewed')
  expect((result().criteria[0].exceptions as { value: string[] }).value).toEqual(['ECOG', '1'])
  expect(result().criteria[1].boundary_review.status).toBe('uncertain')
  expect(result().inventory_review.status).toBe('unreviewed')
  fireEvent.click(screen.getByRole('button', { name: /1\. inclusion/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm draft' }))
  expect(result().criteria).toHaveLength(2)
})

test('editing an approved criterion clears approvals and undo cannot resurrect them', () => {
  const node = criterion(candidates[0].id, candidates[0].original)
  const review = { status: 'reviewed' as const, reviewer: 'software-test-only', reviewed_at: '2026-10-25T00:00:00Z', note: 'Software fixture only' }
  node.boundary_review = review
  node.threshold_value = { value: '1', evidence: [], review }
  render(<Harness initial={{ ...reference, inventory_review: review, criteria: [node] }} />)
  fireEvent.click(screen.getByRole('button', { name: /1\. inclusion/ }))
  fireEvent.change(screen.getByLabelText('Value'), { target: { value: '0 to 1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm draft' }))
  expect(result().criteria[0].boundary_review.status).toBe('unreviewed')
  expect((result().criteria[0].threshold_value as { review: { status: string } }).review.status).toBe('unreviewed')
  expect(result().inventory_review.status).toBe('unreviewed')
  fireEvent.click(screen.getByRole('button', { name: 'Undo last draft change' }))
  expect(result().criteria[0].boundary_review.status).toBe('unreviewed')
  expect(result().inventory_review.status).toBe('unreviewed')
})


test('saved model proposals stay beside original clauses without importing semantic claims', () => {
  const sourceWorkspace: Workspace = { ...workspace, extraction_proposals: [{
    candidate_id: candidates[0].id, criterion_id: 'model-1', status: 'clinical_review',
    proposal: { original_text: 'Model quotation', criterion_type: 'inclusion', cohort: 'Model scope', logical_operator: null, dependencies: null },
    issues: [{ code: 'unresolved_logical_operator', field: null }],
  }] }
  render(<Harness sourceWorkspace={sourceWorkspace} />)
  fireEvent.click(screen.getByRole('button', { name: /1\. inclusion/ }))
  expect(screen.getByLabelText('Selected clause quotation')).toHaveTextContent(candidates[0].original.text)
  expect(screen.getByRole('region', { name: 'Saved model proposal' })).toHaveTextContent('Model quotation')
  expect(screen.getByText(/Compound meaning is unresolved/)).toBeInTheDocument()
  expect(screen.getByLabelText('Cohort restriction')).toHaveValue('')
  fireEvent.click(screen.getByRole('button', { name: 'Correct' }))
  expect(screen.getByLabelText('Comparison operator')).toHaveFocus()
  fireEvent.change(screen.getByLabelText('Value'), { target: { value: '1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm draft' }))
  expect(result().criteria[0].cohort).toMatchObject({ value: null })
  expect(result().criteria[0].threshold_value).toMatchObject({ value: '1', review: { status: 'unreviewed' } })
  expect(result().criteria[0].boundary_review.status).toBe('unreviewed')
  expect(result().inventory_review.status).toBe('unreviewed')
  fireEvent.click(screen.getByRole('button', { name: /2\. inclusion/ }))
  expect(screen.queryByRole('region', { name: 'Saved model proposal' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Skip' }))
  expect(result().criteria).toHaveLength(1)
})
