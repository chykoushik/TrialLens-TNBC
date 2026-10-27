import { useEffect, useRef, useState } from 'react'
import ProtocolSource from './ProtocolSource'
import ClauseReview from './ClauseReview'
import { Button, EmptyState, Panel } from './ui'
import type { Trial } from './types'
import { annotationApi as api, captureSpan, clearReviews, criterion, editCriterion, flatten, unreviewed } from './annotation'
import type { Bundle, Criterion, Label, Quote, Reference, Review, Workspace } from './annotation'

const ids = ['NCT01770353', 'NCT02648477', 'NCT03538028', 'NCT04331067', 'NCT04691375']
const human = (value: string) => value.replaceAll('_', ' ')

export default function ProtocolAnnotation({ active, trials }: { active: boolean; trials: Trial[] }) {
  const [nct, setNct] = useState(ids[0]), [snapshot, setSnapshot] = useState('')
  const [workspace, setWorkspace] = useState<Workspace | null>(null), [reference, setReference] = useState<Reference | null>(null)
  const [selected, setSelected] = useState(''), [slot, setSlot] = useState('polarity'), [quote, setQuote] = useState<Quote | null>(null)
  const [reviewer, setReviewer] = useState(() => `local-draft-${crypto.randomUUID().slice(0, 8)}`), [note, setNote] = useState(''), [reviewStatus, setReviewStatus] = useState<Review['status']>('unreviewed')
  const [stage, setStage] = useState('draft'), [approval, setApproval] = useState(false), [parent, setParent] = useState<string | null>(null)
  const [version, setVersion] = useState(''), [json, setJson] = useState(''), [raw, setRaw] = useState(''), [value, setValue] = useState('')
  const [message, setMessage] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false), [reload, setReload] = useState(0)
  const [autoSave, setAutoSave] = useState(false)
  const [saveState, setSaveState] = useState<'idle' | 'unsaved' | 'saved' | 'error'>('idle')
  const [pendingClause, setPendingClause] = useState(false)
  const [documentKey, setDocumentKey] = useState(0)
  const [allowBroad, setAllowBroad] = useState(false)
  const [evaluationOptions, setEvaluationOptions] = useState('')
  const [operation, setOperation] = useState('edit'), [prediction, setPrediction] = useState(''), [evaluation, setEvaluation] = useState('')
  const validQuote = quote && workspace && Number.isInteger(quote.span.start) && Number.isInteger(quote.span.end) && quote.span.start >= 0 && quote.span.end > quote.span.start && quote.span.end <= Array.from(workspace.source.text).length && Array.from(workspace.source.text).slice(quote.span.start, quote.span.end).join('') === quote.text ? quote : null
  const broadSelection = Boolean(validQuote && (validQuote.text.length > 1200 || (workspace?.candidates ?? []).filter(item => item.original.span.start >= validQuote.span.start && item.original.span.end <= validQuote.span.end).length > 1))
  const sourcePane = useRef<HTMLDivElement>(null)
  const drafts = useRef(new Map<string, { reference: Reference; parent: string | null; selected: string }>())
  const serial = useRef(0)
  const nodes = reference ? flatten(reference.criteria) : []
  const current = nodes.find(node => node.reference_id === selected)
  const label = current?.[slot] as Label | undefined
  useEffect(() => {
    if (!active || workspace) return
    const controller = new AbortController()
    setBusy(true); setError('')
    api<Workspace>(`/annotations/${nct}${snapshot ? `?snapshot=${encodeURIComponent(snapshot)}` : ''}`, undefined, controller.signal)
      .then(result => { if (!controller.signal.aborted) {
        const retained = drafts.current.get(`${result.source.nct_id}/${result.source.source_snapshot}/${result.source.sha256}`)
        setWorkspace(result); setReference(retained?.reference ?? result.reference); setSelected(retained?.selected ?? ''); setQuote(null); setParent(retained?.parent ?? null); setVersion(retained?.parent ?? ''); setJson(''); setMessage(retained ? 'Restored session draft for this exact snapshot. Save a version to persist it.' : 'New unreviewed draft. No extraction has been imported.'); setEvaluation('')
      } })
      .catch(e => { if (!controller.signal.aborted) setError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [active, nct, snapshot, workspace, reload])
  useEffect(() => { setRaw(current ? JSON.stringify(current, null, 2) : '') }, [current])
  useEffect(() => { setValue(label?.value == null ? '' : typeof label.value === 'string' ? label.value : JSON.stringify(label.value)) }, [label])

  function remove(criteria: Criterion[], id: string): Criterion[] { return criteria.filter(node => node.reference_id !== id).map(node => ({ ...node, dependencies: remove(node.dependencies, id) })) }
  function changeSource(nextNct: string, nextSnapshot = '') {
    if (workspace && reference) drafts.current.set(`${workspace.source.nct_id}/${workspace.source.source_snapshot}/${workspace.source.sha256}`, { reference, parent, selected })
    setAutoSave(false); setSaveState('idle'); setPendingClause(false); setAllowBroad(false); setNct(nextNct); setSnapshot(nextSnapshot); setWorkspace(null); setReference(null); setApproval(false); setStage('draft'); setOperation('edit'); setError(''); setQuote(null)
  }
  function mutate(change: (value: Reference) => Reference) {
    if (!reference) return
    setReference({ ...change(reference), annotation_revision: reference.annotation_revision + 1 })
    setStage('draft'); setApproval(false); setMessage('Unsaved draft changes. Previous versions are preserved.'); setEvaluation('')
  }
  function edit(change: (node: Criterion) => Criterion) {
    mutate(ref => ({ ...ref, inventory_review: unreviewed(), criteria: editCriterion(ref.criteria, selected, change) }))
  }
  function review(): Review {
    if (!reviewer.trim() || (reviewStatus === 'reviewed' && reviewer.startsWith('local-draft-'))) throw new Error('Enter your human reviewer identifier in Advanced Mode before asserting human review.')
    return { status: reviewStatus, reviewer: reviewer.trim(), reviewed_at: reviewStatus === 'reviewed' ? new Date().toISOString() : null, note: note || null }
  }
  async function run(action: () => Promise<void> | void) {
    setBusy(true); setError(''); setMessage('')
    try { await action() } catch (e) { setSaveState('error'); setError(e instanceof Error ? e.message : 'Annotation operation failed') } finally { setBusy(false) }
  }
  function add(parentId?: string) {
    if (!validQuote || !reference || (broadSelection && !allowBroad)) return
    let id: string
    do { id = `manual-${++serial.current}` } while (nodes.some(node => node.reference_id === id))
    const item = criterion(id, validQuote)
    mutate(ref => ({ ...ref, inventory_review: unreviewed(), criteria: parentId ? editCriterion(ref.criteria, parentId, node => ({ ...node, boundary_review: unreviewed(), dependencies: [...node.dependencies, item] })) : [...ref.criteria, item] }))
    setSelected(id)
  }
  function commitSlot() {
    if (!current) return
    let parsed: unknown = value || null
    if (value && ['logic', 'exceptions', 'unsupported_semantics'].includes(slot)) parsed = JSON.parse(value)
    edit(node => ({ ...node, [slot]: { ...node[slot] as Label, value: parsed, review: unreviewed() } }))
  }
  function capture() {
    const pre = sourcePane.current?.querySelector('pre')
    if (!pre || !workspace) return
    const captured = captureSpan(pre, window.getSelection(), workspace.source.text)
    if (captured) { setQuote(captured); setAllowBroad(false) }
  }
  async function loadVersion(id: string) {
    const result = await api<{ bundle: Bundle; export_json: string }>(`/annotations/${nct}/versions/${id}`)
    setPendingClause(false); setDocumentKey(key => key + 1); setReference(result.bundle.reference); setParent(id); setVersion(id); setJson(result.export_json); setSelected(''); setStage('draft'); setApproval(false); setMessage(`Loaded ${result.bundle.audit.stage} version by ${result.bundle.audit.reviewer}. Editing creates a new version.`)
  }
  async function saveVersion(draftOnly = false) {
    if (!workspace || !reference) return
    setAutoSave(false)
    if (!draftOnly && stage !== 'draft' && reviewer.startsWith('local-draft-')) throw new Error('Replace the anonymous draft identifier with your human reviewer identifier before approval.')
    const revised = { ...reference, annotation_revision: reference.annotation_revision + 1 }
    const saveStage = draftOnly ? 'draft' : stage
    const result = await api<{ bundle: Bundle; export_json: string; path: string }>(`/annotations/${nct}/versions`, { snapshot: snapshot || workspace.snapshots[0].snapshot, reference: revised, reviewer, note: note.trim() || 'Manual clause annotation draft.', stage: saveStage, approve_review: draftOnly ? false : approval, parent, operation })
    setSaveState('saved'); setReference(revised); setParent(result.bundle.audit.version); setVersion(result.bundle.audit.version); setJson(result.export_json); setApproval(false); setWorkspace({ ...workspace, versions: [...workspace.versions, result.bundle.audit] })
    setMessage(draftOnly ? 'Draft saved. A new version is stored locally; previous versions are unchanged. Human review is not implied.' : `Saved new ${saveStage} version inside ${result.path}.`)
  }
  useEffect(() => {
    if (!active || !autoSave || busy || pendingClause || !workspace || !reference) return
    const timer = window.setTimeout(() => { setAutoSave(false); void run(() => saveVersion(true)) }, 800)
    return () => window.clearTimeout(timer)
  }, [active, autoSave, busy, pendingClause, workspace, reference, reviewer, note, parent])
  if (!active) return null
  return <section className="annotation-workspace" aria-label="Public protocol annotation"><fieldset disabled={busy} className="annotation-fields"><p className="eyebrow">HUMAN REFERENCE / PUBLIC PROTOCOLS ONLY</p><h2>Protocol annotation</h2><p>Review saved ClinicalTrials.gov eligibility clauses, one at a time. Public sources only; do not enter patient information. Drafts are not clinical reference truth.</p>
    <div className="annotation-controls"><label>Annotation study<select value={nct} disabled={busy} onChange={e => changeSource(e.target.value)}>{ids.map(id => <option key={id} value={id}>{id} / {trials.find(trial => trial.nct_id === id)?.title ?? 'Saved public study'}</option>)}</select></label>{workspace && <label>Annotation snapshot<select value={snapshot || workspace.snapshots[0]?.snapshot} disabled={busy} onChange={e => changeSource(nct, e.target.value)}>{workspace.snapshots.map(item => <option value={item.snapshot} key={item.snapshot}>{item.retrieved_at ?? 'Retrieval unknown'} / {item.snapshot}</option>)}</select></label>}</div>
    {busy && <p role="status">Working with local annotation files?</p>}{error && <div role="alert" className="error">{error}{!workspace && <Button onClick={() => { setWorkspace(null); setReload(value => value + 1) }}>Reload source</Button>}</div>}{message && <p role="status">{message}</p>}
    {!workspace || !reference ? <EmptyState title="Select a saved source" description="Sources load from local immutable snapshots." /> : <>
      <ClauseReview key={`${documentKey}/${workspace.source.nct_id}/${workspace.source.source_snapshot}/${workspace.source.sha256}`} workspace={workspace} reference={reference} onPendingChange={setPendingClause} onChange={next => { mutate(() => next); setSaveState('unsaved'); setAutoSave(true) }} />
      <section className="annotation-savebar" aria-label="Draft saving"><span role="status">{busy ? 'Saving / checking local files?' : pendingClause ? 'Current clause has unconfirmed edits.' : saveState === 'unsaved' ? 'Unsaved changes. Draft saving is pending.' : saveState === 'saved' ? 'Draft saved locally. Previous versions are preserved.' : saveState === 'error' ? 'Draft not saved. Retry when the local server is available.' : 'Drafts save automatically after confirmation.'}</span><Button variant="quiet" disabled={busy || pendingClause || !reviewer.trim()} onClick={() => run(() => saveVersion(true))}>Save draft</Button><small>Local anonymous draft identity: {reviewer.startsWith('local-draft-') ? reviewer : 'custom identifier'}. No human approval is implied.</small>{pendingClause && <p>Confirm or mark ambiguous to keep the current edits. Skip discards unconfirmed edits.</p>}</section>
      <details className="annotation-advanced"><summary>Advanced Mode: annotation details</summary><label>Reviewer identifier or pseudonym<input value={reviewer} maxLength={100} onChange={e => setReviewer(e.target.value)} /></label><p>The local-draft identifier is an anonymous software audit identity, not a human review claim.</p>
      <p>Working copy / save stage proposal: {stage}. Saved parent: {workspace.versions.find(item => item.version === parent)?.stage ?? 'None'}. Review status is never inferred from schema validity.</p><p><a href={workspace.source.source_url} target="_blank" rel="noreferrer">ClinicalTrials.gov source</a> / {workspace.source.retrieval_timestamp ?? 'Retrieval date unknown'}</p><p className="annotation-hash">Snapshot SHA-256: <code>{workspace.source.sha256}</code></p>
      <details><summary>Annotation guideline</summary><p>Keep complete clauses and inherited cohort or temporal qualifiers. Inclusion means a required condition; exclusion means an excluding condition, not an inverted inclusion. Copy exact text without normalization. AND/OR operands must be ordered, contained and non-overlapping. Retain exceptions and record ambiguity as uncertain or unsupported with a note.</p><p>Offsets count Unicode code points from zero with an exclusive end, not UTF-16 or bytes. Select text with a mouse or Shift + arrow keys, or enter exact offsets below. Lines and section headings are navigation aids, not automatic criterion boundaries.</p><p>Review boundaries and each label separately. Reviewed absence needs an explanation; reviewed values need exact source evidence. Mark the inventory reviewed only after checking the entire section. Editing values clears the affected approval and inventory completeness. Independently adjudicated requires a different reviewer and a saved reviewed parent. Identifiers are self-declared; software cannot establish expertise or independence.</p></details>
      <div className="annotation-columns"><Panel title="Exact eligibility source"><div ref={sourcePane} onMouseUp={capture} onKeyUp={capture}><ProtocolSource text={workspace.source.text} highlight={validQuote?.span ?? null} /></div>{validQuote && broadSelection && <label><input type="checkbox" checked={allowBroad} onChange={e => setAllowBroad(e.target.checked)} />This selection is long or includes multiple clauses. I checked that the full clause and its dependencies belong together.</label>}<p>Selected span: {quote ? `[${quote.span.start}, ${quote.span.end})` : 'None'}</p><div className="annotation-controls"><label>Span start<input type="number" min="0" value={quote?.span.start ?? ''} onChange={e => { const start = Number(e.target.value), end = quote?.span.end ?? start; setAllowBroad(false); setQuote({ span: { start, end }, text: Array.from(workspace.source.text).slice(start, end).join('') }) }} /></label><label>Span end<input type="number" min="0" value={quote?.span.end ?? ''} onChange={e => { const end = Number(e.target.value), start = quote?.span.start ?? 0; setAllowBroad(false); setQuote({ span: { start, end }, text: Array.from(workspace.source.text).slice(start, end).join('') }) }} /></label></div><blockquote>{quote?.text}</blockquote><Button disabled={busy || !validQuote?.text || (broadSelection && !allowBroad)} onClick={() => add()}>Create criterion from span</Button>{current && <Button disabled={busy || !validQuote?.text} onClick={() => add(current.reference_id)}>Add dependency to selected criterion</Button>}<p>Source offsets are preserved; schema validation rejects invalid or overlapping spans.</p></Panel>
      <Panel title="Criterion draft & review"><label>Annotation criterion<select value={selected} onChange={e => { setSelected(e.target.value); setQuote(nodes.find(node => node.reference_id === e.target.value)?.original ?? null) }}><option value="">Select a criterion</option>{nodes.map(node => <option value={node.reference_id} key={node.reference_id}>{node.reference_id} / {node.boundary_review.status} / [{node.original.span.start}, {node.original.span.end})</option>)}</select></label>{current ? <><blockquote>{current.original.text}</blockquote><p>Boundary: {current.boundary_review.status}</p><Button onClick={() => mutate(ref => ({ ...ref, inventory_review: unreviewed(), criteria: remove(ref.criteria, selected) }))}>Remove selected criterion</Button><label>Structured field<select value={slot} onChange={e => setSlot(e.target.value)}>{workspace.slots.map(name => <option value={name} key={name}>{human(name)}</option>)}</select></label><label>Field value {['logic', 'exceptions', 'unsupported_semantics'].includes(slot) ? '(JSON)' : '(verbatim, except polarity)'}<textarea value={value} onChange={e => setValue(e.target.value)} /></label><p>For logic: {`{"operator":"AND","span":{"start":0,"end":10},"children":[...]}`}. Exceptions use a JSON string array; unsupported semantics uses true or false. Empty means null, never a reviewed absence.</p><Button onClick={() => run(commitSlot)}>Set draft field value</Button><Button disabled={!validQuote?.text} onClick={() => edit(node => ({ ...node, [slot]: { ...node[slot] as Label, evidence: [...(node[slot] as Label).evidence, quote!], review: unreviewed() } }))}>Add selected source evidence</Button><Button onClick={() => edit(node => ({ ...node, [slot]: { ...node[slot] as Label, evidence: [], review: unreviewed() } }))}>Clear field evidence</Button><p>Field status: {label?.review.status} / Evidence quotes: {label?.evidence.length ?? 0}</p>
      <label>Explicit review status<select value={reviewStatus} onChange={e => setReviewStatus(e.target.value as Review['status'])}><option value="unreviewed">Draft / unreviewed</option><option value="uncertain">Uncertain / unresolved</option><option value="reviewed">Human reviewed</option></select></label><label>Review and audit note<textarea value={note} maxLength={4000} onChange={e => setNote(e.target.value)} /></label><Button onClick={() => run(() => { const status = review(); edit(node => ({ ...node, boundary_review: status })) })}>Set boundary review status</Button><Button onClick={() => run(() => { const status = review(); edit(node => ({ ...node, [slot]: { ...node[slot] as Label, review: status } })) })}>Set field review status</Button>
      <details><summary>Nested criterion JSON / correction</summary><p>Uses the existing ReferenceCriterion schema, including dependencies and logic. Applying a correction clears all approvals on this criterion and its dependencies. No automatic repair is performed.</p><label>Criterion JSON<textarea className="annotation-json" value={raw} onChange={e => setRaw(e.target.value)} /></label><Button onClick={() => run(() => { const updated = JSON.parse(raw) as Criterion; if (updated.reference_id !== selected) throw new Error('Keep the criterion ID when correcting.'); edit(() => clearReviews(updated)) })}>Apply criterion correction</Button></details></> : <p>Select source text and create an unreviewed criterion. No labels are pre-populated.</p>}</Panel></div>
      <Panel title="Inventory, versions & audit"><p>Inventory status: {reference.inventory_review.status}. Mark reviewed only after a person checks every top-level boundary and the complete source section. This does not review missing semantic fields.</p><Button onClick={() => run(() => { const status = review(); mutate(ref => ({ ...ref, inventory_review: status })) })}>Set inventory review status</Button><label>Audit note for save<textarea value={note} maxLength={4000} onChange={e => setNote(e.target.value)} /></label><label>Save stage<select value={stage} onChange={e => { setStage(e.target.value); setApproval(false) }}><option value="draft">Draft / not approved for evaluation</option><option value="reviewed">Explicit human review</option><option value="adjudicated">Independent adjudication</option></select></label>{stage !== 'draft' && <label><input type="checkbox" checked={approval} onChange={e => setApproval(e.target.checked)} />I explicitly approve the reviewed labels; I have checked the source and review claims.</label>}
      <div className="row"><Button disabled={busy} onClick={() => run(async () => { const result = await api<{ coverage: unknown }>(`/annotations/${nct}/validate`, { snapshot: snapshot || workspace.snapshots[0].snapshot, reference }); setMessage(`Schema and source checks passed. Coverage: ${JSON.stringify(result.coverage)}. This is not semantic approval.`) })}>Validate annotation</Button><Button disabled={busy || pendingClause || !reviewer.trim() || !note.trim() || (stage !== 'draft' && !approval)} onClick={() => run(() => saveVersion())}>Save new version & export JSON</Button></div>
      <label>Saved annotation version<select value={version} disabled={busy} onChange={e => { if (e.target.value) run(() => loadVersion(e.target.value)) }}><option value="">Choose saved version</option>{workspace.versions.map(item => <option value={item.version} key={item.version}>{item.saved_at} / {item.stage} / {item.reviewer}</option>)}</select></label><ol>{workspace.versions.map(item => <li key={item.version}><code>{item.version}</code> / {item.stage} / {item.reviewer} / {item.saved_at}<p>{item.note} / parent: {item.parent ?? 'None'}</p></li>)}</ol>
      <details><summary>Deterministic JSON export / import</summary><p>Export bytes are stable for a saved version. The backend saves both export.json and the unchanged benchmark-format reference.json inside the project. Paste a review bundle here to import; imported review claims remain a local draft until explicitly approved. Imports never establish adjudication.</p><label>Review bundle JSON<textarea className="annotation-json" value={json} onChange={e => setJson(e.target.value)} /></label><Button disabled={busy || !json} onClick={() => run(async () => {
        const bundle = JSON.parse(json) as Bundle
        if (bundle.snapshot !== (snapshot || workspace.snapshots[0].snapshot)) throw new Error('Select the exact imported snapshot first.')
        const result = await api<{ reference: Reference; message: string }>(`/annotations/${nct}/import`, bundle)
        setPendingClause(false); setDocumentKey(key => key + 1); setReference(result.reference); setParent(null); setVersion(''); setSelected(''); setStage('draft'); setApproval(false); setOperation('import'); setMessage(result.message)
      })}>Import as local draft</Button></details>
      <details><summary>Evaluate saved approved labels offline</summary><p>Uses the existing five-study evaluator. This saved approved version supplies reviewed labels. Optionally select other saved approved versions by NCT ID below; unselected studies remain unreviewed. Unreviewed slots and missing predictions have explicit coverage counts. No extraction is run.</p><label>Existing prediction artifact directory (optional)<input value={prediction} onChange={e => setPrediction(e.target.value)} placeholder="results/extraction/existing-version" /></label><label>Additional evaluation selections (JSON, optional)<textarea value={evaluationOptions} onChange={e => setEvaluationOptions(e.target.value)} placeholder={'{"references":{"NCT_ID":"saved-version-id"},"predictions":{"NCT_ID":"results/extraction/version"}}'} /></label><Button disabled={busy || !parent} onClick={() => run(async () => { const options = evaluationOptions.trim() ? JSON.parse(evaluationOptions) : {}; const result = await api<{ report: unknown; path: string }>(`/annotations/${nct}/versions/${parent}/evaluate`, { ...options, prediction_directory: prediction || null }); setEvaluation(JSON.stringify(result.report, null, 2)); setMessage(`Evaluation saved in ${result.path}. Unavailable metrics remain null.`) })}>Evaluate saved version</Button>{evaluation && <pre className="annotation-json" aria-label="Annotation evaluation report">{evaluation}</pre>}</details>
      </Panel></details></>}
  </fieldset></section>
}

