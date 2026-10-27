import { useId, useRef, useState } from 'react'
import type { Assessed, Evaluation } from './types'
import { Button, DataTable, EmptyState, Panel, StateBadge } from './ui'

export const algorithms = ['exact_nonadaptive', 'joint_greedy', 'adaptive_replan', 'risk_exact', 'risk_greedy', 'risk_adaptive', 'expected_per_cost', 'expected_reduction', 'random', 'affected_trials', 'uncertainty_only', 'cost_only', 'decisiveness_per_cost']
const strategyNotes: Record<string, string> = {
  exact_nonadaptive: 'Enumerates feasible review sets under the finite model and budget, maximizing expected utility. Execution order respects prerequisites; it is not an individual-record benefit ranking.',
  joint_greedy: 'Adds a prerequisite bundle with the greatest positive marginal expected utility per cost. Greedy choices need not be globally optimal. Requires empty review history.',
  adaptive_replan: 'Reveals one simulated review outcome, conditions the model on that history, then solves a new exact nonadaptive set problem. This is not a globally optimal adaptive policy.',
  risk_exact: 'Exact feasible-set selection with an assumed error-bound penalty. Utility accounts for the change in risk, not measured clinical accuracy.',
  risk_greedy: 'Greedy marginal utility per bundle cost with an assumed error-bound penalty. Requires empty review history; no global optimality guarantee.',
  risk_adaptive: 'Conditions on each simulated result and replans with an assumed error-bound penalty. This is not a globally optimal adaptive policy.',
  expected_per_cost: 'Baseline: expected uncertainty reduction per prerequisite-bundle cost.',
  expected_reduction: 'Baseline: greatest expected uncertainty reduction for a prerequisite bundle, without cost normalization.',
  random: 'Baseline: seeded random ranking, not expected benefit. Seed is fixed at 7.',
  affected_trials: 'Baseline: number of distinct targeted protocols, not predicted resolution.',
  uncertainty_only: 'Baseline: current expected unresolved weight of targeted protocols.',
  cost_only: 'Baseline: lowest prerequisite-bundle cost first, without benefit scoring.',
  decisiveness_per_cost: 'Baseline: optimistic best-outcome uncertainty reduction per bundle cost, not the expected reduction.',
}
const human = (value: string) => value.replaceAll('_', ' ')
export function modelNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined || !value.trim()) return null
  const parts = value.split('/')
  if (parts.length > 2 || parts.some(part => !part.trim() || !Number.isFinite(Number(part)))) return null
  const result = Number(parts[0]) / (parts.length === 2 ? Number(parts[1]) : 1)
  return Number.isFinite(result) ? result : null
}
function ValueBars({ label, values }: { label: string; values: { label: string; value: string | undefined; forecast?: boolean }[] }) {
  const scale = Math.max(0, ...values.map(item => Math.abs(modelNumber(item.value) ?? 0)))
  return <figure className="planning-bars" aria-label={label}><figcaption>{label}</figcaption>{values.map(item => <div key={item.label}><span>{item.label}{item.forecast ? ' / forecast' : ''}</span><strong>{item.value ?? 'Not returned'}</strong>{modelNumber(item.value) !== null && <div className={`planning-bar ${item.forecast ? 'is-forecast' : ''}`} aria-hidden="true"><span style={{ width: `${scale ? Math.abs(modelNumber(item.value) ?? 0) / scale * 100 : 0}%` }} /></div>}</div>)}</figure>
}
type Props = { drafts?: Record<string, string>; stage?: (id: string, outcome: string) => void; data: Evaluation | null; algorithm: string; mode: 'tnbc' | 'research'; budget: string; outcomes: Record<string, string>; selectedId: string | null; selectReview: (id: string) => void; changeAlgorithm: (value: string) => void; simulate: (id: string, outcome: string) => void; loading: boolean; failed: boolean }

