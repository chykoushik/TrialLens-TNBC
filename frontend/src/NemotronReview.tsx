import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { allCandidates, candidateView, verifySourceSpan } from './extractionView'
import type { ExtractionReport } from './extractionView'
import ProtocolSource from './ProtocolSource'
import type { Trial } from './types'
import { Button } from './ui'

type Status = { snapshot_sha256: string; configuration: { ready: boolean; missing_variables: string[]; request_available: boolean; maximum_estimated_cost_usd: number | null; maximum_estimated_cost_usd_exact?: string | null; cost_controls_ready: boolean; operator_configured: boolean; live_enabled?: boolean; original_request_available?: boolean; authorization_id?: string | null; authorized_maximum_estimated_cost_usd?: string | null; remaining_authorized_requests?: number }; attempts: { id: string; mode: string; status: string; timestamp: string }[] }
type Report = ExtractionReport & { attempt_sha256: string; review_checks_passed: boolean; mapping_reviews: Record<string, { decision: string }>; partial_recovery?: { complete_top_level_objects: number; exact_source_top_level_objects: number; scope: string; objects: { candidate: { criterion_id?: string; original_text?: string }; source_checks: { exact_match_count: number }[] }[] } }

export default function NemotronReview({ trial, operatorToken = '' }: { trial: Trial; operatorToken?: string }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [attempt, setAttempt] = useState('')
  const [selected, setSelected] = useState('')
  const [token, setToken] = useState(operatorToken)
  const [approved, setApproved] = useState(false)
  const [semanticReview, setSemanticReview] = useState(false)
  const [reviewer, setReviewer] = useState('')
  const [note, setNote] = useState('')
  const [attribute, setAttribute] = useState('')
  const [valueType, setValueType] = useState('numeric')
  const [categories, setCategories] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [reload, setReload] = useState(0)
  const [authorizationUncertain, setAuthorizationUncertain] = useState(false)
  const lock = useRef(false)
  const generation = useRef(0)
  useEffect(() => {
    const version = ++generation.current
    const controller = new AbortController()
    setStatus(null); setError('')
    api<Status>(`/saved-trials/${trial.nct_id}/inference?snapshot=${encodeURIComponent(trial.snapshot)}`, undefined, controller.signal, { Authorization: `Bearer ${token}` }).then(result => {
      if (controller.signal.aborted || generation.current !== version) return
      if (!result.configuration || result.snapshot_sha256 !== trial.snapshot_sha256 || !Array.isArray(result.attempts)) throw new Error('Source identity unavailable')
      setApproved(false); setAuthorizationUncertain(false); setStatus(result)
    }).catch(() => { if (!controller.signal.aborted) setError('Extraction status could not be loaded. You can still read the original source and continue the review.') })
    return () => { controller.abort(); generation.current++ }
  }, [trial.nct_id, trial.snapshot, trial.snapshot_sha256, reload])
  const candidates = allCandidates(candidateView(report?.candidate ?? report?.validated).criteria)
  const current = candidates.find(item => item.key === selected)
  const passage = current && report?.source ? verifySourceSpan(current, report, report.source) : null
  const headers = { Authorization: `Bearer ${token}` }
  async function inspect(id: string) {
    const version = generation.current
    setBusy(true); setReport(null); setSelected(''); setSemanticReview(false); setError(''); setMessage('')
    try {
      const result = await api<Report>(`/saved-trials/${trial.nct_id}/inference/${encodeURIComponent(id)}`, undefined, undefined, headers)
      if (generation.current !== version) return
      if (!result.source || result.source.sha256 !== trial.snapshot_sha256 || result.source.nct_id !== trial.nct_id) throw new Error('Source mismatch')
      setReport(result)
    } catch { if (generation.current === version) setError('Saved extraction could not be opened safely. Select another saved attempt or reload the source.') }
    finally { if (generation.current === version) setBusy(false) }
  }
  async function extract() {
    if (!status?.configuration.ready || !approved || !token || lock.current) return
    lock.current = true; setAuthorizationUncertain(true); setBusy(true); setError(''); setMessage('')
    try {
      const result = await api<ExtractionReport>(`/saved-trials/${trial.nct_id}/extractions`, { snapshot: trial.snapshot, snapshot_sha256: trial.snapshot_sha256, mode: 'live', live_approved: true, ...(status.configuration.authorization_id ? { authorization_id: status.configuration.authorization_id, maximum_estimated_cost_usd: status.configuration.authorized_maximum_estimated_cost_usd } : {}) }, undefined, headers)
      const id = result.output_directory.split('/').at(-1)!
      setAttempt(id); setApproved(false)
      await inspect(id)
      setMessage(result.manifest.mode === 'live' && result.manifest.status === 'validated' ? 'Response saved and source checks passed. Review the extracted conditions; no mapping has been approved automatically.' : 'The request did not produce an approved extraction. Inspect the saved outcome; it has not been converted into eligibility rules.')
    } catch { setError('The request was blocked or did not complete. No automatic retry will occur. Reload status before any further action; a timeout may still consume a provider request.') }
    finally { lock.current = false; setBusy(false); setApproved(false); setStatus(previous => previous ? { ...previous, configuration: { ...previous.configuration, ready: false } } : previous) }
  }
  async function review(decision: 'approve' | 'reject') {
    if (!current?.id || !report || !token || !reviewer.trim() || !note.trim() || lock.current) return
    lock.current = true; setBusy(true); setError(''); setMessage('')
    try {
      const compound = current.children.length > 0
      const result = await api<{ message: string }>(`/saved-trials/${trial.nct_id}/inference/${encodeURIComponent(attempt)}/reviews`, {
        snapshot_sha256: trial.snapshot_sha256, attempt_sha256: report.attempt_sha256, criterion_id: current.id, decision,
        reviewer, note, semantics_reviewed: semanticReview,
        clinical_attribute: compound || decision === 'reject' ? null : attribute.trim() || null,
        value_type: compound || decision === 'reject' ? null : valueType,
        categories: !compound && decision === 'approve' && valueType === 'categorical' ? categories.split(',').map(value => value.trim()).filter(Boolean) : null,
      }, undefined, headers)
      setMessage(result.message)
      setReport(previous => previous ? { ...previous, mapping_reviews: { ...previous.mapping_reviews, [current.id!]: { decision } } } : previous)
      setSemanticReview(false)
    } catch { setError('This mapping review was not accepted. Check operator access, source validity, semantic review and the supported mapping fields. Unsupported or changed mappings cannot be approved.') }
    finally { lock.current = false; setBusy(false) }
  }
  return <section className="nemotron-review" aria-labelledby="nemotron-title"><h3 id="nemotron-title">NVIDIA criteria extraction</h3>
    <p>Nemotron can propose structured conditions from this saved source through Nebius. A model proposal is not a clinical verification or an eligibility decision.</p>
    {!status ? <p role="status">{error || 'Checking extraction availability...'}</p> : <><p>{status.configuration.ready ? 'Live extraction is configured. An authorized operator must explicitly approve one paid request.' : 'Live extraction is unavailable. Existing saved outputs can still be inspected.'}</p>
      <p>Remaining authorized requests for this source: <strong>{authorizationUncertain ? 'Reload status to verify' : status.configuration.remaining_authorized_requests ?? (status.configuration.request_available ? 1 : 0)}</strong>.</p><details><summary>Operator access and live request controls</summary><p>The provider API key stays on the server. Enter an operator access code only; it is kept in memory for this view and is not saved in browser storage.</p><label>Operator access code<input type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} /></label><Button variant="quiet" onClick={() => setToken('')}>Clear access code</Button>
        <p>Maximum estimated request cost: {status.configuration.maximum_estimated_cost_usd === null ? 'Not configured' : `$${status.configuration.maximum_estimated_cost_usd_exact ?? status.configuration.maximum_estimated_cost_usd.toFixed(7)}`}. This uses configured rates and bounded input/output; it is not a billing receipt.</p>
        {!status.configuration.request_available && <p>No unused authorization matches this trial, checksum, model and cost scope. The original request reservation remains consumed and has not been reset.</p>}
        {status.configuration.live_enabled === false && <p>Live requests are disabled in the backend. Enabling live mode does not itself authorize or send a request.</p>}
        {status.configuration.authorization_id && <p>One-use request identifier: <code>{status.configuration.authorization_id}</code>. Authorized estimated cost ceiling: ${status.configuration.authorized_maximum_estimated_cost_usd}.</p>}
        {status.configuration.missing_variables.length > 0 && <details><summary>Missing server configuration</summary><p>{status.configuration.missing_variables.join(', ')}</p></details>}
        <label><input type="checkbox" checked={approved} disabled={!status.configuration.ready || busy} onChange={event => setApproved(event.target.checked)} />I authorize one paid Nebius request for this exact saved public trial source. No patient data will be sent.</label>
        <Button disabled={!status.configuration.ready || !approved || !token || busy} onClick={extract}>{busy ? 'Working...' : 'Request NVIDIA extraction'}</Button>
      </details>
      <label>Saved extraction<select value={attempt} disabled={busy} onChange={event => { setAttempt(event.target.value); if (event.target.value) void inspect(event.target.value); else setReport(null) }}><option value="">Choose a saved attempt</option>{status.attempts.map(item => <option key={item.id} value={item.id}>{item.timestamp} / {item.mode === 'live' ? 'Saved provider attempt' : 'Offline mock'} / {item.status}</option>)}</select></label>
    </>}
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}<Button variant="quiet" disabled={busy} onClick={() => setReload(value => value + 1)}>Reload extraction status</Button>
    {report && <><p><strong>{report.manifest.mode === 'live' ? 'Saved live-request attempt' : 'Offline mock output'}</strong>. {report.review_checks_passed ? 'Source and structural checks passed. No independent clinical verification follows.' : 'Validation failed or the request did not return usable criteria. Approval is blocked.'}</p>
      {report.partial_recovery && <section aria-label="Incomplete response recovery"><h4>Partial recovery · review only</h4><p>The response reached its output limit. {report.partial_recovery.complete_top_level_objects} complete top-level objects were recovered; {report.partial_recovery.exact_source_top_level_objects} contain exact source quotations. Evidence annotations and the complete extraction are unavailable. Mapping approval and assessment remain blocked.</p><details><summary>Inspect intact recovered objects</summary><p>{report.partial_recovery.scope}</p>{report.partial_recovery.objects.map((item, index) => <article key={index}><h5>{typeof item.candidate.criterion_id === 'string' ? item.candidate.criterion_id : `Object ${index + 1}`}</h5><blockquote>{typeof item.candidate.original_text === 'string' ? item.candidate.original_text : 'No original text supplied'}</blockquote><p>{item.source_checks[0]?.exact_match_count ? 'Exact source text found; clinical meaning and attributes remain unverified.' : 'Original text does not match an exact source passage. Do not use as grounded evidence.'}</p></article>)}</details></section>}
      {candidates.length ? <><label>Extracted condition<select value={selected} onChange={event => { setSelected(event.target.value); setSemanticReview(false); setAttribute(''); setCategories(''); setNote('') }}><option value="">Choose a condition</option>{candidates.map((item, index) => <option value={item.key} key={item.key}>Condition {index + 1}: {item.text?.slice(0, 100) ?? 'Unavailable text'}</option>)}</select></label>{current && <article><blockquote>{current.text}</blockquote><p>Inclusion/exclusion: {String(current.raw.criterion_type ?? 'Unresolved')}. Logic: {String(current.raw.logical_operator ?? 'Unresolved')}.</p><dl>{['biomarker', 'assay', 'comparator', 'threshold', 'unit', 'temporal_constraint', 'cohort'].map(field => <div key={field}><dt>{field.replaceAll('_', ' ')}</dt><dd>{String(current.raw[field] ?? 'Not supplied')}</dd></div>)}</dl><p>Current review: {report.mapping_reviews?.[current.id ?? '']?.decision ?? 'Unreviewed'}.</p>
        <details open><summary>Original source passage and context</summary><p>{passage?.message}</p><ProtocolSource text={report.source?.text ?? ''} highlight={passage?.span ?? null} /></details>
        <fieldset disabled={busy}><legend>Operator mapping review</legend><p>Approve only after checking meaning, inclusion/exclusion, negation, dependencies, exceptions, scope, assay and timing against the full source. Temporal mappings are not supported by this form and need separate rule review. Do not enter patient information.</p><label>Reviewer or pseudonym<input value={reviewer} maxLength={100} onChange={event => setReviewer(event.target.value)} /></label><label>Review note<textarea value={note} maxLength={2000} onChange={event => setNote(event.target.value)} /></label>{current.children.length === 0 && <><label>Mapped clinical attribute<input value={attribute} maxLength={150} onChange={event => setAttribute(event.target.value)} /></label><label>Value type<select value={valueType} onChange={event => setValueType(event.target.value)}><option value="numeric">Numeric</option><option value="categorical">Categorical</option></select></label>{valueType === 'categorical' && <label>Allowed categories, separated by commas<input value={categories} onChange={event => setCategories(event.target.value)} /></label>}</>}
          <label><input type="checkbox" checked={semanticReview} onChange={event => setSemanticReview(event.target.checked)} />I checked the complete source meaning and this supported research mapping.</label>
          <Button disabled={!report.review_checks_passed || !semanticReview || !token || !reviewer.trim() || !note.trim()} onClick={() => review('approve')}>Approve supported mapping</Button><Button disabled={!token || !reviewer.trim() || !note.trim()} onClick={() => review('reject')}>Reject mapping</Button>
        </fieldset><p>Approved research mappings do not authorize patient use. No authorized real-patient evidence adapter is configured; complete assessment and planning remain unavailable.</p></article>}</> : <p>No usable conditions were returned. Continue with the original source or select a different saved attempt.</p>}
    </>}
  </section>
}
