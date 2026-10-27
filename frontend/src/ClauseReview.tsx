import { useRef, useState } from 'react'
import { Button, Panel } from './ui'
import { clearReviews, criterion, unreviewed } from './annotation'
import type { Candidate, Criterion, Label, Quote, Reference, Workspace } from './annotation'

const fields = [['threshold_operator', 'Comparison operator'], ['threshold_value', 'Value'], ['unit', 'Unit'], ['temporal_constraint', 'Temporal qualifier'], ['cohort', 'Cohort restriction'], ['exceptions', 'Exception'], ['biomarker', 'Biomarker'], ['assay', 'Assay']] as const
const withinClause = (a: Quote, b: Quote) => a.span.start >= b.span.start && a.span.end <= b.span.end

export default function ClauseReview({ workspace, reference, onChange, onPendingChange }: { workspace: Workspace; reference: Reference; onChange: (next: Reference) => void; onPendingChange?: (pending: boolean) => void }) {
  const candidates = workspace.candidates ?? []
  const correctionFields = useRef<HTMLDetailsElement>(null)
  const [chosen, setChosen] = useState<Candidate | null>(null)
  const [draft, setDraft] = useState<Criterion | null>(null)
  const [skipped, setSkipped] = useState<string[]>([])
  const [history, setHistory] = useState<Reference[]>([])
  const [correction, setCorrection] = useState('')
  const [problem, setProblem] = useState('')
  const [notice, setNotice] = useState('')
  const [uncertainty, setUncertainty] = useState('')
  const [attribute, setAttribute] = useState('condition')
  const proposals = workspace.extraction_proposals?.filter(item => item.candidate_id === chosen?.id) ?? []
  const existing = chosen && reference.criteria.find(item => withinClause(item.original, chosen.original))
  const linked = draft && Array.from(workspace.source.text).slice(draft.original.span.start, draft.original.span.end).join('') === draft.original.text
  const count = candidates.filter(item => reference.criteria.some(node => withinClause(node.original, item.original))).length
  function select(item: Candidate) {
    onPendingChange?.(false)
    const saved = reference.criteria.find(node => withinClause(node.original, item.original))
    setUncertainty(saved?.boundary_review.note ?? ''); setAttribute((saved?.biomarker as Label | undefined)?.value ? 'biomarker' : (saved?.assay as Label | undefined)?.value ? 'assay' : 'condition'); setChosen(item); setDraft(structuredClone(saved ?? criterion(item.id, item.original))); setCorrection(item.original.text); setProblem(''); setNotice('')
  }
  function change(name: string, value: unknown) {
    if (!draft) return
    onPendingChange?.(true)
    let evidence: Quote[] = []
    const phrases = Array.isArray(value) ? value : typeof value === 'string' && name !== 'polarity' ? [value] : []
    for (const phrase of phrases) {
      const source = [draft.original, chosen?.context].find(item => item && item.text.includes(phrase))
      const index = source?.text.indexOf(phrase) ?? -1
      if (source && index >= 0 && phrase) {
        const start = source.span.start + Array.from(source.text.slice(0, index)).length
        evidence.push({ text: phrase, span: { start, end: start + Array.from(phrase).length } })
      }
    }
    if (name === 'polarity' && chosen?.heading) evidence = [chosen.heading]
    setNotice('Unconfirmed changes. Choose Confirm draft to include them in your saved work.'); setDraft({ ...clearReviews(draft), [name]: { value: value || null, evidence, review: unreviewed() } })
  }
  function commit(ambiguous = false) {
    if (!draft || !chosen || !linked) return
    const others = reference.criteria.filter(item => item.reference_id !== existing?.reference_id)
    if (others.some(item => item.original.span.start < draft.original.span.end && draft.original.span.start < item.original.span.end)) { setProblem('This overlaps another draft. Edit or delete that draft first.'); return }
    onPendingChange?.(false)
    setHistory([...history, structuredClone(reference)])
    const node = clearReviews(draft)
    node.boundary_review = { ...unreviewed(), status: ambiguous ? 'uncertain' : 'unreviewed', note: ambiguous ? uncertainty.trim() || 'Boundary or meaning needs human review.' : null }
    onChange({ ...reference, inventory_review: unreviewed(), criteria: [...others, node] })
    setSkipped(skipped.filter(id => id !== chosen.id)); setDraft(node); setProblem(''); setNotice(ambiguous ? 'Marked ambiguous. Formal review remains incomplete.' : 'Draft confirmed. Fields remain unreviewed; save to keep this version.')
  }
  function correct() {
    if (!draft || !chosen || !correction.trim()) return
    const index = chosen.original.text.indexOf(correction)
    if (index < 0 || chosen.original.text.indexOf(correction, index + 1) >= 0) { setProblem('Use one exact, unique passage from this clause. The source is never rewritten.'); return }
    const start = chosen.original.span.start + Array.from(chosen.original.text.slice(0, index)).length
    setDraft({ ...clearReviews(draft), original: { text: correction, span: { start, end: start + Array.from(correction).length } }, dependencies: [] })
    onPendingChange?.(true); setProblem(''); setNotice('Boundary corrected. Confirm this draft to apply it.')
  }
  return <>
    <p className="annotation-steps">Choose study → Review clauses → Confirm or mark uncertain → Save draft</p>
    <p role="status">{count} of {candidates.length} candidate clauses have drafts · {skipped.length} skipped this session · {reference.criteria.length} criteria. Inventory: {reference.inventory_review.status}.</p>
    <p>Formatting suggestions only. Confirm draft does not mark fields human-reviewed.</p>
    <div className="clause-workspace">
      <Panel title="Candidate clauses"><div className="clause-list" aria-label="Candidate clauses">{candidates.map((item, index) => <button type="button" key={item.id} className="clause-card" aria-pressed={chosen?.id === item.id} onClick={() => select(item)}><strong>{index + 1}. {item.suggested_polarity ?? 'Section unclear'} · {reference.criteria.some(node => withinClause(node.original, item.original)) ? 'Draft' : skipped.includes(item.id) ? 'Skipped' : 'To do'}</strong><span>{item.original.text}</span>{item.warnings.length > 0 && <small>Check boundary / context</small>}</button>)}</div>{!candidates.length && <p role="alert">Clause suggestions unavailable. Restart the local backend or use Advanced details.</p>}</Panel>
      <Panel title="Review clause">{draft && chosen ? <>
        <a href="#annotation-source-context" onClick={() => { const details = document.getElementById('annotation-source-context') as HTMLDetailsElement; if (details) details.open = true }}>✓ {linked ? 'Linked to exact saved source' : 'Source link invalid'}</a>
        {chosen.heading && <p>Source section: {chosen.heading.text}</p>}
        {chosen.context && <p>Source context: {chosen.context.text}</p>}
        {chosen.warnings.map(warning => <p key={warning} className="clause-warning">{warning}. Confirm the complete scope before labeling.</p>)}
        <p><strong>Original trial clause</strong></p>
        <blockquote aria-label="Selected clause quotation">{draft.original.text}</blockquote>
        {proposals.map(item => <section key={item.criterion_id} aria-label="Saved model proposal" className="clause-proposal">
          <h4>Proposed extraction ? not reviewed</h4><blockquote>{item.proposal.original_text}</blockquote>
          <dl>{[['criterion_type', 'Polarity'], ['cohort', 'Cohort'], ['biomarker', 'Biomarker'], ['assay', 'Assay'], ['comparator', 'Comparison'], ['threshold', 'Value'], ['unit', 'Unit'], ['temporal_constraint', 'Timing']].map(([key, label]) => item.proposal[key] != null && <div key={key}><dt>{label}</dt><dd>{String(item.proposal[key])}</dd></div>)}</dl>
          <p>{item.status === 'automatically_recovered' ? 'Source alignment checked. Clinical meaning still needs human review.' : 'Needs correction before use. Check the full clause and its scope.'}</p>
          {(item.proposal.logical_operator === null || item.issues.some(issue => issue.code.includes('logic'))) && <p>Compound meaning is unresolved. Do not assume how the conditions combine.</p>}
          <details><summary>Advanced Mode: model diagnostics</summary><pre>{JSON.stringify(item, null, 2)}</pre></details>
        </section>)}
        {proposals.length > 0 && <p>Compare the proposal with the original above. Enter only source-supported corrections below. Confirm draft saves your source-linked draft; model fields are never silently imported or marked reviewed.</p>}
        <details id="annotation-source-context"><summary>Source context</summary><p>{chosen.heading?.text}</p><blockquote>{chosen.original.text}</blockquote><a href={workspace.source.source_url} target="_blank" rel="noreferrer">Open ClinicalTrials.gov study</a></details>
        <details><summary>Correct clause boundary</summary><label>Exact passage within this clause<textarea value={correction} onChange={e => { setCorrection(e.target.value); onPendingChange?.(true) }} /></label><Button onClick={correct}>Use corrected passage</Button></details>
        <label>Criterion polarity<select value={(draft.polarity as Label).value as string ?? ''} onChange={e => change('polarity', e.target.value)}><option value="">Not specified</option><option value="inclusion">Inclusion</option><option value="exclusion">Exclusion</option></select></label>
        {chosen.suggested_polarity && <p>Section suggests {chosen.suggested_polarity}. Choose explicitly if applicable.</p>}
        <label>Clinical attribute<select value={attribute} onChange={e => setAttribute(e.target.value)}><option value="condition">General condition (original quotation)</option><option value="biomarker">Biomarker</option><option value="assay">Assay</option></select></label>
        <p>General attributes, including ECOG, stay in the quotation. Enter only source wording; numbers are never inferred.</p>
        <details ref={correctionFields}><summary>Add values, timing or restrictions (optional)</summary><div className="clause-form">{fields.filter(([name]) => !['biomarker', 'assay'].includes(name) || attribute === name || (draft[name] as Label).value).map(([name, title]) => <label key={name}>{title}{name === 'exceptions' ? <textarea value={((draft[name] as Label).value as string[] | null)?.join('\n') ?? ''} onChange={e => change(name, e.target.value.split('\n').filter(Boolean))} placeholder="One exact source phrase per line" /> : <input value={(draft[name] as Label).value as string ?? ''} onChange={e => change(name, e.target.value)} />}</label>)}</div></details>
        <label>Uncertainty note (optional)<input value={uncertainty} onChange={e => { setUncertainty(e.target.value); onPendingChange?.(true) }} /></label>
        {problem && <p role="alert">{problem}</p>}{notice && <p role="status">{notice}</p>}
        <div className="row"><Button variant="primary" disabled={!linked} onClick={() => commit()}>Confirm draft</Button><Button onClick={() => { if (correctionFields.current) { correctionFields.current.open = true; correctionFields.current.querySelector<HTMLInputElement>('input')?.focus() } }}>Correct</Button><Button onClick={() => commit(true)}>Mark ambiguous</Button><Button onClick={() => { onPendingChange?.(false); setSkipped([...new Set([...skipped, chosen.id])]); const next = candidates.find(item => item.id !== chosen.id && !skipped.includes(item.id) && !reference.criteria.some(node => withinClause(node.original, item.original))); if (next) select(next); else { setChosen(null); setDraft(null) } }}>Skip</Button>{existing && <><Button onClick={() => select(chosen)}>Edit</Button><Button onClick={() => { onPendingChange?.(false); setHistory([...history, structuredClone(reference)]); onChange({ ...reference, inventory_review: unreviewed(), criteria: reference.criteria.filter(item => item.reference_id !== existing.reference_id) }); setDraft(criterion(chosen.id, chosen.original)); setNotice('Draft deleted. Saved versions are unchanged.') }}>Delete draft</Button></>}</div>
      </> : <p>Select a clause from the list. Nothing is annotated automatically.</p>}
      <Button disabled={!history.length} onClick={() => { onPendingChange?.(false); const previous = history.at(-1)!; onChange({ ...previous, inventory_review: unreviewed(), criteria: previous.criteria.map(clearReviews) }); setHistory(history.slice(0, -1)); setChosen(null); setDraft(null); setNotice('Last draft change undone. Save a new version to persist it.') }}>Undo last draft change</Button>{!draft && notice && <p role="status">{notice}</p>}
      </Panel>
    </div>
  </>
}
