import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import ProtocolSource from './ProtocolSource'
import TrialReader from './TrialReader'
import { Button } from './ui'
import type { Trial } from './types'

const storageKey = 'triallens.real-source-review.v1'
const titles = ['Choose a saved trial', 'Read the trial requirements', 'Inspect evidence and mappings', 'Understand unresolved conditions', 'Explore report prioritization', 'Review the sources and next steps']
type Selection = { nct: string; snapshot: string; hash: string; step: number }
type Review = {
  source: { nct_id: string; text: string; sha256: string; source_url: string; retrieval_timestamp: string | null }
  source_passages: { text: string; span: { start: number; end: number }; section: string | null; state: string; reason: string }[]
  reviewed_source_criteria: { original_text: string; polarity: string | null; executable: boolean }[]
  executable_mapping_count: number; assessment_available: boolean; complete_eligibility_available: boolean
  saved_extractions: { mode: string; saved_status: string; source_structure_valid: boolean }[]
  patient_evidence: unknown[]; planning: { available: boolean; selected_reports: string[]; missing_inputs: string[] }; scope: string
}
function savedSelection(): Selection | null {
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw || raw.length > 2000) return null
    const value = JSON.parse(raw)
    return /^NCT\d{8}$/.test(value.nct) && /^[a-zA-Z0-9_-]+\/response\.json$/.test(value.snapshot) && /^[a-f0-9]{64}$/.test(value.hash) && Number.isInteger(value.step) && value.step >= 0 && value.step < titles.length ? value : null
  } catch { return null }
}

