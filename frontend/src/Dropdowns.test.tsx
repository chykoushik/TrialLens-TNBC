import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import PatientEvidence from './PatientEvidence'
import CriterionAssessments from './CriterionAssessments'
import fixture from './fixtures/tnbc_demo.json'
import type { Evaluation } from './types'

const research = ['scenario-a', 'scenario-b', 'scenario-c'].map(case_id => ({ case_id, trial_count: 2, review_count: 2, budgets: ['3'], unsupported: null }))
function renderApp() { render(<App />); fireEvent.click(screen.getByRole('button', { name: 'Research Tools' })) }

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => {
    if (url.endsWith('/health')) return { status: 'ok' }
    if (url.endsWith('/research/trials')) return { trials: [], warnings: [] }
    if (url.endsWith('/research/cases')) return research
    if (url.endsWith('/tnbc/cases')) return fixture.catalog
    return structuredClone(fixture.baseline)
  } })))
})

function change(label: string, value: string) {
  const select = screen.getByLabelText(label)
  expect(select).toBeEnabled()
  select.focus()
  expect(select).toHaveFocus()
  expect(fireEvent.mouseDown(select)).toBe(true)
  expect(fireEvent.keyDown(select, { key: 'ArrowDown' })).toBe(true)
  fireEvent.change(select, { target: { value } })
  expect(screen.getByLabelText(label)).toHaveValue(value)
  expect(screen.getByLabelText(label)).toBeEnabled()
}

test('cached case choices remain interactive during refresh and after catalog failure', async () => {
  renderApp()
  await screen.findByRole('option', { name: 'scenario-c' })
  const originalFetch = fetch
  let fail!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.endsWith('/research/cases')
    ? { ok: false, status: 503, json: () => new Promise(resolve => { fail = resolve }) } : originalFetch(url, options)))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh connection' }))
  change('Synthetic portfolio', 'scenario-b')
  await waitFor(() => expect(typeof fail).toBe('function'))
  await act(async () => { fail({ detail: 'Scenario refresh failed' }) })
  change('Synthetic portfolio', 'scenario-c')
  change('Synthetic portfolio', 'scenario-a')
})

test('late evaluations cannot replace the selected case after a second selection', async () => {
  renderApp()
  await screen.findByRole('option', { name: 'scenario-c' })
  const originalFetch = fetch
  let resolveOld!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.includes('/scenario-b/evaluate')
    ? { ok: true, json: () => new Promise(resolve => { resolveOld = resolve }) }
    : url.includes('/scenario-c/evaluate') ? { ok: true, json: async () => ({ ...fixture.baseline, case_title: 'Current software scenario' }) } : originalFetch(url, options)))
  change('Synthetic portfolio', 'scenario-b')
  await waitFor(() => expect(typeof resolveOld).toBe('function'))
  change('Synthetic portfolio', 'scenario-c')
  fireEvent.click(screen.getByRole('button', { name: 'Patient evidence' }))
  await waitFor(() => expect(screen.getByLabelText('Calculated scenario')).toHaveTextContent('Current software scenario'))
  await act(async () => { resolveOld({ ...fixture.baseline, case_title: 'Obsolete software scenario' }) })
  expect(screen.getByLabelText('Calculated scenario')).not.toHaveTextContent('Obsolete software scenario')
  expect(screen.getByLabelText('Synthetic portfolio')).toHaveValue('scenario-c')
  change('Synthetic portfolio', 'scenario-a')
})

test('reselecting the current mode does not clear catalogs or lock the case control', async () => {
  renderApp()
  await screen.findByRole('option', { name: 'scenario-c' })
  change('Application mode', 'research')
  change('Synthetic portfolio', 'scenario-b')
  change('Synthetic portfolio', 'scenario-b')
  change('Synthetic portfolio', 'scenario-c')
})

test('an obsolete mode catalog cannot replace the current catalog after rapid switches', async () => {
  renderApp()
  await screen.findByRole('option', { name: 'scenario-c' })
  const originalFetch = fetch
  let resolveOld!: (value: unknown) => void
  let requests = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.endsWith('/tnbc/cases') && requests++ === 0
    ? { ok: true, json: () => new Promise(resolve => { resolveOld = resolve }) } : originalFetch(url, options)))
  change('Application mode', 'tnbc')
  change('Application mode', 'research')
  await screen.findByRole('option', { name: 'scenario-c' })
  await act(async () => { resolveOld(fixture.catalog) })
  expect(screen.getByLabelText('Synthetic portfolio')).toHaveValue('scenario-a')
  expect(within(screen.getByLabelText('Synthetic portfolio')).getByRole('option', { name: 'scenario-b' })).toBeInTheDocument()
  change('Synthetic portfolio', 'scenario-c')
})

test('ordinary mode, case and algorithm selectors can change repeatedly after loading and evaluation failure', async () => {
  renderApp()
  await screen.findByRole('option', { name: 'scenario-c' })
  for (const value of ['scenario-b', 'scenario-c', 'scenario-a']) change('Synthetic portfolio', value)
  for (const value of ['tnbc', 'research', 'tnbc']) {
    change('Application mode', value)
    await waitFor(() => expect(screen.getByLabelText(value === 'tnbc' ? 'Fictional TNBC case' : 'Synthetic portfolio')).toBeEnabled())
  }
  for (const value of ['tnbc-record-gaps', 'tnbc-stale-labs', 'tnbc-conflicting-records']) change('Fictional TNBC case', value)
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Demo steps' })).getByRole('button', { name: /Prioritize existing/ }))
  fireEvent.click(screen.getByText('Research Details', { selector: 'summary' }))
  const originalFetch = fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.includes('/evaluate') && JSON.parse(String(options?.body)).algorithm === 'joint_greedy'
    ? { ok: false, status: 409, json: async () => ({ detail: 'Software fixture calculation failure' }) } : originalFetch(url, options)))
  change('Algorithm', 'joint_greedy')
  await screen.findByRole('alert')
  change('Algorithm', 'adaptive_replan')
  await screen.findByRole('region', { name: 'Next proposed review' })
  change('Algorithm', 'exact_nonadaptive')
  await screen.findByRole('region', { name: 'Next proposed review' })
  change('Fictional TNBC case', 'tnbc-record-gaps')
})

