import { afterEach, expect, test, vi } from 'vitest'

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules() })

test.each(['/api', 'http://127.0.0.1:8000', 'http://127.0.0.1:8000/'])('annotation uses the shared API base %s', async base => {
  vi.stubEnv('VITE_API_BASE_URL', base)
  vi.resetModules()
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ source: 'software fixture' }) })
  vi.stubGlobal('fetch', fetcher)
  const { annotationApi } = await import('./annotation')
  await annotationApi('/annotations/NCT02648477')
  expect(fetcher.mock.calls[0][0]).toBe(`${base.replace(/\/$/, '')}/annotations/NCT02648477`)
})

test('generic route 404 explains routing while preserving source-specific errors', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: 'Not Found' }) }))
  const { annotationApi } = await import('./annotation')
  await expect(annotationApi('/annotations/NCT01770353')).rejects.toThrow('Check the API base URL')
})
