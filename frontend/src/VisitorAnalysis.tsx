import { useEffect, useRef, useState } from 'react'
import { api, apiUrl, ApiError } from './api'
import type { Trial } from './types'
import { Button } from './ui'

type Quote = { analysis_id: string; model: string; request_count: number; maximum_cost_usd: string; max_output_tokens_per_request: number; expires_in_seconds: number; max_input_tokens?: number[] }
type Criterion = { criterion_id: string; original_text: string; criterion_type: string; dependencies?: Criterion[] | null; logical_operator?: string | null; [field: string]: unknown }

function Condition({ node }: { node: Criterion }) {
  const fields = Object.entries(node).filter(([field]) => !['criterion_id', 'original_text', 'dependencies'].includes(field))
  return <section><blockquote>{node.original_text}</blockquote><dl>{fields.map(([field, value]) => <div key={field}><dt>{field.replaceAll('_', ' ')}</dt><dd>{value == null ? 'Unresolved / not extracted' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>{!node.logical_operator && <p>Logical relationship unresolved: human review required.</p>}{node.dependencies?.map(child => <Condition key={child.criterion_id} node={child} />)}</section>
}

type Diagnostic = { code: string; message: string; field?: string; category?: string }

type SourcePassage = { source_id: string; start: number; end: number; text: string; interpretation_status: string; unresolved_reason: string | null }

type Result = { source_inventory_complete?: boolean; interpretation_complete?: boolean; source_passages?: SourcePassage[]; unresolved_count?: number; merge_diagnostics?: Diagnostic[]; full_source_coverage_validated?: boolean; status: string; human_review_required: boolean; sections: { section: number; status: string; error?: string; diagnostics?: Diagnostic[]; criteria: Criterion[] }[] }

function preparationError(error: unknown) {
  const reasons: Record<number, string> = {
    400: 'Analysis preparation requires a secure HTTPS connection.',
    403: 'Analysis preparation was blocked by the same-origin security check.',
    404: 'The preparation endpoint was not found. The frontend and backend deployment may not match.',
    409: 'The saved source is unavailable or changed. Search again and reselect the trial.',
    422: 'This trial could not be prepared safely. Check the selected source or choose another trial.',
    429: 'Too many preparation requests. Wait ten minutes before preparing again.',
    503: 'Visitor analysis is disabled or a required server prerequisite is unavailable.',
  }
  const safeDetails = new Set([
    'Visitor extraction is disabled pending deployment security review.',
    'Visitor credentials require HTTPS.', 'Untrusted request origin.',
    'Operator must configure verified provider pricing before visitor extraction.',
    'Visitor cost ceiling is not configured safely.', 'This analysis exceeds the server cost ceiling.',
    'Visitor preparation limit reached. Please wait ten minutes.',
    'Choose an unchanged real registry snapshot.',
    'Criteria require source review before section extraction.',
    'Long cohort-scoped criteria require source review before splitting.',
    'A dependent criterion is too long for safe automatic splitting. Source review required.',
    'Section exceeds safe input limit.',
    'Source exceeds the visitor request limit; source review required.',
    'Source sections do not provide complete coverage.',
  ])
  if (error instanceof ApiError) {
    const reason = safeDetails.has(error.message) ? error.message : reasons[error.status] ?? 'The analysis service could not prepare this request. Try preparing again or contact the site operator.'
    return `Preparation failed (HTTP ${error.status}): ${reason} No provider request was sent.`
  }
  return 'Could not reach the analysis service. Check your connection and try preparing again. No provider request was sent.'
}

export default function VisitorAnalysis({ trial }: { trial: Trial }) {
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [quote, setQuote] = useState<Quote | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const controller = useRef<AbortController | null>(null)
  const running = useRef(false)
  const analysisId = useRef<string | null>(null)
  const keyTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  function removeKey() {
    controller.current?.abort(); setKey(''); setQuote(null); setConfirmed(false)
    if (keyTimer.current) clearTimeout(keyTimer.current)
    if (analysisId.current) {
      void fetch(apiUrl('/visitor-analysis/remove'), { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ analysis_id: analysisId.current }) }).catch(() => {})
      analysisId.current = null
    }
  }
  useEffect(() => {
    const disconnect = () => removeKey()
    window.addEventListener('pagehide', disconnect)
    return () => { window.removeEventListener('pagehide', disconnect); removeKey() }
  }, [])
  async function prepare() {
    if (running.current) return
    running.current = true; setOpen(true); setBusy(true); setProgress('Preparing source sections and the aggregate cost estimate. No provider request is sent.'); setError(''); setConfirmed(false); setQuote(null)
    const abort = new AbortController(); controller.current = abort
    try {
      const value = await api<Quote>('/visitor-analysis/prepare', { nct_id: trial.nct_id, snapshot: trial.snapshot, snapshot_sha256: trial.snapshot_sha256 }, abort.signal)
      if (!abort.signal.aborted) { analysisId.current = value.analysis_id; setQuote(value) }
    } catch (error) { if (!abort.signal.aborted) setError(preparationError(error)) }
    finally { running.current = false; setBusy(false) }
  }
  async function run() {
    if (running.current || !quote || !confirmed || !key.trim()) return
    const url = new URL(apiUrl('/visitor-analysis/run'), window.location.href)
    if (url.origin !== window.location.origin || (url.protocol !== 'https:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) {
      setError('Visitor credentials require the trusted same-origin HTTPS backend.'); return
    }
    running.current = true; setBusy(true); setError(''); setResult(null)
    const abort = new AbortController(); controller.current = abort
    let credential = key.trim(); setKey('')
    const approval = quote; setQuote(null); setConfirmed(false)
    setProgress(`Analyzing up to ${approval.request_count} source sections and validating each response. This may take several minutes. No automatic retries.`)
    keyTimer.current = setTimeout(() => { removeKey(); setError('Temporary key expired. Provider processing and billing may have occurred.') }, 300000)
    try {
      const pending = fetch(url, { method: 'POST', signal: abort.signal, cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysis_id: approval.analysis_id, api_key: credential, confirmed: true, maximum_cost_usd: approval.maximum_cost_usd }) })
      credential = ''
      const response = await pending
      if (!response.ok) throw new Error('request_failed')
      const value = await response.json() as Result
      if (!abort.signal.aborted) setResult(value)
    } catch { if (!abort.signal.aborted) setError('Analysis could not finish. Check your key, credits or provider availability. Processing and billing may have occurred. No automatic retry was made.') }
    finally { credential = ''; if (keyTimer.current) clearTimeout(keyTimer.current); setKey(''); running.current = false; setBusy(false) }
  }
  return <section aria-label="Visitor NVIDIA analysis">
    <Button disabled={busy} onClick={() => void prepare()}>Run NVIDIA Analysis</Button>
    {open && <div><h3>Use your own Nebius API key</h3>
      <p>Your API key is used temporarily for NVIDIA analysis and is automatically removed from this website after five minutes. It is not saved. Your Nebius Token Factory account may be charged for inference. For additional security, revoke the API key in your Token Factory dashboard after testing.</p><p>Your key is sent to the TrialLens server and then to Nebius Token Factory for this analysis. It stays in runtime memory, is not saved, and is cleared after use or when you leave this page. Do not submit real patient records. Nebius processes the public trial text under its own policies.</p>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">{progress}</p>}
      {quote && <><p>Model: {quote.model}. Planned provider requests: {quote.request_count}. Estimated aggregate maximum: ${quote.maximum_cost_usd}. Input token limits per request: {quote.max_input_tokens?.join(', ')}. Output limit: {quote.max_output_tokens_per_request} tokens per request. Approval expires in {quote.expires_in_seconds / 60} minutes.</p>
        <label>Connect Nebius API Key<input type="password" autoComplete="off" spellCheck={false} value={key} onChange={event => setKey(event.target.value)} /></label>
        <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I approve these requests and the displayed aggregate cost ceiling for this trial.</label>
        <Button disabled={busy || !confirmed || !key.trim()} onClick={() => void run()}>Approve cost and analyze</Button></>}
      <Button onClick={() => { removeKey(); setOpen(false) }}>Remove Key Now</Button>
      {result && <article><h3>NVIDIA extraction: {result.status.replaceAll('_', ' ')}</h3>{result.source_passages && <><p>Original source inventory: {result.source_inventory_complete ? 'complete' : 'incomplete'}. Clinical interpretation: {result.interpretation_complete ? 'source-checked; human review still required' : 'incomplete or unresolved'}.</p><details><summary>Original passages and interpretation coverage ({result.source_passages.length})</summary>{result.source_passages.map(passage => <section key={passage.source_id}><p>Source characters {passage.start}-{passage.end}: {passage.interpretation_status.replaceAll('_', ' ')}</p><blockquote className="source-text">{passage.text}</blockquote>{passage.unresolved_reason && <p>Requires review: {passage.unresolved_reason.replaceAll('_', ' ')}.</p>}</section>)}</details></>}<p>Full source coverage: {result.full_source_coverage_validated ? 'validated' : 'incomplete or unverified'}.</p><p>Automatic source and structure checks only. Clinical review is required; these are not executable mappings or patient eligibility findings.</p>
        {result.merge_diagnostics?.map(item => <p role="alert" key={`${item.code}/${item.field ?? ''}/${item.category ?? ''}`}>Combined source validation: {item.message}{item.field && <> Field: {item.field}.</>}{item.category && <> Reason: {item.category.replaceAll('_', ' ')}.</>}</p>)}
        {result.sections.map(section => <section key={section.section}><h4>Section {section.section}: {section.status.replaceAll('_', ' ')}</h4>{section.error && <p>{section.error.replaceAll('_', ' ')}. Processing and billing may have occurred; no retry was made.</p>}{section.diagnostics?.map(item => <p key={`${item.code}/${item.field ?? ''}/${item.category ?? ''}`}>{item.message}{item.field && <> Field: {item.field}.</>}{item.category && <> Reason: {item.category.replaceAll('_', ' ')}.</>}</p>)}{section.error === 'source_validation_failed' && !section.diagnostics?.length && <p role="alert">The server did not provide validation details. The backend version cannot be confirmed from this response. No retry was made.</p>}{section.criteria.map(node => <div key={node.criterion_id}><Condition node={node} /><p>Coverage: source validated. Unresolved conditions require human review.</p></div>)}</section>)}
      </article>}
    </div>}
  </section>
}