test('patient category and availability filters can change repeatedly without locking each other', () => {
  render(<PatientEvidence data={structuredClone(fixture.baseline) as Evaluation} />)
  for (const value of ['Laboratory', 'Biomarkers', 'Clinical context', 'All categories']) change('Evidence category', value)
  for (const value of ['Missing', 'Assay-incompatible', 'Observed', 'All evidence']) change('Evidence availability / limitation', value)
  change('Evidence category', 'Laboratory')
  change('Evidence availability / limitation', 'Conflicting')
  expect(screen.getByText('No matching records')).toBeInTheDocument()
  change('Evidence availability / limitation', 'All evidence')
  change('Evidence category', 'All categories')
})

test('criterion state, type and protocol filters remain interactive after repeated empty and populated results', () => {
  render(<CriterionAssessments data={structuredClone(fixture.baseline) as Evaluation} inspectEvidence={vi.fn()} />)
  for (const value of ['unknown', 'conflict', 'satisfied', 'All states']) change('Assessment state', value)
  for (const value of ['exclusion', 'inclusion', 'All types']) change('Criterion type', value)
  for (const value of ['demo-pdl1', 'demo-brca', 'All protocols']) change('Fictional protocol', value)
  expect(screen.getByRole('button', { name: 'Inspect demo-pdl1-pdl1' })).toBeEnabled()
})

test('ordinary selectors stay usable after simulation, navigation and reset while recorded reviews lock intentionally', async () => {
  renderApp()
  await screen.findByRole('option', { name: 'scenario-c' })
  fireEvent.click(screen.getByRole('button', { name: 'Evidence prioritization' }))
  fireEvent.change(await screen.findByLabelText('Simulated report for review-pdl1-report'), { target: { value: 'cps-15' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply simulated review review-pdl1-report' }))
  await waitFor(() => expect(screen.getByLabelText('Simulated report for review-pdl1-report')).toBeDisabled())
  const review = screen.getByLabelText('Simulated report for review-pdl1-report')
  expect(review).toHaveAccessibleDescription(/use Reset hypothetical reviews/)
  change('Algorithm', 'exact_nonadaptive')
  expect(review).toBeDisabled()
  change('Synthetic portfolio', 'scenario-a')
  expect(screen.getByLabelText('Simulated report for review-pdl1-report')).toHaveValue('cps-15')
  fireEvent.click(screen.getByRole('button', { name: 'Patient evidence' }))
  change('Evidence category', 'Laboratory')
  change('Evidence category', 'Biomarkers')
  change('Application mode', 'research')
  fireEvent.click(screen.getByRole('button', { name: 'Evidence prioritization' }))
  expect(screen.getByLabelText('Simulated report for review-pdl1-report')).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Reset hypothetical reviews' }))
  await waitFor(() => expect(screen.getByLabelText('Simulated report for review-pdl1-report')).toBeEnabled())
  change('Algorithm', 'adaptive_replan')
  change('Algorithm', 'joint_greedy')
  change('Algorithm', 'exact_nonadaptive')
  change('Synthetic portfolio', 'scenario-b')
  change('Synthetic portfolio', 'scenario-c')
})

test('closing mobile navigation removes the inert overlay and restores repeatable dropdown interaction', async () => {
  renderApp()
  await screen.findByRole('option', { name: 'scenario-c' })
  fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }))
  expect(screen.getByRole('main', { hidden: true })).toHaveAttribute('inert')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.getByRole('main')).not.toHaveAttribute('inert')
  change('Synthetic portfolio', 'scenario-b')
  change('Synthetic portfolio', 'scenario-c')
  change('Synthetic portfolio', 'scenario-a')
})

test('algorithm stays mounted and changeable through multiple pending calculations', async () => {
  renderApp()
  await screen.findByRole('option', { name: 'scenario-c' })
  fireEvent.click(screen.getByRole('button', { name: 'Evidence prioritization' }))
  const algorithm = screen.getByLabelText('Algorithm')
  const originalFetch = fetch
  let resolveOld!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => url.includes('/evaluate') && JSON.parse(String(options?.body)).algorithm === 'joint_greedy'
    ? { ok: true, json: () => new Promise(resolve => { resolveOld = resolve }) } : originalFetch(url, options)))
  change('Algorithm', 'joint_greedy')
  await waitFor(() => expect(typeof resolveOld).toBe('function'))
  expect(screen.getByLabelText('Algorithm')).toBe(algorithm)
  change('Algorithm', 'adaptive_replan')
  change('Algorithm', 'exact_nonadaptive')
  await screen.findByRole('region', { name: 'Next proposed review' })
  await act(async () => { resolveOld({ ...fixture.baseline, case_title: 'Obsolete algorithm result' }) })
  expect(screen.queryByRole('heading', { name: 'Obsolete algorithm result' })).not.toBeInTheDocument()
  expect(algorithm).toHaveValue('exact_nonadaptive')
  expect(algorithm).toBeEnabled()
})
