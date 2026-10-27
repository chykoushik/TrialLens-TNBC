import { useRef, useState } from 'react'
import type { Assessed, Evaluation, State } from './types'
import { Button, DataTable, EmptyState, Panel, StateBadge } from './ui'

const states: State[] = ['satisfied', 'violated', 'unknown', 'temporal', 'conflict']
const meanings: Record<State, string> = {
  satisfied: 'The clause is met under its mapped rules and evidence.',
  violated: 'The clause is not met under its mapped rules and evidence.',
  unknown: 'Evidence or an executable mapping is insufficient or unsupported.',
  temporal: 'A time requirement is unresolved or an elapsed requirement is not yet met.',
  conflict: 'Contradictory observations or a conflicting dependency remain unresolved.',
}
const shown = (value: string | null | undefined) => value ?? 'Not supplied'
type Decision = Evaluation['assessment']['decisions'][number]
type Row = { node: Assessed; root: Assessed; decision: Decision; depth: number }

function flatten(nodes: Assessed[], decision: Decision, depth = 0, root?: Assessed): Row[] {
  return nodes.flatMap(node => [{ node, root: root ?? node, decision, depth }, ...flatten(node.dependencies, decision, depth + 1, root ?? node)])
}

function LogicBranch({ node, selected, choose }: { node: Assessed; selected: string; choose: (id: string) => void }) {
  const control = <button className="logic-node" aria-label={`${node.criterion_id} ${node.state}`} aria-pressed={selected === node.criterion_id} onClick={() => choose(node.criterion_id)}><code>{node.criterion_id}</code><StateBadge state={node.state} /></button>
  return <li>{node.dependencies.length ? <details open><summary>{node.criterion.logical_operator} / {node.criterion_id}</summary>{control}<ul aria-label="Logical dependencies">{node.dependencies.map(child => <LogicBranch key={child.criterion_id} node={child} selected={selected} choose={choose} />)}</ul></details> : control}</li>
}

