import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { Trial } from './types'
import ProtocolSource from './ProtocolSource'
import { allCandidates, candidateView, sameSource, schemaStatus, verifySourceSpan } from './extractionView'
import type { CandidateNode, ExtractionReport, SourceSelection, SourceSpan } from './extractionView'
import { Button, EmptyState, StatusIndicator } from './ui'

const clinicalSlots = ['cohort', 'logical_operator', 'biomarker', 'assay', 'comparator', 'threshold', 'unit', 'temporal_constraint']
const slotName = (name: string) => name.replaceAll('_', ' ')

function CriterionList({ nodes, selected, choose }: { nodes: CandidateNode[]; selected: string | null; choose: (node: CandidateNode) => void }) {
  return <ol className="extracted-criteria">{nodes.map(node => <li key={node.key}>
    <button className={`criterion-select ${selected === node.key ? 'is-selected' : ''}`} aria-label={`Inspect criterion ${node.id ?? node.key}`} aria-pressed={selected === node.key} onClick={() => choose(node)}>
      <span className="criterion-select-meta"><code>{node.id ?? 'ID unavailable'}</code><span>{typeof node.raw.criterion_type === 'string' ? node.raw.criterion_type : 'Polarity unresolved'}</span></span>
      <span className="criterion-excerpt">{node.text ?? 'Original criterion text is unavailable.'}</span>
      <small>Logic: {typeof node.raw.logical_operator === 'string' ? node.raw.logical_operator : 'unresolved'}</small>
    </button>
    {node.children.length > 0 && <div className="criterion-dependencies" aria-label={`Dependencies of ${node.id ?? node.key}`}><CriterionList nodes={node.children} selected={selected} choose={choose} /></div>}
  </li>)}</ol>
}

