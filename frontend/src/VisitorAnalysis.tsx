import { useEffect, useRef, useState } from 'react'
import { api, apiUrl } from './api'
import type { Trial } from './types'
import { Button } from './ui'

type Quote = { analysis_id: string; model: string; request_count: number; maximum_cost_usd: string; max_output_tokens_per_request: number; expires_in_seconds: number }
type Result = { status: string; human_review_required: boolean; sections: { section: number; status: string; error?: string; criteria: { criterion_id: string; original_text: string; criterion_type: string }[] }[] }

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
  useEffect(() => {
    const disconnect = () => { controller.current?.abort(); setKey(''); setQuote(null); setConfirmed(false) }
    window.addEventListener('pagehide', disconnect)
    return () => { window.removeEventListener('pagehide', disconnect); controller.current?.abort() }
  }, [])
  async function prepare() {
    if (running.current) return
    running.current = true; setOpen(true); setBusy(true); setProgress('Preparing source sections and the aggregate cost estimate. No provider request is sent.'); setError(''); setConfirmed(false); setQuote(null)
    const abort = new AbortController(); controller.current = abort
    try {
      const value = await api<Quote>('/visitor-analysis/prepare', { nct_id: trial.nct_id, snapshot: trial.snapshot, snapshot_sha256: trial.snapshot_sha256 }, abort.signal)
      if (!abort.signal.aborted) setQuote(value)
    } catch { if (!abort.signal.aborted) setError('Visitor analysis is unavailable. Verified pricing and secure deployment must be configured by the operator.') }
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
    const credential = key.trim(); setKey('')
    const approval = quote; setQuote(null); setConfirmed(false)
    setProgress(`Analyzing up to ${approval.request_count} source sections and validating each response. This may take several minutes. No automatic retries.`)
    try {
      const response = await fetch(url, { method: 'POST', signal: abort.signal, cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysis_id: approval.analysis_id, api_key: credential, confirmed: true, maximum_cost_usd: approval.maximum_cost_usd }) })
      if (!response.ok) throw new Error('request_failed')
      const value = await response.json() as Result
      if (!abort.signal.aborted) setResult(value)
    } catch { if (!abort.signal.aborted) setError('Analysis could not finish. Check your key, credits or provider availability. Processing and billing may have occurred. No automatic retry was made.') }
    finally { setKey(''); running.current = false; setBusy(false) }
  }
  return <section aria-label="Visitor NVIDIA analysis">
    <Button disabled={busy} onClick={() => void prepare()}>Analyze with NVIDIA</Button>
    {open && <div><h3>Use your own Nebius API key</h3>
      <p>Your key is sent to the TrialLens server and then to Nebius Token Factory for this analysis. It stays in runtime memory, is not saved, and is cleared after use or when you leave this page. Do not submit real patient records. Nebius processes the public trial text under its own policies.</p>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">{progress}</p>}
      {quote && <><p>Model: {quote.model}. Planned provider requests: {quote.request_count}. Estimated aggregate maximum: ${quote.maximum_cost_usd}. Output limit: {quote.max_output_tokens_per_request} tokens per request. Approval expires in {quote.expires_in_seconds / 60} minutes.</p>
        <label>Connect Nebius API Key<input type="password" autoComplete="off" spellCheck={false} value={key} onChange={event => setKey(event.target.value)} /></label>
        <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I approve these requests and the displayed aggregate cost ceiling for this trial.</label>
        <Button disabled={busy || !confirmed || !key.trim()} onClick={() => void run()}>Approve cost and analyze</Button></>}
      <Button onClick={() => { controller.current?.abort(); setKey(''); setQuote(null); setConfirmed(false); setOpen(false) }}>Disconnect key</Button>
      {result && <article><h3>NVIDIA extraction: {result.status}</h3><p>Automatic source and structure checks only. Clinical review is required; these are not executable mappings or patient eligibility findings.</p>
        {result.sections.map(section => <section key={section.section}><h4>Section {section.section}: {section.status.replaceAll('_', ' ')}</h4>{section.error && <p>{section.error.replaceAll('_', ' ')}. Processing and billing may have occurred; no retry was made.</p>}{section.criteria.map(node => <blockquote key={node.criterion_id}>{node.original_text}</blockquote>)}</section>)}
      </article>}
    </div>}
  </section>
}
