import { useEffect, useState } from 'react'
import { api } from './api'
import { Button } from './ui'

type Result = { reports: { id: string; criterion: number; cost: number; outcome: number; selection_probability: number; expected_entropy_reduction: number | null }[]; protocol_probabilities: number[]; entropy_bits: number; spent: number; budget: number; stop_probability: number; expected_policy_metrics: { risk: number; coverage: number; utility: number }; numerical_gap: number; risk_limit: number; bdd_nodes: number; cache: { hits: number; misses: number }; scope: string; boolean_graph: unknown; policy_decisions: { weight: number; decisions: number[] }[] }
export default function PaperPlanner() {
  const [scenarios, setScenarios] = useState<{ id: string; criteria: number; reports: number }[]>([])
  const [scenario, setScenario] = useState('')
  const [budget, setBudget] = useState(1)
  const [outcomes, setOutcomes] = useState<Record<string, number>>({})
  const [result, setResult] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    api<{ scenarios: typeof scenarios }>('/research/planner/scenarios', undefined, controller.signal).then(value => { if (!Array.isArray(value.scenarios)) throw new Error('Research scenarios unavailable.'); setScenarios(value.scenarios); setScenario(value.scenarios[0]?.id ?? '') }).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [retry])
  useEffect(() => {
    if (!scenario) return
    const controller = new AbortController()
    setBusy(true); setError(''); setResult(null)
    api<Result>('/research/planner/evaluate', { scenario, budget, outcomes }, controller.signal).then(setResult).catch(e => { if (!controller.signal.aborted) setError(e.message) }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [scenario, budget, outcomes, retry])
  return <section className="paper-planner"><p className="eyebrow">EXECUTABLE RESEARCH / SYNTHETIC SCENARIOS</p><h2>Which report should we review next?</h2><p>This runs the paper’s compiled Boolean inference and constrained adaptive planner. Choose a hypothetical report outcome to see how the next recommendation changes. These are abstract synthetic scenarios, not patient records.</p>
    <div className="search-form"><label>Research scenario<select value={scenario} disabled={busy} onChange={e => { setScenario(e.target.value); setOutcomes({}) }}>{scenarios.map((item, index) => <option key={item.id} value={item.id}>Scenario {index + 1}: {item.criteria} conditions, {item.reports} reports</option>)}</select></label><label>Review budget<select value={budget} disabled={busy} onChange={e => { setBudget(Number(e.target.value)); setOutcomes({}) }}><option value={0}>0 review units</option><option value={1}>1 review unit</option><option value={3}>3 review units</option></select></label><Button onClick={() => setOutcomes({})} disabled={busy}>Restart review</Button></div>
    {busy && <p role="status">Computing the constrained policy and source probabilities…</p>}{error && <div role="alert"><p>{error}</p><Button onClick={() => setRetry(value => value + 1)}>Retry planner</Button></div>}
    {result && <><div className="planner-summary" role="status"><p><strong>{result.spent} / {result.budget}</strong> review units used</p><p><strong>{result.entropy_bits.toFixed(3)} bits</strong> current uncertainty</p><p><strong>{(result.stop_probability * 100).toFixed(1)}%</strong> policy weight stops here</p></div>
      <h3>Available reports</h3><p>The planner may mix policies to meet its modeled error limit. Selection percentages show each action’s weight. Information gain explains uncertainty changes; it is not the optimization objective.</p><div className="search-results">{result.reports.map(report => <article key={report.id}><h3>Report {Number(report.id) + 1}</h3><p>Observes condition {report.criterion} · Cost {report.cost}</p><p>{report.outcome >= 0 ? `Reviewed: ${['negative', 'positive', 'unavailable'][report.outcome]}` : `${(report.selection_probability * 100).toFixed(1)}% policy weight recommends this report`}</p>{report.expected_entropy_reduction !== null && <p>Expected information gain: {report.expected_entropy_reduction.toFixed(3)} bits</p>}<label>Hypothetical outcome<select aria-label={`Outcome for report ${Number(report.id) + 1}`} value={report.outcome} disabled={busy || report.outcome >= 0 || result.spent + report.cost > budget || report.selection_probability <= 0} onChange={e => setOutcomes(previous => ({ ...previous, [report.id]: Number(e.target.value) }))}><option value={-1}>Choose to review</option><option value={0}>Negative</option><option value={1}>Positive</option><option value={2}>Unavailable</option></select></label></article>)}</div>
      <h3>Current modeled Boolean outcomes</h3>{result.protocol_probabilities.map((value, index) => <p key={index}>Synthetic protocol {index + 1}: {(value * 100).toFixed(1)}% probability its Boolean expression is true. This is not clinical eligibility.</p>)}
      <details><summary>Risk, abstention and reproducibility</summary><p>{result.scope}</p><p>Before review, this policy’s nominal expected error is {(result.expected_policy_metrics.risk * 100).toFixed(2)}% of all protocol opportunities; answer coverage is {(result.expected_policy_metrics.coverage * 100).toFixed(2)}%. Modelwise cap: {result.risk_limit * 100}%. These are root-policy expectations, not guarantees conditional on your chosen outcome.</p><p>Numerical optimization gap: {result.numerical_gap.toExponential(2)}. BDD nodes: {result.bdd_nodes}. Cached diagram hits: {result.cache.hits}, misses: {result.cache.misses}.</p><p>Decisions: −1 abstain, 0 false, 1 true. First entries refer to atomic conditions; final entries to protocol expressions.</p><pre>{JSON.stringify(result.policy_decisions, null, 2)}</pre><p>Boolean expressions from the frozen scenario (zero-based condition indices):</p><pre>{JSON.stringify(result.boolean_graph, null, 2)}</pre><p>Sources: research/compiled_review_v1/belief.py; research/certified_review_v1/belief.py; research/constrained_review_v1/factorized.py; results/recomb/20261026-compiled-review-v2/decision_cases.json. Cache reuse changes computation, not the scientific model. Three fixed reliability models do not provide the later continuous-interval certificate.</p></details>
    </>}
  </section>
}