export default function EvidencePrioritization({ data, algorithm, mode, budget, outcomes, selectedId, selectReview, changeAlgorithm, simulate, loading, failed, drafts: savedDrafts, stage }: Props) {
  const [stepIndex, setStepIndex] = useState(0)
  const controlId = useId()
  const [localDrafts, setLocalDrafts] = useState<Record<string, string>>({})
  const drafts = savedDrafts ?? localDrafts
  function stageDraft(id: string, outcome: string) { if (stage) stage(id, outcome); else setLocalDrafts(previous => ({ ...previous, [id]: outcome })) }
  const inspector = useRef<HTMLElement>(null)
  const controls = <section className="panel planning-strategy"><div><p className="eyebrow">FICTIONAL / EXISTING-RECORD REVIEW</p><h2>Review the record. Recalculate the plan.</h2><p>No test orders or medical recommendations. All outcomes are fictional simulations.</p></div><label>Algorithm<select value={algorithm} onChange={event => { setStepIndex(0); changeAlgorithm(event.target.value) }}>{algorithms.map(name => <option key={name} value={name} disabled={mode === 'tnbc' && name.startsWith('risk_')}>{human(name)}{mode === 'tnbc' && name.startsWith('risk_') ? ' (no reliability assumptions)' : ''}</option>)}</select></label><p className="planning-method">{strategyNotes[algorithm]}</p><p className="muted">Changing algorithm resets hypothetical reviews. Exact and adaptive methods support review history; greedy and baseline methods require an empty history. Baselines assume independent outcomes and may be rejected for joint models.</p></section>
  if (!data) return <div>{controls}<EmptyState title={loading ? 'Calculating review plan' : failed ? 'No current plan available' : 'Select a fictional scenario'} description={failed ? 'Adjust the budget or algorithm, reset hypothetical reviews, or retry with Refresh connection. Failed calculations do not retain stale proposals.' : 'The workspace uses the existing backend planner; no inference is run.'} /></div>
  const adaptive = algorithm === 'adaptive_replan' || algorithm === 'risk_adaptive'
  const nextId = adaptive ? data.next_review : data.plan.selected_items[0]
  const next = data.candidates.find(item => item.item_id === nextId)
  const selected = data.candidates.find(item => item.item_id === selectedId) ?? next ?? data.candidates[0]
  const candidates = [...data.candidates].sort((a, b) => {
    const first = data.plan.selected_items.indexOf(a.item_id), second = data.plan.selected_items.indexOf(b.item_id)
    return (first < 0 ? Infinity : first) - (second < 0 ? Infinity : second) || a.item_id.localeCompare(b.item_id)
  })
  const steps = data.plan.trace ?? data.plan.steps ?? []
  const step = steps[Math.min(stepIndex, Math.max(0, steps.length - 1))]
  const remaining = modelNumber(data.remaining_budget)
  const zeroUncertainty = modelNumber(data.assessment.uncertainty) === 0
  function inspect(id: string) {
    selectReview(id)
    requestAnimationFrame(() => { inspector.current?.focus(); inspector.current?.scrollIntoView?.({ block: 'start', behavior: 'auto' }) })
  }
  function findNode(nodes: Assessed[], id: string): Assessed | undefined {
    for (const node of nodes) { if (node.criterion_id === id) return node; const found = findNode(node.dependencies, id); if (found) return found }
  }
  return <div className="planning-workspace">{controls}
    <section className="planning-budget" aria-label="Review budget accounting">{[['Total budget / input', budget], ['Already spent', data.spent], ['Remaining', data.remaining_budget], ['Proposed additional cost', data.plan.spent]].map(([name, value]) => <div key={name}><span>{name}</span><strong>{value}</strong></div>)}<p>{data.cost_unit}. Proposed cost is a forecast; it has not been spent. Recorded spending reflects simulated review history.</p></section>
    <section className="planning-proposal" aria-label="Next proposed review"><div><p className="eyebrow">{adaptive ? 'NEXT REVIEW / CONDITIONAL REPLANNING' : 'FIRST IN PROPOSED PLAN / FORECAST'}</p><h2>{next?.description ?? 'No additional review proposed'}</h2><p>{adaptive ? 'Simulate one existing-record review, then inspect the fresh backend proposal.' : 'Execution order for the proposed set, not an independently optimal next-record ranking. The set forecast does not observe outcomes.'}</p>{next && <Button variant="primary" onClick={() => inspect(next.item_id)}>Inspect proposed record</Button>}</div><div><span className="planning-big-value">{data.plan.expected_reduction}</span><p>Expected portfolio uncertainty reduction / entire proposed set</p><p>Expected utility: {data.plan.expected_utility} / risk weight: {data.plan.risk_weight}</p>{data.plan.expected_error_bound !== null && <p>Expected assumed error bound: {data.plan.expected_error_bound}</p>}</div></section>
    {remaining === 0 && <div className="notice">No remaining review budget. Increase the total budget or reset hypothetical reviews to explore another plan.</div>}
    {zeroUncertainty && <div className="notice">Current engine uncertainty is zero. This does not establish clinical correctness; some baseline strategies may still spend budget.</div>}
    {!data.candidates.length && <EmptyState title="No reviewable existing records" description="This scenario supplies no candidate review actions. No new test or record is invented." />}
    {!data.plan.selected_items.length && data.candidates.length > 0 && <div className="notice">No additional review selected within this budget and objective. Costs, dependencies or the risk objective can prevent selection.</div>}
    <div className="planning-figures"><ValueBars label="Portfolio uncertainty: current versus expected" values={[{ label: 'Current / simulated evidence', value: data.assessment.uncertainty }, { label: 'After proposed set', value: data.plan.expected_final_uncertainty, forecast: true }]} /><ValueBars label="Review cost tradeoff" values={[{ label: 'Already spent', value: data.spent }, { label: 'Proposed additional cost', value: data.plan.spent, forecast: true }, { label: 'Remaining budget', value: data.remaining_budget }]} /></div>
    <p className="muted">{data.plan_scope}. Seed: 7. Values are model expectations in weighted protocol-decision uncertainty, not improved eligibility accuracy or real-world outcomes. Chart lengths approximate returned rational values; exact values remain printed.</p>
    <div className="planning-panels"><Panel title="Existing records to investigate" eyebrow="PROPOSED ORDER, THEN OTHER CANDIDATES" className="planning-list"><p className="muted">Plan position respects the selected strategy and prerequisites. Costs are per action; ranking traces may score prerequisite bundles.</p><ol>{candidates.map(item => {
      const position = data.plan.selected_items.indexOf(item.item_id)
      return <li key={item.item_id}><button aria-label={`Inspect review ${item.item_id}`} aria-pressed={selected?.item_id === item.item_id} onClick={() => inspect(item.item_id)}><span className="planning-position">{position < 0 ? '—' : String(position + 1).padStart(2, '0')}</span><span><strong>{item.description}</strong><small>{item.item_id} / {outcomes[item.item_id] ? 'Simulated review recorded' : position < 0 ? 'Outside proposed set' : 'Proposed'} / Cost {item.cost}</small></span></button></li>
    })}</ol>
      <details className="planning-trace"><summary>Backend ranking and selection trace</summary>{steps.length ? <><label>Forecast selection step<select value={Math.min(stepIndex, steps.length - 1)} onChange={event => setStepIndex(Number(event.target.value))}>{steps.map((_, index) => <option key={index} value={index}>Step {index + 1}</option>)}</select></label><p>Selected bundle target: {step?.selected ?? 'None'}. Later steps are conditional plan forecasts, not observed outcomes.</p><DataTable label="Backend bundle ranking"><thead><tr><th>Review bundle</th><th>Cost</th><th>Returned scores</th></tr></thead><tbody>{step?.ranking.map(row => <tr key={row.item_id}><td><button onClick={() => inspect(row.item_id)}>{row.item_id}</button><small>{row.bundle.join(' + ')}</small><small>{row.status ?? 'Scored candidate'}</small></td><td>{row.cost}</td><td>{row.score !== undefined && row.score !== null && <span>Strategy score: {row.score}<br /></span>}{row.delta_U !== undefined && <span>Expected reduction: {row.delta_U}<br /></span>}{row.delta !== undefined && <span>Marginal utility: {row.delta}</span>}</td></tr>)}</tbody></DataTable></> : <p>No per-record ranking trace returned. Plan-wide benefit is not allocated to individual records.{data.plan.feasible_sets_evaluated !== undefined && ` Exact feasible sets evaluated: ${data.plan.feasible_sets_evaluated}.`}</p>}</details>
    </Panel><section className="panel planning-inspector" ref={inspector} tabIndex={-1} aria-label="Review record inspector">{selected ? <><p className="eyebrow">EXISTING FICTIONAL RECORD</p><h2>{selected.description}</h2><p><code>{selected.item_id}</code></p><dl className="evidence-metadata"><div><dt>Review cost</dt><dd>{selected.cost} {data.cost_unit}</dd></div><div><dt>Prerequisites</dt><dd>{selected.depends_on.join(', ') || 'None'}</dd></div><div><dt>Plan membership</dt><dd>{data.plan.selected_items.includes(selected.item_id) ? 'Included in backend proposed set' : 'Not in backend proposed set'}</dd></div><div><dt>Selection basis</dt><dd>{strategyNotes[algorithm]} No additional per-record causal explanation is inferred.</dd></div></dl>
      <details><summary>Record provenance & assumptions</summary><p>{selected.existing_record.record_id}</p><p>{selected.existing_record.reference}</p><p>{selected.probability_basis ?? 'No probability basis supplied'}</p><p>{data.reliability?.assumption ?? 'No review reliability model supplied; risk-aware accuracy claims are unavailable.'}</p>{data.reliability?.conditional_error_probabilities[selected.item_id] && <pre>{JSON.stringify(data.reliability.conditional_error_probabilities[selected.item_id], null, 2)}</pre>}{data.dependence_groups.filter(group => group.item_ids.includes(selected.item_id)).map(group => <p key={group.item_ids.join(',')}>{human(group.relationship)}: {group.assumption}</p>)}</details>
      <h3>Portfolio impact / mapped conditions</h3><p>Declared target relationships, not predicted per-protocol improvements.</p>{selected.targets?.map(target => {
        const decision = data.assessment.decisions.find(item => item.trial_id === target.trial_id)
        const node = decision ? findNode(decision.assessment.assessments, target.criterion_id) : undefined
        return <article className="planning-target" key={`${target.trial_id}/${target.criterion_id}`}><strong>{data.protocol_titles?.[target.trial_id] ?? target.trial_id}</strong><p><code>{target.criterion_id}</code>{node && <> <StateBadge state={node.state} /></>}</p>{node ? <><p>{node.criterion.original_text}</p><p>Required assay: {node.criterion.assay ?? 'Not specified'}. Backend reason: {node.reason_code}.</p>{node.reason_code === 'missing_compatible_evidence' && <p className="notice">No compatible observed value. Assay-mismatched records are not substituted.{node.criterion.biomarker === 'PD-L1' && ' PD-L1 22C3 CPS and SP142 IC remain distinct.'}</p>}</> : <p>Clause detail not supplied in this response.</p>}</article>
      })}{!selected.targets?.length && <p>No criterion target mappings supplied.</p>}</> : <EmptyState title="Select an existing record" description="Provenance and declared protocol targets appear here." />}</section></div>
    <Panel title="Hypothetical review outcomes" eyebrow="SIMULATE / NEVER ALTER ORIGINAL RECORDS"><p>Choose a fictional report to update a copy of the evidence. Selection creates a draft. Apply simulated review requests a fresh backend calculation. Exact and adaptive methods support history; greedy and baseline methods require empty history. Algorithm changes reset these simulations.</p>{data.candidates.map((item, index) => {
      const unmet = item.depends_on.some(id => !outcomes[id])
      const overBudget = remaining !== null && (modelNumber(item.cost) ?? Infinity) > remaining
      const completed = Boolean(outcomes[item.item_id])
      return <div className="planning-simulation" key={item.item_id}><div><strong>{item.description}</strong><small id={`${controlId}-${index}`}>Cost {item.cost} / {completed ? `Simulated outcome: ${outcomes[item.item_id]}. Recorded hypothetical reviews are locked; use Reset hypothetical reviews to restore the original case.` : unmet ? 'Prerequisite review required' : overBudget ? 'Exceeds remaining budget' : 'Available to simulate'}</small></div><label>Simulated report for {item.description}<select aria-label={`Simulated report for ${item.item_id}`} aria-describedby={`${controlId}-${index}`} value={outcomes[item.item_id] || drafts[item.item_id] || ''} disabled={completed || unmet || overBudget} onChange={event => stageDraft(item.item_id, event.target.value)}><option value="">Not reviewed</option>{item.outcomes.map(outcome => <option key={outcome.outcome_id} value={outcome.outcome_id}>{outcome.outcome_id} / assumed P={outcome.probability ?? 'not supplied'}</option>)}</select></label><Button aria-label={`Apply simulated review ${item.item_id}`} disabled={completed || unmet || overBudget || !drafts[item.item_id]} onClick={() => simulate(item.item_id, drafts[item.item_id])}>Apply simulated review</Button></div>
    })}</Panel>
  </div>
}