export default function RealTrialReview({ trials, status, warnings, retry, home, demo }: { trials: Trial[]; status: 'loading' | 'ready' | 'error'; warnings: string[]; retry: () => void; home: () => void; demo: () => void }) {
  const [selection, setSelection] = useState<Selection | null>(savedSelection)
  const [data, setData] = useState<Review | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [storageNotice, setStorageNotice] = useState('')
  const heading = useRef<HTMLHeadingElement>(null)
  const realTrials = trials.filter(item => item.is_synthetic !== true && item.nct_id)
  const selected = realTrials.find(item => item.nct_id === selection?.nct && item.snapshot === selection.snapshot && item.snapshot_sha256 === selection.hash) ?? null
  const step = selected ? selection?.step ?? 0 : 0
  useEffect(() => { heading.current?.focus(); heading.current?.scrollIntoView?.({ block: 'start' }) }, [step])
  useEffect(() => {
    setData(null); setError('')
    if (!selected) return
    const controller = new AbortController()
    const query = new URLSearchParams({ snapshot: selected.snapshot, snapshot_sha256: selected.snapshot_sha256! })
    api<Review>(`/research/trials/${selected.nct_id}/review?${query}`, undefined, controller.signal).then(value => {
      if (controller.signal.aborted) return
      if (value.source?.nct_id !== selected.nct_id || value.source.sha256 !== selected.snapshot_sha256 || value.source.text !== selected.eligibility_criteria) throw new Error('Source identity changed')
      setData(value)
    }).catch(() => { if (!controller.signal.aborted) setError('The mapping review could not be loaded. The original trial text remains available. Retry or choose another trial.') })
    return () => controller.abort()
  }, [selected?.nct_id, selected?.snapshot, selected?.snapshot_sha256, attempt])
  useEffect(() => {
    try {
      if (selection) localStorage.setItem(storageKey, JSON.stringify(selection))
      else localStorage.removeItem(storageKey)
    } catch { setStorageNotice('Browser storage is unavailable. Keep this tab open to retain your source selection.') }
  }, [selection])
  function choose(trial: Trial | null) {
    setData(null)
    if (trial && !trial.snapshot_sha256) setStorageNotice('This saved record has incomplete provenance. Reload the library or choose another record.')
    setSelection(trial?.nct_id && trial.snapshot_sha256 ? { nct: trial.nct_id, snapshot: trial.snapshot, hash: trial.snapshot_sha256, step: 0 } : null)
  }
  function go(value: number) { if (selection) setSelection({ ...selection, step: value }) }
  const sourceText = data?.source.text ?? selected?.eligibility_criteria ?? ''
  return <div className="review-journey real-trial-review">
    <div className="real-review-actions"><Button variant="quiet" onClick={() => choose(null)}>Start again</Button><Button variant="quiet" onClick={demo}>Try a Demo</Button></div>
    <nav aria-label="Real trial review progress"><ol className="journey-progress">{titles.map((title, index) => <li key={title} aria-current={step === index ? 'step' : undefined}><span>{index + 1}</span>{title}</li>)}</ol></nav>
    <section className="journey-stage"><p className="eyebrow">Step {step + 1} of 6 / Saved ClinicalTrials.gov source</p><h2 ref={heading} tabIndex={-1}>{titles[step]}</h2>
      {storageNotice && <p role="status">{storageNotice}</p>}
      {selection && !selected && status === 'ready' && <p role="status">The saved source is no longer available with the same identity. Select a current saved record to continue; no different trial has been substituted.</p>}
      {step === 0 ? <><p>Search the saved registry records and choose a trial. You will read its original requirements, check available mappings, and see whether evidence supports further automated review.</p><TrialReader trials={realTrials} status={status} warnings={warnings} selected={selected} onSelect={choose} retry={retry} allowExtraction={false} />{status === 'ready' && !realTrials.length && <p>No real trial records are available in this workspace. Reload the saved library, or use the separately labeled demo. No fictional trial has been substituted.</p>}{status === 'ready' && !realTrials.length && <Button onClick={retry}>Reload saved trials</Button>}</> : <>
        <p className="case-source-label">{selected?.nct_id} / Real trial source</p><h3>{selected?.title}</h3>
        {step === 1 ? <><p>Read the original requirements, including inclusion and exclusion sections and cohort-specific exceptions. Source text is preserved; it has not been converted into a patient eligibility decision.</p><ProtocolSource text={sourceText} highlight={null} /><p>Saved: {selected?.retrieved_at ?? 'Retrieval date not recorded'}</p></> : error ? <div role="alert"><p>{error}</p><Button onClick={() => setAttempt(value => value + 1)}>Retry mapping review</Button></div> : !data ? <p role="status">Checking saved source and mapping artifacts...</p> : step === 2 ? <><p>No authorized patient records or report histories are attached to this trial. Aggregate METABRIC and TCGA findings remain research evaluations, not individual case evidence.</p><h3>Mapping checks</h3><p>{data.reviewed_source_criteria.length} source-reviewed criterion boundaries. {data.executable_mapping_count} approved executable mappings.</p>{data.reviewed_source_criteria.map((item, index) => <blockquote key={index}>{item.original_text}<p>Source-reviewed boundary only; not an executable clinical assessment.</p></blockquote>)}<p>Source validation checks quotations and structure. It does not verify clinical meaning or create the Boolean bindings, assay rules and temporal context needed for assessment.</p><details><summary>Saved extraction checks</summary>{data.saved_extractions.length ? <ul>{data.saved_extractions.map((item, index) => <li key={index}>{item.mode === 'live' ? 'Saved model output' : 'Offline mock output'}: {item.source_structure_valid ? 'Source and structural checks passed; execution still unavailable' : 'No validated extraction available'}.</li>)}</ul> : <p>No source-matching extraction output was found.</p>}<p>These are saved outputs. No new inference or extraction runs here.</p></details></> : step === 3 ? <><p>Automated assessment is unavailable for these source passages. Unmapped conditions remain unresolved; missing patient evidence is not treated as a negative result.</p><p>Passages below are automatically separated for reading. Their boundaries, section labels and complete logic still require review. Refer to the full source for context and exceptions.</p>{data.source_passages.length ? data.source_passages.map((item, index) => <article className="criterion" key={item.span.start}><strong>Unresolved / unavailable for automated assessment</strong><p>{item.text}</p><small>{item.reason}</small></article>) : <p>No passage boundaries were identified. The complete original text remains available in the previous step.</p>}</> : step === 4 ? <><h3>Report prioritization is not available for this record</h3><p>No review ranking, report outcome or budget decision has been generated. A source record alone does not provide the inputs required by the existing planner.</p><p>Further review requires:</p><ul>{data.planning.missing_inputs.map(item => <li key={item}>{item}</li>)}</ul><p>Continue to the source summary. To explore working adaptive planning with authored evidence, choose Try a Demo.</p></> : <><h3>Source review complete; eligibility remains unresolved</h3><p>You have inspected the saved trial requirements and the limits of the available evidence. No full eligibility decision or report plan has been produced.</p><p>Next, review the original registry source or start with another saved trial. Qualified mapping review and authorized, compatible evidence are required before automated assessment can proceed.</p><details><summary>Source provenance</summary><p>Retrieved: {selected?.retrieved_at ?? 'Not recorded'}</p><p>Snapshot: <code>{selected?.snapshot}</code></p><p>SHA-256: <code>{selected?.snapshot_sha256}</code></p></details><Button onClick={() => choose(null)}>Choose another trial</Button></>}
        {selected && selected.source_url === `https://clinicaltrials.gov/study/${selected.nct_id}` && <p><a href={selected.source_url} target="_blank" rel="noreferrer">Read original ClinicalTrials.gov source</a></p>}
      </>}
      <div className="demo-step-actions"><Button onClick={() => step ? go(step - 1) : home()}>Back</Button><Button variant="primary" disabled={!selected} onClick={() => step < 5 ? go(step + 1) : home()}>{step < 5 ? 'Continue' : 'Return home'}</Button></div>
    </section>
  </div>
}
