import { useEffect, useState } from 'react'
import type { Assessed, Evaluation, Evidence } from './types'
import { Button, EmptyState, Panel } from './ui'

type Quality = 'Observed' | 'Missing' | 'Stale' | 'Conflicting' | 'Assay-incompatible' | 'Time unresolved'
const categories: Record<string, string> = { ER: 'Biomarkers', PR: 'Biomarkers', HER2: 'Biomarkers', 'PD-L1': 'Biomarkers', gBRCA1: 'Biomarkers', gBRCA2: 'Biomarkers', hemoglobin: 'Laboratory', prior_checkpoint: 'Treatment history', prior_platinum: 'Treatment history', prior_parp: 'Treatment history' }
const present = (value: string | null | undefined) => value ?? 'Not recorded'
const recordDay = (item: Evidence) => item.observation_date && Number.isFinite(Date.parse(item.observation_date)) ? new Date(item.observation_date).toISOString().slice(0, 10) : 'Date unknown'

export default function PatientEvidence({ data, initialEvidenceId = null }: { data: Evaluation; initialEvidenceId?: string | null }) {
  const [selected, setSelected] = useState<string | null>(initialEvidenceId)
  const [category, setCategory] = useState('All categories')
  const [quality, setQuality] = useState('All evidence')
  useEffect(() => {
    if (!initialEvidenceId || !data.patient.evidence.some(item => item.evidence_id === initialEvidenceId)) return
    const frame = requestAnimationFrame(() => {
      const inspector = document.getElementById('evidence-inspector')
      inspector?.focus()
      inspector?.scrollIntoView?.({ block: 'start', behavior: 'auto' })
    })
    return () => cancelAnimationFrame(frame)
  }, [initialEvidenceId, data.patient.evidence])
  const label = (attribute: string) => data.display_labels?.[attribute] ?? attribute
  const links = data.assessment.decisions.flatMap(decision => {
    function leaves(nodes: Assessed[]): Assessed[] { return nodes.flatMap(node => node.dependencies.length ? leaves(node.dependencies) : [node]) }
    return leaves(decision.assessment.assessments).map(node => ({ node, trial: data.protocol_titles?.[decision.trial_id] ?? decision.trial_id, asOf: decision.assessment.context.as_of }))
  })
  function qualities(item: Evidence): Quality[] {
    const result: Quality[] = [item.value === null ? 'Missing' : 'Observed']
    for (const { node, asOf } of links.filter(link => link.node.evidence_ids.includes(item.evidence_id))) {
      if (item.value !== null && node.criterion.assay !== item.assay) result.push('Assay-incompatible')
      if (node.criterion.assay !== item.assay || item.value === null) continue
      if (node.reason_code === 'contradictory_observations') result.push('Conflicting')
      if (node.reason_code === 'evidence_time_unresolved') {
        const binding = data.trials.flatMap(trial => trial.bindings).find(binding => binding.criterion.criterion_id === node.criterion_id)
        const rule = binding?.temporal_rule
        const age = item.observation_date ? Date.parse(asOf) - Date.parse(item.observation_date) : NaN
        result.push(rule?.kind === 'freshness' && rule.source_text === node.criterion.temporal_constraint && rule.max_age_days !== null && age > Number(rule.max_age_days) * 86400000 ? 'Stale' : 'Time unresolved')
      }
    }
    return [...new Set(result)]
  }
  const records = [...data.patient.evidence].sort((a, b) => {
    const first = a.observation_date ? Date.parse(a.observation_date) : Infinity
    const second = b.observation_date ? Date.parse(b.observation_date) : Infinity
    return first - second || a.evidence_id.localeCompare(b.evidence_id)
  })
  const filtered = records.filter(item => (category === 'All categories' || (categories[item.clinical_attribute] ?? 'Clinical context') === category) && (quality === 'All evidence' || qualities(item).includes(quality as Quality)))
  const active = filtered.find(item => item.evidence_id === selected) ?? filtered[0]
  const attributes = [...new Set(data.trials.flatMap(trial => trial.bindings.map(binding => binding.clinical_attribute)).filter((attribute): attribute is string => attribute !== null))]
  const missing = attributes.filter(attribute => !records.some(item => item.clinical_attribute === attribute && item.value !== null))
  const groups = [...new Set(filtered.map(recordDay))]
  const related = active ? links.filter(link => link.node.evidence_ids.includes(active.evidence_id)) : []
  const peers = active && qualities(active).includes('Conflicting') ? records.filter(item => item.clinical_attribute === active.clinical_attribute && item.assay === active.assay) : []
  function selectRecord(id: string, focus = false) {
    setSelected(id)
    if (focus) requestAnimationFrame(() => document.getElementById('evidence-inspector')?.focus())
  }
  return <div className="evidence-workspace">
    <section className="evidence-intro"><div><p className="eyebrow">FICTIONAL RECORD COLLECTION</p><h2>Evidence, with its limits visible.</h2><p>{data.patient.patient_id}</p></div><p>Dates and values are supplied by the selected scenario. Evidence labels describe records and their protocol context, not the engine’s five criterion-assessment states.</p></section>
    <Panel title="Biomarker & clinical evidence" eyebrow="RECORDED OBSERVATIONS">
      <div className="evidence-overview">{[...new Set(records.map(item => item.clinical_attribute))].map(attribute => <div key={attribute}><h3>{label(attribute)}</h3>{records.filter(item => item.clinical_attribute === attribute).map(item => <button key={item.evidence_id} className="evidence-summary" onClick={() => { setCategory('All categories'); setQuality('All evidence'); selectRecord(item.evidence_id, true) }}><strong>{item.value ?? 'No value recorded'} {item.units}</strong><span>{item.assay ?? 'No assay recorded'}</span><span className="evidence-quality">{qualities(item).join(' / ')}</span></button>)}</div>)}</div>
      {!records.length && <EmptyState title="No observed evidence in this synthetic case." description="Missing values are not negative observations." />}
      <div className="notice"><strong>Attributes without recorded values</strong><span>{missing.map(label).join(', ') || 'None for the current protocol mappings'}. Assay compatibility and temporal validity are evaluated separately by the backend.</span></div>
    </Panel>
    <div className="evidence-filters"><label>Evidence category<select value={category} onChange={event => setCategory(event.target.value)}>{['All categories', ...new Set(records.map(item => categories[item.clinical_attribute] ?? 'Clinical context'))].map(value => <option key={value}>{value}</option>)}</select></label><label>Evidence availability / limitation<select value={quality} onChange={event => setQuality(event.target.value)}>{['All evidence', 'Observed', 'Missing', 'Stale', 'Conflicting', 'Assay-incompatible', 'Time unresolved'].map(value => <option key={value}>{value}</option>)}</select></label><p role="status">{filtered.length} of {records.length} fictional records</p></div>
    <div className="evidence-panels"><Panel title="Evidence chronology" eyebrow="OLDEST TO NEWEST" className="evidence-timeline">
      <p className="muted">UTC dates. Undated records remain separate.</p>
      <nav aria-label="Timeline dates" className="timeline-dates">{groups.map(group => <a key={group} href={`#evidence-date-${group}`}>{group}</a>)}</nav>
      {groups.map(group => <section key={group} id={`evidence-date-${group}`}><h3>{group}</h3><ol>{filtered.filter(item => recordDay(item) === group).map(item => <li key={item.evidence_id}><button aria-pressed={active?.evidence_id === item.evidence_id} onClick={() => selectRecord(item.evidence_id)}><span>{label(item.clinical_attribute)}</span><strong>{item.value ?? 'No value recorded'} {item.units}</strong><small>{item.assay ?? 'No assay recorded'} · {qualities(item).join(' / ')}</small></button></li>)}</ol></section>)}
      {!filtered.length && <EmptyState title="No matching records" description="Change the category or evidence limitation filter." action={<Button onClick={() => { setCategory('All categories'); setQuality('All evidence') }}>Clear filters</Button>} />}
    </Panel><section className="panel evidence-inspector" id="evidence-inspector" tabIndex={-1} aria-label="Evidence record inspector">
      <p className="eyebrow">RECORD INSPECTION / FICTIONAL</p>{active ? <><h2>{label(active.clinical_attribute)}</h2><p className="evidence-value">{active.value ?? 'No value recorded'} <small>{active.units}</small></p><p className="evidence-quality">{qualities(active).join(' / ')}</p><dl className="evidence-metadata">{Object.entries({ 'Original value': present(active.value), Unit: present(active.units), Availability: present(active.availability), 'Assay / method': present(active.assay), 'Scoring method': present(active.scoring_method), 'Specimen context': present(active.specimen_context), 'Observation timestamp': present(active.observation_date), Source: active.source, 'Record reliability': 'Not supplied by this evidence schema' }).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
        {active.value === null && <p className="notice">No observed value. {active.availability ?? 'Unknown availability'} does not mean a negative result.</p>}
        {qualities(active).includes('Assay-incompatible') && <p className="notice">This record’s assay differs from a linked criterion’s required assay. Candidate record links do not establish compatibility. {active.clinical_attribute === 'PD-L1' ? '22C3 CPS and SP142 IC are separate assay/scoring records; no conversion or substitution is applied.' : 'No assay conversion or substitution is applied.'}</p>}
        {peers.length > 1 && <section className="evidence-conflicts"><h3>Conflicting source records</h3><p>The backend reports contradictory observations. These records are retained together; no adjudication or authority rule is supplied to choose one.</p><div>{peers.map(item => <article key={item.evidence_id}><strong>{item.value} {item.units}</strong><p>{present(item.observation_date)}</p><code>{item.evidence_id}</code><p>{item.provenance.reference}</p></article>)}</div></section>}
        <details><summary>Original record provenance</summary><dl className="evidence-metadata"><div><dt>Evidence ID</dt><dd>{active.evidence_id}</dd></div><div><dt>Record ID</dt><dd>{active.provenance.record_id}</dd></div><div><dt>Reference</dt><dd>{active.provenance.reference}</dd></div></dl></details>
        <section className="evidence-relationships"><h3>Mapped fictional protocol conditions</h3><p>Backend candidate-record associations, not eligibility conclusions. Assay mismatch and unresolved timing remain explicit.</p>{related.map(({ node, trial, asOf }) => <details key={`${trial}-${node.criterion_id}`}><summary>{trial} / {node.criterion_id}</summary><p>{node.criterion.original_text}</p><p>Required assay: {present(node.criterion.assay)}. Record assay: {present(active.assay)}.</p><p>Temporal requirement: {present(node.criterion.temporal_constraint)}</p><p>Backend reason: <code>{node.reason_code}</code></p><p>Assessment reference time: {asOf}</p></details>)}{!related.length && <p>No backend record-to-criterion association supplied.</p>}</section>
      </> : <EmptyState title="Select an evidence record" description="Matching records and their original provenance will appear here." />}
    </section></div>
  </div>
}
