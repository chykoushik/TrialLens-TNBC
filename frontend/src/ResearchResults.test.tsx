import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import ResearchResults from './ResearchResults'

afterEach(() => vi.unstubAllGlobals())

test('configuration blockers are explicit without claiming a model request', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ sections: [], privacy: 'Aggregate outputs only.', inference: { ready: false, missing_variables: ['NEBIUS_API_KEY', 'NEBIUS_MODEL'], live_enabled: false, request_available: false, errors: ['configuration_error'] } }) })))
  render(<ResearchResults />)
  expect(await screen.findByText('Offline: live inference is not ready.')).toBeVisible()
  expect(screen.getByText(/separate protected operator workspace/)).toBeVisible()
  expect(screen.queryByText(/Missing server configuration/)).not.toBeInTheDocument()
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method)).toBe(true)
})

test('unavailable research has a retry action', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ detail: 'Research unavailable' }) })))
  render(<ResearchResults />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Research unavailable')
  fireEvent.click(screen.getByRole('button', { name: 'Retry research results' }))
  await screen.findByRole('alert')
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/research/results'))).toHaveLength(2)
})
