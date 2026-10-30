import { useEffect, useState } from 'react'
import { api } from './api'
import { Button } from './ui'

type Result = { manual_counterfactual: boolean; recommendation_available: boolean; reports: { id: string; criterion: number; cost: number; outcome: number; feasible: boolean; unavailable_reason: string | null; permitted_outcomes: number[]; selection_probability: number; expected_entropy_reduction: number | null }[]; protocol_probabilities: number[]; entropy_bits: number; spent: number; budget: number; stop_probability: number | null; expected_policy_metrics: { risk: number; coverage: number; utility: number }; numerical_gap: number; risk_limit: number; bdd_nodes: number; cache: { hits: number; misses: number }; scope: string; boolean_graph: unknown; policy_decisions: { weight: number; decisions: number[] }[] }
export default function PaperPlanner() {
  const [scenarios, setScenarios] = useState<{ id: string; criteria: number; reports: number }[]>([])
  const [scenario, setScenario] = useState('')
  const [budget, setBudget] = useState(1)
  const [manual, setManual] = useState(false)
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
    api<Result>('/research/planner/evaluate', { scenario, budget, outcomes, manual }, controller.signal).then(value => { if (!controller.signal.aborted) setResult(value) }).catch(e => { if (!controller.signal.aborted) setError(e.message) }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [scenario, budget, outcomes, manual, retry])
  const exhausted = result !== null && result.spent >= result.budget
  const available = result?.reports.filter(report => report.outcome < 0 && report.feasible).sort((a, b) => Number(b.selection_probability > 0) - Number(a.selection_probability > 0)) ?? []
  const reviewed = result?.reports.filter(report => report.outcome >= 0) ?? []
  const recommended = available.filter(report => report.selection_probability > 0)
  const reportName = (id: string) => `Report ${Number(id) + 1}`
  return <section className="paper-planner" aria-label="Evidence review demonstration">
    <p className="eyebrow">SYNTHETIC RESEARCH DEMONSTRATION</p>
    <h2>Choose a report. See what changes.</h2>
    <p>Explore how a limited review budget affects which evidence to examine next. These scenarios use hypothetical reports, not actual patient records or clinical eligibility assessments.</p>
    <p>The optimizer recommends reports within the scenario's budget and modeled error constraints. Choose a hypothetical outcome to update the model's estimates and see what can be reviewed next. No real report is ordered.</p>
    <div className="search-form">
      <label>Scenario<select aria-label="Scenario" value={scenario} disabled={busy} onChange={e => { setScenario(e.target.value); setOutcomes({}) }}>{scenarios.map((item, index) => <option key={item.id} value={item.id}>Scenario {index + 1}: {item.criteria} conditions, {item.reports} reports</option>)}</select></label>
      <label>Review budget<select aria-label="Review budget" value={budget} disabled={busy} onChange={e => { setBudget(Number(e.target.value)); setOutcomes({}) }}><option value={0}>0 review units</option><option value={1}>1 review unit</option><option value={3}>3 review units</option></select></label>
      <Button variant="primary" onClick={() => setOutcomes({})} disabled={busy}>Restart Review</Button>
    </div>
    <p>Changing the scenario or budget starts a fresh review.</p>
    {busy && <p role="status">Updating the review and recommendations...</p>}
    {error && <div role="alert"><p>{error}</p><Button onClick={() => setRetry(value => value + 1)}>Try again</Button></div>}
    {result && <>
      <div className="planner-summary" role="status"><p><strong>{result.spent} of {result.budget}</strong> review units used. <strong>{Math.max(0, result.budget - result.spent)}</strong> remaining.</p></div>
      {result.manual_counterfactual && <p role="note">Manual exploration results. The model's estimates have been recalculated. Choices on this path are your exploration, not optimizer recommendations.</p>}
      {exhausted ? <div role="status"><h3>Review budget exhausted</h3><p>No further reports can be reviewed under the current budget. Select Restart Review to explore different outcomes, or change the scenario or review budget above.</p></div> : <>
        {!result.manual_counterfactual && <div className="review-recommendation recommended-report"><h3>{recommended.length ? `Recommended next: ${recommended.map(report => reportName(report.id)).join(', ')}` : 'No further report is recommended'}</h3><p>{recommended.length ? 'Each recommended report checks the condition shown below. Its outcome can change the model estimates. The optimizer weighs its value against review cost and the modeled error constraints.' : 'The optimizer may stop even when some budget remains. You can explore other feasible reports manually.'}</p>{!!result.stop_probability && <p>The optimizer also assigns some weight to stopping here.</p>}</div>}
        {available.length > 0 && <><label className="manual-exploration"><input type="checkbox" checked={manual} disabled={busy} onChange={e => { setManual(e.target.checked); setOutcomes({}) }} />Manual exploration: choose any available report</label><p>Manual choices update the same model but are not optimizer recommendations. Switching modes starts a fresh review.</p>
          <h3>Hypothetical reports</h3><p>Choose Positive, Negative, or Unavailable to simulate a report result. Each choice uses the report's review units and recalculates the estimates below.</p>
          <div className="search-results">{available.map(report => <article key={report.id} className={report.selection_probability > 0 ? 'recommended-report' : undefined}>
            <h4>{reportName(report.id)}{report.selection_probability > 0 ? ' - Recommended' : ''}</h4>
            <p>Checks synthetic condition {report.criterion}. Uses {report.cost} review {report.cost === 1 ? 'unit' : 'units'}.</p>
            <p>{report.selection_probability > 0 ? 'Recommended by the optimizer.' : result.manual_counterfactual ? 'Available for manual exploration.' : 'Feasible alternative; not recommended at this step.'}</p>
            <label>Hypothetical outcome<select aria-label={`Outcome for report ${Number(report.id) + 1}`} value={report.outcome} disabled={busy || (!manual && report.selection_probability <= 0)} onChange={e => setOutcomes(previous => ({ ...previous, [report.id]: Number(e.target.value) }))}><option value={-1} disabled>Choose an outcome</option><option value={0} disabled={!report.permitted_outcomes.includes(0)}>Negative</option><option value={1} disabled={!report.permitted_outcomes.includes(1)}>Positive</option><option value={2} disabled={!report.permitted_outcomes.includes(2)}>Unavailable</option></select></label>
            {!manual && report.selection_probability <= 0 && <p>Enable manual exploration above to try this alternative.</p>}
          </article>)}</div>
        </>}
        {result.reports.some(report => report.outcome < 0 && !report.feasible) && <div><h3>Unavailable reports</h3><ul>{result.reports.filter(report => report.outcome < 0 && !report.feasible).map(report => <li key={report.id}>{reportName(report.id)}: {report.unavailable_reason ?? 'Unavailable under the current constraints.'}</li>)}</ul></div>}
      </>}
      {reviewed.length > 0 && <section><h3>Your hypothetical review</h3><ul>{reviewed.map(report => <li key={report.id}>{reportName(report.id)}: {['Negative', 'Positive', 'Unavailable'][report.outcome]} ({report.cost} review {report.cost === 1 ? 'unit' : 'units'})</li>)}</ul></section>}
      <section><h3>{reviewed.length ? 'Updated model estimates' : 'Starting model estimates'}</h3><p>These percentages describe whether each synthetic scenario's requirements hold in the model. They are not patient eligibility findings or clinical safety guarantees.</p>{result.protocol_probabilities.map((value, index) => <p key={index}>Synthetic protocol {index + 1}: {(value * 100).toFixed(1)}% modeled probability.</p>)}</section>
      <details><summary>Research Details</summary>
        <p>{result.scope}</p>
        <p>Policy weight is how often the optimizer selects an action at this step across its mixed policy. Zero weight means not recommended, not scientifically invalid. Information gain measures expected uncertainty reduction; it is not the optimization objective.</p>
        <p>Current uncertainty: {result.entropy_bits.toFixed(3)} bits. Stop weight: {result.stop_probability === null ? 'Not applicable on this manual path' : `${(result.stop_probability * 100).toFixed(1)}%`}.</p>
        <ul>{result.reports.map(report => <li key={report.id}>{reportName(report.id)}: {(report.selection_probability * 100).toFixed(1)}% policy weight; expected information gain: {report.expected_entropy_reduction === null ? 'not available' : `${report.expected_entropy_reduction.toFixed(3)} bits`}.</li>)}</ul>
        <p>{result.manual_counterfactual ? 'Reference only: the original optimizer policy. These metrics do not apply to your manual choices. ' : ''}Before review, this policy's nominal expected error is {(result.expected_policy_metrics.risk * 100).toFixed(2)}% of all protocol opportunities; answer coverage is {(result.expected_policy_metrics.coverage * 100).toFixed(2)}%. Modelwise cap: {result.risk_limit * 100}%. These are root-policy expectations, not guarantees conditional on your chosen outcome.</p>
        <p>Numerical optimization gap: {result.numerical_gap.toExponential(2)}. BDD nodes: {result.bdd_nodes}. Cached diagram hits: {result.cache.hits}, misses: {result.cache.misses}.</p>
        <p>Decisions: -1 abstain, 0 false, 1 true. First entries refer to atomic conditions; final entries to protocol expressions.</p><pre>{JSON.stringify(result.policy_decisions, null, 2)}</pre>
        <p>Boolean expressions from the frozen scenario (zero-based condition indices):</p><pre>{JSON.stringify(result.boolean_graph, null, 2)}</pre>
        <p>Sources: research/compiled_review_v1/belief.py; research/certified_review_v1/belief.py; research/constrained_review_v1/factorized.py; results/recomb/20261026-compiled-review-v2/decision_cases.json. Cache reuse changes computation, not the scientific model. Three fixed reliability models do not provide the later continuous-interval certificate.</p>
      </details>
    </>}
  </section>
}
