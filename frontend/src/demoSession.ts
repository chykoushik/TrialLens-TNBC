export const DEMO_STORAGE = 'triallens.fictional-demo.v1'
const cases = ['tnbc-record-gaps', 'tnbc-complete', 'tnbc-stale-labs', 'tnbc-conflicting-records']
export const algorithms = ['expected_per_cost', 'expected_reduction', 'random', 'affected_trials', 'uncertainty_only', 'cost_only', 'decisiveness_per_cost', 'joint_greedy', 'exact_nonadaptive', 'adaptive_replan', 'risk_greedy', 'risk_exact', 'risk_adaptive']
export type DemoSession = { version: 1; kind: 'fictional-tnbc-demo'; savedAt: number; fixtureHash: string; caseId: string; step: number; algorithm: string; budget: string; outcomes: Record<string, string>; drafts: Record<string, string> }
const keys = ['version', 'kind', 'savedAt', 'fixtureHash', 'caseId', 'step', 'algorithm', 'budget', 'outcomes', 'drafts']
function selections(value: unknown): value is Record<string, string> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length <= 10 && Object.entries(value).every(([key, item]) => /^review-[a-z0-9-]{1,60}$/.test(key) && typeof item === 'string' && /^[a-z0-9-]{1,60}$/.test(item))
}
export function parseSession(raw: string): DemoSession {
  if (raw.length > 8000) throw new Error('Invalid saved demonstration')
  const value = JSON.parse(raw)
  if (!value || typeof value !== 'object' || Object.keys(value).length !== keys.length || !keys.every(key => Object.hasOwn(value, key)) || value.version !== 1 || value.kind !== 'fictional-tnbc-demo' ||
    !cases.includes(value.caseId) || !algorithms.includes(value.algorithm) || !Number.isInteger(value.step) || value.step < 0 || value.step > 4 ||
    typeof value.fixtureHash !== 'string' || !/^[a-f0-9]{64}$/.test(value.fixtureHash) ||
    typeof value.budget !== 'string' || !/^\d{1,3}(\.\d{1,4})?$/.test(value.budget) || Number(value.budget) > 100 ||
    !Number.isSafeInteger(value.savedAt) || value.savedAt > Date.now() + 60000 || value.savedAt < Date.now() - 7 * 86400000 ||
    !selections(value.outcomes) || !selections(value.drafts) || Object.keys(value.drafts).some(key => key in value.outcomes)) throw new Error('Invalid saved demonstration')
  return value
}
export function loadSession(): { session: DemoSession | null; notice: string } {
  try {
    const raw = localStorage.getItem(DEMO_STORAGE)
    if (!raw) return { session: null, notice: '' }
    try { return { session: parseSession(raw), notice: '' } } catch {
      localStorage.removeItem(DEMO_STORAGE)
      return { session: null, notice: 'Invalid or expired fictional demonstration discarded.' }
    }
  } catch { return { session: null, notice: 'Browser storage unavailable. This demonstration will not survive reload.' } }
}
