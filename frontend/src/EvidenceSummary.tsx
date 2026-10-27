import { useState } from 'react'
import type { Evaluation } from './types'
import { allNodes } from './demoPresentation'
import { Button } from './ui'

export default function EvidenceSummary({ data, compact = false }: { data: Evaluation; compact?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const conflicting = new Set(allNodes(data).filter(node => node.state === 'conflict').flatMap(node => node.evidence_ids))
  const groups = [
    { title: 'Recorded', detail: 'Values in the fictional records', items: data.patient.evidence.filter(item => item.value !== null && item.availability !== 'unavailable' && item.availability !== 'unknown' && !conflicting.has(item.evidence_id)), tone: 'known' },
    { title: 'Missing', detail: 'No usable value in these records', items: data.patient.evidence.filter(item => item.value === null || item.availability === 'unavailable' || item.availability === 'unknown'), tone: 'missing' },
    { title: 'Conflicting', detail: 'Records flagged by the reasoning engine', items: data.patient.evidence.filter(item => conflicting.has(item.evidence_id)), tone: 'conflicting' },
  ]
  return <section aria-label="Fictional evidence summary" className={`simple-evidence ${compact ? 'is-compact' : ''}`}><div className="evidence-strip">{groups.map(group => <div key={group.title} className={`evidence-column ${group.tone}`}><h3><span className="evidence-dot" />{group.title} <span>{group.items.length}</span></h3>{!compact && <p>{group.detail}</p>}<ul>{group.items.slice(0, expanded ? undefined : compact ? 2 : 5).map(item => <li key={item.evidence_id}><strong>{data.display_labels?.[item.clinical_attribute] ?? item.clinical_attribute}</strong><span>{item.value?.replaceAll('_', ' ') ?? 'Not recorded'} {item.units}</span>{!compact && item.assay && <small>{item.assay}</small>}</li>)}</ul>{!group.items.length && <p>{group.tone === 'conflicting' ? 'No conflicts flagged.' : 'None in this response.'}</p>}{!expanded && group.items.length > (compact ? 2 : 5) && <small>+ {group.items.length - (compact ? 2 : 5)} more</small>}</div>)}</div>{!compact && <Button variant="quiet" onClick={() => setExpanded(!expanded)}>{expanded ? 'Show fewer records' : 'Show all records'}</Button>}<small>{compact ? 'Missing does not mean negative.' : 'Recorded values can still be incompatible with a required assay or date. Missing does not mean negative.'}</small></section>
}