export default function CriterionAssessments({ data, inspectEvidence }: { data: Evaluation; inspectEvidence: (id: string) => void }) {
  const [state, setState] = useState('All states')
  const [polarity, setPolarity] = useState('All types')
  const [protocol, setProtocol] = useState('All protocols')
  const [selected, setSelected] = useState<string | null>(null)
  const inspector = useRef<HTMLElement>(null)
  const all = data.assessment.decisions.flatMap(decision => flatten(decision.assessment.assessments, decision))
  const blocked = data.assessment.decisions.some(decision => decision.assessment.criteria_set.is_synthetic === false || !!decision.assessment.criteria_set.nct_id)
    || all.some(({ node }) => !!node.criterion.nct_id || /^https:\/\/clinicaltrials\.gov\//.test(node.criterion.source_url ?? ''))
  if (blocked) return <EmptyState error title="Real-protocol assessment blocked" description="This workspace accepts fictional executable demonstration protocols only. Saved registry records and generated extractions remain in Trial Explorer; no assessment is enabled here." />
  const rows = all.filter(({ node, decision }) => (state === 'All states' || node.state === state) && (polarity === 'All types' || node.criterion.criterion_type === polarity) && (protocol === 'All protocols' || decision.trial_id === protocol))
  const key = (row: Row) => `${row.decision.trial_id}/${row.node.criterion_id}`
  const active = rows.find(row => key(row) === selected) ?? rows[0]
  const top = all.filter(row => row.depth === 0)
  const title = (decision: Decision) => data.protocol_titles?.[decision.trial_id] ?? decision.trial_id
  function choose(row: Row, focus = true) {
    setSelected(key(row))
    if (focus) requestAnimationFrame(() => { inspector.current?.focus(); inspector.current?.scrollIntoView?.({ block: 'start', behavior: 'auto' }) })
  }
  function resetFilters() { setState('All states'); setPolarity('All types'); setProtocol('All protocols') }
  const node = active?.node
  const records = node ? node.evidence_ids.flatMap(id => data.patient.evidence.filter(item => item.evidence_id === id)) : []
  const missingIds = node?.evidence_ids.filter(id => !data.patient.evidence.some(item => item.evidence_id === id)) ?? []
  const binding = node ? data.trials.flatMap(trial => trial.bindings).find(item => item.criterion.criterion_id === node.criterion_id) : undefined
  return <div className="reasoning-workspace">
    <section className="reasoning-summary" aria-label="Engine portfolio summary"><div><p className="eyebrow">FICTIONAL / SYMBOLIC REASONING</p><h2>Trace every condition.</h2><p>{data.assessment.decisions.length} fictional protocols / {top.length} top-level clauses</p></div><div><div className="reasoning-counts">{states.map(value => <div key={value}><StateBadge state={value} /><strong aria-label={`${value} top-level clauses`}>{top.filter(row => row.node.state === value).length}</strong></div>)}</div><p>Counts cover top-level clauses only; nested branches are not counted twice. Engine portfolio uncertainty: <code>{data.assessment.uncertainty}</code>. No eligibility score is calculated.</p></div></section>
    <details className="panel reasoning-guide"><summary>Read states and inclusion / exclusion polarity</summary><dl>{states.map(value => <div key={value}><dt><StateBadge state={value} /></dt><dd>{meanings[value]}</dd></div>)}</dl><p>Inclusion: satisfied means the required clause is met; violated means it is not met. Exclusion: satisfied means the excluding condition is observed; violated means that condition is not met and is not an exclusion blocker. Neither establishes overall eligibility.</p><p>Missing observations are not negative findings. Stale evidence does not establish current status. Conflicting records cannot be arbitrarily resolved. The engine retains unresolved dependencies in AND/OR groups rather than hiding them behind a resolved branch.</p></details>
    <div className="reasoning-filters"><label>Assessment state<select value={state} onChange={event => setState(event.target.value)}>{['All states', ...states].map(value => <option key={value}>{value}</option>)}</select></label><label>Criterion type<select value={polarity} onChange={event => setPolarity(event.target.value)}><option>All types</option><option>inclusion</option><option>exclusion</option></select></label><label>Fictional protocol<select value={protocol} onChange={event => setProtocol(event.target.value)}><option>All protocols</option>{data.assessment.decisions.map(decision => <option key={decision.trial_id} value={decision.trial_id}>{title(decision)}</option>)}</select></label><p role="status">{rows.length} of {all.length} clauses</p></div>
    <div className="reasoning-panels"><Panel title="Assessment matrix" eyebrow="ENGINE OUTPUT / ALL DEPTHS" className="reasoning-matrix">
      {data.assessment.decisions.filter(decision => protocol === 'All protocols' || decision.trial_id === protocol).map(decision => <section key={decision.trial_id}><h3>{title(decision)}</h3><p className="muted">Engine portfolio result: {decision.decision.replaceAll('_', ' ')}. Fictional rules only.</p>{(['inclusion', 'exclusion', null] as const).map(type => {
        const group = rows.filter(row => row.decision === decision && row.node.criterion.criterion_type === type)
        return group.length > 0 && <div key={type ?? 'unspecified'}><h4>{type === 'inclusion' ? 'Inclusion conditions' : type === 'exclusion' ? 'Exclusion conditions' : 'Unspecified polarity'}</h4><DataTable label={`${decision.trial_id} ${type ?? 'unspecified'} assessment matrix`}><thead><tr><th>Clause / dependency</th><th>State</th></tr></thead><tbody>{group.map(row => <tr key={key(row)} className={active && key(row) === key(active) ? 'is-selected' : ''}><td><button aria-label={`Inspect ${row.node.criterion_id}`} aria-pressed={!!active && key(row) === key(active)} onClick={() => choose(row)}><code>{row.node.criterion_id}</code><span>{row.depth ? `Dependency / depth ${row.depth}` : 'Top-level clause'}{row.node.dependencies.length ? ` / ${row.node.criterion.logical_operator}` : ''}</span></button></td><td><StateBadge state={row.node.state} /></td></tr>)}</tbody></DataTable></div>
      })}</section>)}
      {!rows.length && <EmptyState title="No matching clauses" description="Change a state, type or protocol filter." action={<Button onClick={resetFilters}>Clear filters</Button>} />}
    </Panel><section className="panel reasoning-inspector" ref={inspector} tabIndex={-1} aria-label="Criterion reasoning inspector">{active && node ? <>
      <p className="eyebrow">CLAUSE INSPECTION / FICTIONAL</p><div className="section-heading"><h2>{node.criterion_id}</h2><StateBadge state={node.state} /></div><p>{meanings[node.state]}</p><p className="reasoning-polarity">{node.criterion.criterion_type === 'exclusion' ? `Exclusion condition / ${node.state === 'satisfied' ? 'excluding condition observed' : node.state === 'violated' ? 'excluding condition not met; not an exclusion blocker' : 'unresolved'}` : node.criterion.criterion_type === 'inclusion' ? 'Inclusion condition / required clause' : 'Polarity not supplied'}</p>
      <h3>Original fictional protocol clause</h3><blockquote>{node.criterion.original_text}</blockquote>
      <h3>Symbolic representation</h3><code className="symbolic-expression">{node.dependencies.length ? `(${node.dependencies.map(child => child.criterion_id).join(` ${node.criterion.logical_operator} `)})` : node.criterion.biomarker && node.criterion.comparator && node.criterion.threshold !== null && node.criterion.threshold !== undefined ? `${node.criterion.biomarker} ${node.criterion.comparator} ${node.criterion.threshold}${node.criterion.unit ? ` ${node.criterion.unit}` : ''}` : 'Complete symbolic operands not supplied; original clause retained.'}</code>
      <dl className="evidence-metadata"><div><dt>Backend reason</dt><dd><code>{node.reason_code}</code></dd></div><div><dt>Explanation</dt><dd>{shown(node.explanation)}</dd></div><div><dt>Cohort</dt><dd>{shown(node.criterion.cohort)}</dd></div><div><dt>Required assay</dt><dd>{shown(node.criterion.assay)}</dd></div><div><dt>Temporal constraint</dt><dd>{shown(node.criterion.temporal_constraint)}</dd></div><div><dt>Assessment as of</dt><dd>{active.decision.assessment.context.as_of}</dd></div></dl>
      {node.state === 'temporal' && <p className="notice">The backend reports unresolved timing. An old observation is not necessarily current; a missing or future date or an unmet elapsed interval may also prevent resolution. No current value is inferred.</p>}
      {node.state === 'conflict' && <p className="notice">The engine retains contradictory observations or conflicting dependencies. No adjudication rule is supplied to choose a preferred record.</p>}
      <section><h3>Evidence & missing observations</h3><p className="muted">Backend-linked candidate records; association does not establish assay compatibility.</p>{records.map(item => <article className="reasoning-record" key={item.evidence_id}><strong>{data.display_labels?.[item.clinical_attribute] ?? item.clinical_attribute}: {item.value ?? 'No value recorded'} {item.units}</strong><p>{shown(item.assay)} / {shown(item.scoring_method)} / {item.observation_date ?? 'Date unknown'}</p>{item.value === null && <p>Missing observation ({item.availability ?? 'availability unknown'}), not a negative finding.</p>}{!node.dependencies.length && item.assay !== node.criterion.assay && <p className="notice">Assay-incompatible with this clause: required {shown(node.criterion.assay)}, recorded {shown(item.assay)}. {item.clinical_attribute === 'PD-L1' ? '22C3 CPS and SP142 IC are not interchangeable. No conversion is applied.' : 'No assay substitution is applied.'}</p>}<Button onClick={() => inspectEvidence(item.evidence_id)}>Inspect evidence {item.evidence_id}</Button></article>)}{!records.length && <p>No linked records are available in this patient evidence response. Missing observations are not negative findings.</p>}{missingIds.map(id => <p key={id}>Linked record unavailable: <code>{id}</code>. No evidence link can be opened.</p>)}{node.reason_code === 'missing_compatible_evidence' && <p className="notice">The backend found no usable assay-matched value for this clause. {binding?.clinical_attribute ?? node.criterion.biomarker ?? 'Required attribute'} remains unresolved.</p>}</section>
      <section><h3>Logical structure</h3><p className="muted">Select a branch to inspect it. Unresolved states are preserved exactly as returned.</p><ul className="reasoning-tree" aria-label="Logical reasoning tree"><LogicBranch node={active.root} selected={node.criterion_id} choose={id => { const row = all.find(row => row.decision === active.decision && row.node.criterion_id === id); if (row) { resetFilters(); choose(row, false) } }} /></ul></section>
      <details><summary>Protocol provenance</summary><p>{title(active.decision)}</p><p>{shown(node.criterion.source_url)}</p><p>Snapshot: {shown(active.decision.assessment.criteria_set.source_snapshot)}</p></details>
    </> : <EmptyState title="Select a criterion" description="A matching clause and its reasoning trace will appear here." />}</section></div>
  </div>
}
