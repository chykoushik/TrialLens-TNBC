import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import ProtocolSource from './ProtocolSource'

test('reading blocks preserve original bullets, whitespace, punctuation and Unicode exactly', () => {
  const text = 'Inclusion Criteria:\n\n* 🧬 Marker A ≥ 1.5 units;\n  * Marker B, unchanged.\n2. Marker C (source wording).\n\nExclusion Criteria:\n\n* Condition D unless resolved.\n'
  render(<ProtocolSource text={text} highlight={null} />)
  const source = screen.getByLabelText('Exact original eligibility text')
  expect(source.textContent).toBe(text)
  expect(source.querySelectorAll('.source-reading-block')).toHaveLength(6)
  expect(screen.getByRole('button', { name: 'Jump to inclusion' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Jump to exclusion' })).toBeInTheDocument()
})

test('a quote spanning reading blocks highlights exactly the original Unicode range', () => {
  const text = 'Inclusion Criteria:\n\n* 🧬 Marker A ≥ 1.5 units;\n  * Marker B, unchanged.\n\nExclusion Criteria:\n* Condition C.'
  const start = Array.from('Inclusion Criteria:\n\n').length
  const quote = '* 🧬 Marker A ≥ 1.5 units;\n  * Marker B, unchanged.\n\n'
  const end = start + Array.from(quote).length
  const view = render(<ProtocolSource text={text} highlight={{ start, end }} />)
  const source = screen.getByLabelText('Exact original eligibility text')
  expect(source.textContent).toBe(text)
  expect(Array.from(source.querySelectorAll('mark'), mark => mark.textContent).join('')).toBe(quote)
  expect(screen.getByLabelText('Verified source passage')).toHaveTextContent('Marker A')
  expect(screen.getByLabelText('Verified source passage continuation')).toHaveTextContent('Marker B')
  view.rerender(<ProtocolSource text={text} highlight={null} />)
  expect(source.querySelector('mark')).toBeNull()
  expect(source.textContent).toBe(text)
})

test('short, unsectioned CRLF source retains its text without inferred criteria', () => {
  const text = 'Unsectioned source.\r\n\r\nOriginal wording; unchanged.'
  render(<ProtocolSource text={text} highlight={null} />)
  expect(screen.getByLabelText('Exact original eligibility text').textContent).toBe(text)
  expect(screen.queryByRole('button', { name: 'Jump to inclusion' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Verified source passage')).not.toBeInTheDocument()
})
