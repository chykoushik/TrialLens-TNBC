import { useState } from 'react'
import VisitorAnalysis from './VisitorAnalysis'
import { api } from './api'
import { Button } from './ui'
import type { Trial } from './types'

type Analysis = { extracted_conditions?: { criterion_id: string; original_text: string; criterion_type: string; biomarker?: string; comparator?: string; threshold?: string; unit?: string }[]; source_passages: { text: string; section: string; state: string }[]; saved_extractions: { mode: string; saved_status: string; source_structure_valid: boolean }[]; assessment_available: boolean; scope: string; inference: { explanation: string }; planning: { missing_inputs: string[] } }
export default function TrialSearch({ trials, research, demo, allowVisitor = true }: { allowVisitor?: boolean; trials: Trial[]; research: () => void; demo: () => void }) {
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('condition')
  const [status, setStatus] = useState('')
  const [matches, setMatches] = useState<Trial[] | null>(null)
  const [next, setNext] = useState<string | null>(null)
  const [selected, setSelected] = useState<Trial | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [origin, setOrigin] = useState('Saved ClinicalTrials.gov snapshots')
  async function search(token = '') {
    setBusy(true); setError(''); setSelected(null); setAnalysis(null)
    try {
      const params = new URLSearchParams({ [/^NCT\d{8}$/i.test(query.trim()) ? 'nct_id' : kind]: /^NCT\d{8}$/i.test(query.trim()) ? query.trim().toUpperCase() : query.trim(), status, page_token: token })
      const result = await api<{ trials: Trial[]; next_page_token: string | null; origin: string }>(`/clinical-trials/search?${params}`)
      setMatches(result.trials); setNext(result.next_page_token); setOrigin(result.origin)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  async function analyze() {
    if (!selected || busy) return
    setBusy(true); setError('')
    try { setAnalysis(await api<Analysis>(`/clinical-trials/${selected.nct_id}/analysis?${new URLSearchParams({ snapshot: selected.snapshot, snapshot_sha256: selected.snapshot_sha256 ?? '' })}`)) }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  function back() { setSelected(null); setAnalysis(null); setError('') }
  return <section className="trial-search">
    <p className="eyebrow">REAL REGISTRY SOURCES / RESEARCH PROTOTYPE</p>
    <h1>{analysis ? 'Trial analysis results' : selected ? 'Review your selected trial' : 'Understand a clinical trial.'}</h1>
    <p>{selected ? 'Original trial requirements stay separate from research demonstrations and patient assessments.' : 'Search ClinicalTrials.gov, choose a study and explore its requirements and available analysis.'}</p>
    {error && <p role="alert">{error}</p>}{busy && <p role="status">{selected ? 'Checking the saved source and available analysis…' : 'Searching ClinicalTrials.gov…'}</p>}
    {!selected ? <><form onSubmit={e => { e.preventDefault(); void search() }} className="search-form">
      <label>Search by<select value={kind} onChange={e => setKind(e.target.value)}><option value="condition">Condition or disease</option><option value="intervention">Treatment</option><option value="keywords">Keywords</option><option value="nct_id">NCT identifier</option></select></label>
      <label>{kind === 'nct_id' ? 'NCT identifier' : 'Search terms'}<input required value={query} onChange={e => setQuery(kind === 'nct_id' ? e.target.value.toUpperCase() : e.target.value)} placeholder={kind === 'nct_id' ? 'NCT04331067' : 'e.g. triple-negative breast cancer'} /></label>
      <label>Study status<select value={status} onChange={e => setStatus(e.target.value)}><option value="">Any status</option><option value="RECRUITING">Recruiting</option><option value="NOT_YET_RECRUITING">Not yet recruiting</option><option value="ACTIVE_NOT_RECRUITING">Active, not recruiting</option><option value="COMPLETED">Completed</option><option value="TERMINATED">Terminated</option></select></label>
      <Button variant="primary" type="submit" disabled={busy || !query.trim()}>Search trials</Button></form>
      <h2>{matches === null ? 'Or start with a saved study' : 'Search results'}</h2><p>{origin}. Registry status reflects the saved retrieval date.</p>
      {(matches ?? trials).length === 0 && <p>No matching studies. Change your search terms or filters.</p>}
      <div className="search-results">{(matches ?? trials).filter(trial => trial.is_synthetic !== true).map(trial => <article key={`${trial.nct_id}-${trial.snapshot}`}><p className="eyebrow">{trial.nct_id} · {trial.recruitment_status?.replaceAll('_', ' ')}</p><h3>{trial.title}</h3><p>{trial.conditions.join(', ')}</p>{'phases' in trial && <p>Phase: {(trial.phases as string[]).join(', ') || 'Not reported'}</p>}<p>Saved {trial.retrieved_at ? new Date(trial.retrieved_at).toLocaleDateString() : 'retrieval date unavailable'}</p><Button onClick={() => { setSelected(trial); setError('') }}>Select {trial.nct_id}</Button></article>)}</div>
      {next && <Button disabled={busy} onClick={() => void search(next)}>Next results</Button>}
    </> : <><Button onClick={back}>Back to Search</Button><article><p className="eyebrow">{selected.nct_id} · SAVED TRIAL RECORD</p><h2>{selected.title}</h2><p>{selected.recruitment_status?.replaceAll('_', ' ')} · {selected.conditions.join(', ')}</p><a href={selected.source_url ?? undefined} target="_blank" rel="noreferrer">Original ClinicalTrials.gov record</a>
      <details open={!analysis}><summary>Original eligibility requirements</summary><p className="source-text">{selected.eligibility_criteria || 'Eligibility text is not available for this study.'}</p></details>
      <details><summary>Source provenance</summary><p>Retrieved: {selected.retrieved_at ?? 'Unknown'}</p><p>New search snapshots can expire when this demonstration restarts. Search again if a saved source becomes unavailable.</p></details>
      {!analysis && <><p>Analyze checks available saved outputs and source requirements. It sends no new paid model request.</p><Button variant="primary" disabled={busy || !selected.eligibility_criteria} onClick={() => void analyze()}>Analyze trial</Button>{!selected.eligibility_criteria && <p>Choose another trial with available eligibility text.</p>}</>}
    </article>{analysis && <div className="analysis-sections"><article><h2>NVIDIA analysis</h2><p>{analysis.inference.explanation}</p>{analysis.saved_extractions.length ? <ul>{analysis.saved_extractions.map((item, index) => <li key={index}>{item.mode === 'live' ? 'Saved provider attempt' : 'Simulated extraction'}: {item.saved_status.replaceAll('_', ' ')}. Source and structure checks {item.source_structure_valid ? 'passed' : 'not passed'}.</li>)}</ul> : <p>No matching saved model extraction is available. The source-only review below is not NVIDIA inference.</p>}</article>
      {analysis.extracted_conditions && analysis.extracted_conditions.length > 0 && <article><h2>Source-supported extracted conditions</h2><p>Saved NVIDIA output that passed automatic source and structure checks. These conditions are not approved executable rules or clinically verified mappings.</p>{analysis.extracted_conditions.map(node => <section key={node.criterion_id}><h3>{node.criterion_type}</h3><blockquote>{node.original_text}</blockquote>{node.biomarker && <p>{node.biomarker} {node.comparator} {node.threshold} {node.unit}</p>}</section>)}</article>}
      {allowVisitor ? <VisitorAnalysis key={`${selected.nct_id}/${selected.snapshot}`} trial={selected} /> : <p>Public BYOK is currently disabled while deployment credential handling is verified. No API key is required to explore saved sources and research demonstrations.</p>}<article><h2>Eligibility reasoning</h2><p>Patient assessment is unavailable. There are no authorized patient records connected to this trial. Source passages alone are not executable eligibility rules.</p><details><summary>View source passages and unresolved conditions ({analysis.source_passages.length})</summary>{analysis.source_passages.map((passage, index) => <section key={index}><h3>{passage.section?.replaceAll('_', ' ') || 'Requirement'} · Unresolved</h3><p>{passage.text}</p></section>)}</details><p>{analysis.scope}</p></article>
      <article><h2>Adaptive evidence review</h2><p>A trial-specific plan requires approved mappings, authorized reports, review costs and a compatible probability model.</p><Button onClick={demo}>Explore the research planner</Button><p>The research demonstration uses synthetic scenarios, separate from this trial.</p></article>
      <article><h2>Scientific evaluation</h2><p>Explore the paper's inference and planning benchmarks, plus separate METABRIC and TCGA studies. These are general research findings, not results for this trial.</p><Button onClick={research}>View Research Results</Button></article>
      <details><summary>Methods and reproducibility</summary><p>Original registry text is preserved with its source checksum. Saved extraction checks assess source alignment and structure, not clinical correctness. Boolean reasoning and probabilistic planning require reviewed mappings and compatible evidence; incomplete inputs remain unresolved.</p></details><Button onClick={back}>Analyze another trial</Button>
    </div>}</>}
    <p className="simple-boundary">Research prototype. Not a clinical eligibility decision or treatment recommendation.</p>
  </section>
}