export default function TrialExtraction({ nctId, snapshot, study }: { nctId: string; snapshot: string; study?: Trial }) {
  const [selectedSnapshot, setSelectedSnapshot] = useState(snapshot)
  const [selection, setSelection] = useState<SourceSelection | null>(null)
  const [snapshots, setSnapshots] = useState<Pick<Trial, 'snapshot' | 'retrieved_at'>[]>([{ snapshot, retrieved_at: study?.retrieved_at ?? null }])
  const [report, setReport] = useState<ExtractionReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState<'mock' | 'live'>('mock')
  const [approved, setApproved] = useState(false)
  const [running, setRunning] = useState(false)
  const [sourceError, setSourceError] = useState('')
  const [requestError, setRequestError] = useState('')
  const [reload, setReload] = useState(0)
  const [activeCriterion, setActiveCriterion] = useState<string | null>(null)
  const [highlight, setHighlight] = useState<SourceSpan | null>(null)
  const [spanMessage, setSpanMessage] = useState('')
  const generation = useRef(0)
  const requestLock = useRef(false)

  function clearResult() {
    setReport(null); setActiveCriterion(null); setHighlight(null); setSpanMessage(''); setRequestError('')
  }

  useEffect(() => {
    const controller = new AbortController()
    const version = ++generation.current
    setSelection(null); clearResult(); setMode('mock'); setApproved(false); setSourceError(''); setLoading(true)
    api<SourceSelection>(`/saved-trials/${encodeURIComponent(nctId)}?snapshot=${encodeURIComponent(selectedSnapshot)}`, undefined, controller.signal)
      .then(result => {
        if (controller.signal.aborted || generation.current !== version) return
        if (result.source.nct_id !== nctId || !result.source.source_snapshot.endsWith(`/${selectedSnapshot}`)) {
          throw new Error('Source identity does not match the selected study and snapshot.')
        }
        setSelection(result)
        setSnapshots(previous => {
          const versions = new Map(previous.map(item => [item.snapshot, item]))
          for (const item of result.snapshots) versions.set(item.snapshot, item)
          return [...versions.values()]
        })
      })
      .catch(error => { if (!controller.signal.aborted) setSourceError(error.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => { controller.abort(); generation.current++ }
  }, [nctId, selectedSnapshot, reload])

  async function extract() {
    if (!selection || running || requestLock.current || !selection.source.text.trim()
        || (mode === 'live' && (!approved || !selection.configuration?.ready))) return
    const version = generation.current
    requestLock.current = true
    setRunning(true); clearResult()
    try {
      const result = await api<ExtractionReport>(`/saved-trials/${encodeURIComponent(nctId)}/extractions`, {
        snapshot: selectedSnapshot, snapshot_sha256: selection.source.sha256,
        mode, mock_version: selection.mock_version, ...(mode === 'live' ? { live_approved: approved } : {}),
      })
      if (generation.current === version) setReport(result)
    } catch (error) {
      if (generation.current === version) setRequestError(error instanceof Error ? error.message : 'Extraction request failed')
    } finally {
      requestLock.current = false
      if (generation.current === version) {
        setRunning(false)
        if (mode === 'live') {
          setApproved(false)
          setSelection(current => current ? { ...current, configuration: current.configuration ? { ...current.configuration, ready: false } : undefined } : current)
        }
      }
    }
  }

  const view = candidateView(report?.candidate ?? report?.validated)
  const candidates = allCandidates(view.criteria)
  const active = candidates.find(node => node.key === activeCriterion)
  const metadata = selection?.snapshots.find(item => item.snapshot === selectedSnapshot)
  const selectedStudy = metadata?.title !== undefined ? metadata : selectedSnapshot === snapshot ? study : undefined
  const validated = Boolean(report && selection && sameSource(report.source, selection.source)
    && report.manifest.status === 'validated' && report.validated !== null && report.validation_errors.length === 0)
  const schema = report ? schemaStatus(report) : 'Not run'

  function chooseCriterion(node: CandidateNode) {
    if (!report || !selection) return
    setActiveCriterion(node.key)
    const result = verifySourceSpan(node, report, selection.source)
    setHighlight(result.span); setSpanMessage(result.message)
  }

  return <section className="protocol-inspector" aria-label="Saved-trial extraction">
    <header className="protocol-header">
      <div className="protocol-identity"><p className="eyebrow">PROTOCOL INSPECTION / <span>{nctId}</span></p>
        <h2>{selectedStudy?.title ?? 'Saved-trial eligibility inspection'}</h2>
        <p className="protocol-conditions">{selectedStudy?.conditions?.join(' / ') || 'Conditions not recorded for this snapshot'}</p>
      </div>
      <span className="tag">{mode === 'mock' ? 'MOCK / SIMULATED' : 'LIVE NVIDIA NEMOTRON'}</span>
    </header>
      <div className="protocol-context">
        <label>Snapshot history<select disabled={running} aria-describedby="snapshot-control-status" value={selectedSnapshot} onChange={event => {
          if (event.target.value === selectedSnapshot) return
          setSelectedSnapshot(event.target.value); setSelection(null); setLoading(true); clearResult(); setApproved(false); setMode('mock')
        }}>{snapshots.map(item => <option key={item.snapshot} value={item.snapshot}>{item.retrieved_at ?? 'Retrieval time not recorded'} / {item.snapshot}</option>)}</select></label>
        {selection && <dl><div><dt>Registry status</dt><dd>{selectedStudy?.recruitment_status?.replaceAll('_', ' ') ?? 'Not recorded'}</dd></div>
          <div><dt>Retrieved</dt><dd>{selection.source.retrieval_timestamp ?? 'Not recorded'}</dd></div>
          <div><dt>Versions available</dt><dd>{selection.snapshots.length}</dd></div></dl>}
      </div>
    <p className="muted" id="snapshot-control-status">{running ? 'Snapshot and extraction mode are locked only while the current extraction request is running.' : 'Snapshot choices remain available during source loading and after failure. Changing snapshot clears results and resets extraction to mock.'}</p>
    {loading && <EmptyState title="Loading exact saved source…" description="Reading the selected snapshot and its provenance." />}
    {sourceError && <EmptyState error title="Saved source unavailable" description={sourceError} action={<Button onClick={() => setReload(value => value + 1)}>Reload source</Button>} />}
    {selection && <>
      <div className="protocol-source-link">
        <span>{selection.source.is_synthetic === true ? 'Explicitly synthetic source fixture' : 'Saved ClinicalTrials.gov source record; not a demonstration protocol'}</span>
        {selection.source.source_url === `https://clinicaltrials.gov/study/${nctId}` && <a href={selection.source.source_url} target="_blank" rel="noreferrer">Original ClinicalTrials.gov record</a>}
      </div>
      <p className="sr-only" role="status">Saved source loaded for {nctId}.</p>
      {selection.warnings.map(warning => <p className="inline-warning" key={warning}>{warning}</p>)}
      <div className="protocol-panels">
        <section className="source-pane" aria-label="Original eligibility source">
          <div className="inspection-pane-heading"><div><p className="eyebrow">01 / ORIGINAL SOURCE</p><h3>Eligibility text</h3></div><span className="tag">Verbatim</span></div>
          {selection.source.text.trim() ? <ProtocolSource text={selection.source.text} highlight={highlight} />
            : <EmptyState title="No eligibility text is available in this saved source." description="Extraction is disabled for empty source text." />}
          <div className="source-pane-foot"><span>Exact quote highlighting only</span>{highlight && <Button variant="quiet" onClick={() => { setHighlight(null); setActiveCriterion(null); setSpanMessage('') }}>Clear highlight</Button>}</div>
          <details className="source-provenance" open><summary>Source provenance</summary>
            <dl><div><dt>Snapshot</dt><dd>{selection.source.source_snapshot}</dd></div><div><dt>SHA-256</dt><dd><code>{selection.source.sha256}</code></dd></div></dl>
          </details>
        </section>
        <section className="extraction-pane" aria-label="Structured extraction inspection">
          <div className="inspection-pane-heading"><div><p className="eyebrow">02 / STRUCTURED INTERPRETATION</p><h3>Extraction & validation</h3></div></div>
          <div className="extraction-controls">
            <label>Extraction mode<select disabled={running} aria-describedby="snapshot-control-status" value={mode} onChange={event => {
              setMode(event.target.value as 'mock' | 'live'); setApproved(false); clearResult()
            }}><option value="mock">Mock extraction (default)</option><option value="live" disabled={!selection.configuration?.ready}>Live NVIDIA Nemotron (Nebius)</option></select></label>
            <div className="extraction-mode-note"><strong>{mode === 'mock' ? 'Simulated extraction' : 'Live NVIDIA Nemotron extraction'}</strong>
              <p>{mode === 'mock' ? 'Verbatim section replay, not verified NVIDIA or Nebius inference.' : 'One paid request through Nebius Token Factory. The saved public source text is sent to the provider.'}</p></div>
            {selection.configuration ? <details className="live-configuration"><summary>Live configuration: {selection.configuration.ready ? 'ready for approval' : 'unavailable or request budget consumed'}</summary><p>{selection.configuration.model}</p>{selection.configuration.errors.map(code => <p key={code}>{code}</p>)}</details>
              : <p className="muted">Live extraction is unavailable in the current server configuration.</p>}
            {mode === 'live' && <label className="live-approval"><input type="checkbox" checked={approved} disabled={running} onChange={event => setApproved(event.target.checked)} />Approve one paid live extraction of this snapshot</label>}
            <Button variant="primary" onClick={extract} disabled={running || !selection.source.text.trim() || (mode === 'live' && (!approved || !selection.configuration?.ready))}>
              {running ? 'Running extraction...' : mode === 'mock' ? 'Run mock extraction' : 'Run one live NVIDIA Nemotron extraction'}
            </Button>
          </div>
          {running && <EmptyState title="Extraction is running." description="Waiting for one extraction report. No automatic retries." />}
          {requestError && <EmptyState error title="Request failed" description={requestError} />}
          {!running && !requestError && !report && <EmptyState title="No extraction has been run for this snapshot." description="Run simulated mock extraction to inspect source spans and validation results. No eligibility assessment is performed." />}
          {report && <div className="extraction-result" aria-label="Extraction result">
            <dl className="extraction-status-grid">
              <div><dt>Backend request</dt><dd><StatusIndicator tone="success">Request succeeded</StatusIndicator></dd></div>
              <div><dt>Strict schema</dt><dd><StatusIndicator tone={schema === 'Passed' ? 'success' : schema === 'Failed' ? 'error' : 'neutral'}>{schema}</StatusIndicator></dd></div>
              <div><dt>Full validation</dt><dd><StatusIndicator tone={validated ? 'success' : 'warning'}>{validated ? 'Passed / review required' : 'Not validated'}</StatusIndicator></dd></div>
            </dl>
            <p className="result-status">Extraction status: <code>{report.manifest.status}</code></p>
            <p className="muted">Request success means the backend returned a report, not that extraction or validation succeeded.</p>
            {!sameSource(report.source, selection.source) && <p className="error" role="alert">The report source does not match this snapshot. Source highlighting is blocked.</p>}
            <div className="criterion-list-heading"><h4>Extracted criteria</h4><span>{view.criteria.length} top-level / {candidates.length - view.criteria.length} dependencies</span></div>
            {view.criteria.length ? <CriterionList nodes={view.criteria} selected={activeCriterion} choose={chooseCriterion} />
              : <EmptyState title="No structured criteria returned" description="Inspect the extraction errors and raw output below." />}
            {view.issues.map((issue, index) => <p className="inline-warning" key={index}>{issue}</p>)}
            {active && <section className="criterion-detail" aria-label="Selected extracted criterion"><h4>{active.id ?? 'Unlabeled criterion'}</h4>
              <p className={highlight ? 'span-verification' : 'span-unavailable'} role="status">{spanMessage}</p>
              <p className="selected-original">{active.text ?? 'Original text unavailable.'}</p>
              <dl>{clinicalSlots.map(slot => <div key={slot}><dt>{slotName(slot)}</dt><dd>{typeof active.raw[slot] === 'string' ? active.raw[slot] as string : active.raw[slot] === null ? 'Unresolved / not provided' : 'Unavailable or invalid'}</dd></div>)}</dl>
            </section>}
            <details className="validation-details" open={report.validation_errors.length > 0}><summary>Extraction and validation errors ({report.validation_errors.length})</summary>
              {report.validation_errors.length ? <ul>{report.validation_errors.map((item, index) => <li key={index}><code>{item.code}</code><span>{item.criterion_id ?? 'Source'}{item.field && ` / ${item.field}`}</span></li>)}</ul>
                : <p>No structural or source-span validation errors. Human semantic review is still required.</p>}
            </details>
            <details className="unsupported-details" open={report.unsupported_criteria.length > 0}><summary>Unsupported / unreviewed criteria ({report.unsupported_criteria.length})</summary>
              {report.unsupported_criteria.length ? <ul>{report.unsupported_criteria.map((item, index) => <li key={index}><code>{item.criterion_id ?? 'Source'}</code><span>{item.reason}</span></li>)}</ul>
                : <p>No unsupported criteria reported. Human review is still required.</p>}
            </details>
            <details className="structured-output"><summary>Validated structured output</summary>
              {report.validated === null ? <p>No validated criteria set. The validator was not relaxed or repaired.</p> : <pre>{JSON.stringify(report.validated, null, 2)}</pre>}
            </details>
            <details className="raw-output"><summary>{report.manifest.mode === 'mock' ? 'Unvalidated mock candidates and source spans' : 'Unvalidated live candidates and source spans'}</summary><pre>{JSON.stringify(report.candidate, null, 2)}</pre></details>
            <details className="extraction-provenance" open={Boolean(report.manifest.usage)}><summary>Extraction provenance & usage</summary>
              <dl><div><dt>Mode</dt><dd>{report.manifest.mode === 'mock' ? 'Mock / simulated' : report.manifest.mode}</dd></div>
                <div><dt>Prompt</dt><dd>{report.manifest.prompt_version}</dd></div><div><dt>Requested model</dt><dd>{report.manifest.requested_model ?? 'Not recorded'}</dd></div><div><dt>Returned model</dt><dd>{report.manifest.returned_model ?? 'Not recorded'}</dd></div><div><dt>Saved artifacts</dt><dd>{report.output_directory}</dd></div></dl>
              {report.manifest.usage && <p>Token usage: input {report.manifest.usage.prompt_tokens ?? 'unknown'} / output {report.manifest.usage.completion_tokens ?? 'unknown'} / total {report.manifest.usage.total_tokens ?? 'unknown'}</p>}
              {report.manifest.estimated_cost_usd != null && <p>Estimated cost: ${report.manifest.estimated_cost_usd.toFixed(6)} USD</p>}
            </details>
          </div>}
          <div className="assessment-boundary"><strong>Assessment blocked</strong><p>{report?.assessment_block_reason ?? 'Real trial criteria remain separate from fictional patient demonstrations. Source highlighting is not semantic validation or permission to assess a patient.'}</p></div>
        </section>
      </div>
    </>}
  </section>
}
