import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import { DEMO_STORAGE, loadSession, parseSession } from './demoSession'
import fixture from './fixtures/tnbc_demo.json'

const value = () => ({ version: 1, kind: 'fictional-tnbc-demo', savedAt: Date.now(), fixtureHash: 'a'.repeat(64), caseId: 'tnbc-record-gaps', step: 4, algorithm: 'adaptive_replan', budget: '3', outcomes: { 'review-germline-report': 'brca1-pathogenic' }, drafts: { 'review-pdl1-report': 'cps-15' } })
beforeEach(() => localStorage.clear())
afterEach(() => { localStorage.clear(); vi.unstubAllGlobals() })

test('strict storage parser rejects invalid versions, real records, unknown fields, expired data and malformed JSON', () => {
  expect(parseSession(JSON.stringify(value())).caseId).toBe('tnbc-record-gaps')
  for (const change of [{ version: 0 }, { caseId: 'NCT01770353' }, { patient: {} }, { savedAt: 0 }, { budget: '-1' }, { budget: 'NaN' }, { step: 7 }, { fixtureHash: 'bad' }, { algorithm: 'new' }, { outcomes: { '__proto__': 'bad', nct: 'real' } }]) {
    expect(() => parseSession(JSON.stringify({ ...value(), ...change }))).toThrow()
  }
  localStorage.setItem(DEMO_STORAGE, '{bad')
  expect(loadSession().notice).toContain('discarded')
  expect(localStorage.getItem(DEMO_STORAGE)).toBeNull()
})

function mock(restoreStatus = 200) {
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => ({ ok: !url.endsWith('/restore') || restoreStatus === 200, status: url.endsWith('/restore') ? restoreStatus : 200,
    json: async () => url.endsWith('/restore') ? restoreStatus === 200 ? { validated: true, session: JSON.parse(String(options?.body)) } : { detail: 'Temporarily unavailable' } : url.endsWith('/health') ? { status: 'ok' } : url.endsWith('/research/trials') ? { trials: [], warnings: [] } : url.endsWith('/cases') ? fixture.catalog : { ...structuredClone(fixture.baseline), demo_fixture_sha256: 'a'.repeat(64) } })))
}

test('restore checks backend before calculating, retains drafts and replays each committed review once', async () => {
  localStorage.setItem(DEMO_STORAGE, JSON.stringify(value()))
  mock()
  render(<App />)
  localStorage.setItem('unrelated-software-fixture', 'keep')
  await screen.findByText(/Fictional demonstration restored and checked/)
  fireEvent.click(screen.getByRole('button', { name: 'Try the demo' }))
  fireEvent.click(screen.getByText('Advanced Mode', { selector: 'summary' }))
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url, options]) => String(url).endsWith('/evaluate') && JSON.parse(String(options?.body)).outcomes['review-germline-report'] === 'brca1-pathogenic')).toBe(true))
  const requests = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/tnbc/session/restore'))
  expect(requests).toHaveLength(1)
  expect(screen.getByText('1 hypothetical reviews applied')).toBeInTheDocument()
  expect(JSON.parse(localStorage.getItem(DEMO_STORAGE)!).drafts).toEqual(value().drafts)
  fireEvent.click(screen.getByRole('button', { name: 'Start new demonstration' }))
  await waitFor(() => expect(screen.getByText('0 hypothetical reviews applied')).toBeInTheDocument())
  await waitFor(() => expect(JSON.parse(localStorage.getItem(DEMO_STORAGE)!).outcomes).toEqual({}))
  expect(localStorage.getItem('unrelated-software-fixture')).toBe('keep')
})

test('backend failure preserves the saved session and blocks restored calculations until retry or reset', async () => {
  const stored = JSON.stringify(value())
  localStorage.setItem(DEMO_STORAGE, stored)
  mock(503)
  render(<App />)
  await screen.findByRole('button', { name: 'Retry saved demonstration' })
  expect(localStorage.getItem(DEMO_STORAGE)).toBe(stored)
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/evaluate'))).toBe(false)
  mock()
  fireEvent.click(screen.getByRole('button', { name: 'Retry saved demonstration' }))
  await screen.findByText(/Fictional demonstration restored and checked/)
})

test('backend rejection discards incompatible history rather than executing it', async () => {
  localStorage.setItem(DEMO_STORAGE, JSON.stringify(value()))
  mock(409)
  render(<App />)
  await screen.findByText(/Saved fictional demonstration rejected/)
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url, options]) => String(url).endsWith('/evaluate') && Object.keys(JSON.parse(String(options?.body)).outcomes).length)).toBe(false))
})
