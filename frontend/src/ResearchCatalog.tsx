import { useEffect, useState } from 'react'
import { api } from './api'
import { Button } from './ui'

type Catalog = { manuscript: string; title: string; artifacts: { id: string; title: string; study: string; available: boolean }[]; implementation: { method: string; code: string; capability: string }[] }
type Artifact = { title: string; study: string; source: string; sha256: string; limitation: string; columns?: string[]; rows?: Record<string, string>[]; total?: number; text?: string }
export default function ResearchCatalog() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [selected, setSelected] = useState('paper-means')
  const [offset, setOffset] = useState(0)
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState('')
  const [data, setData] = useState<Artifact | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    api<Catalog>('/research/evaluation', undefined, controller.signal).then(value => { if (!Array.isArray(value.artifacts)) throw new Error('Evaluation catalog unavailable.'); setCatalog(value) }).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [retry])
  useEffect(() => {
    const controller = new AbortController()
    setError(''); setData(null)
    api<Artifact>(`/research/evaluation/${selected}?${new URLSearchParams({ offset: String(offset), query })}`, undefined, controller.signal).then(value => { if (!value.source) throw new Error('Evaluation artifact unavailable.'); setData(value) }).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [selected, offset, query, retry])
  return <section className="research-catalog"><h2>Explore the full evaluation</h2><p>The original complete manuscript and later studies use different populations and assumptions. Browse their actual saved tables, including baselines, unfavorable outcomes, coverage, budgets, ablations and uncertainty.</p>{catalog && <><p><strong>{catalog.title}</strong><br /><code>{catalog.manuscript}</code></p><label>Study and result table<select value={selected} onChange={e => { setSelected(e.target.value); setOffset(0); setQuery(''); setDraft('') }}>{catalog.artifacts.map(item => <option key={item.id} value={item.id}>{item.study}: {item.title}{item.available ? '' : ' (unavailable)'}</option>)}</select></label></>}
    <form className="search-form" onSubmit={e => { e.preventDefault(); setQuery(draft); setOffset(0) }}><label>Filter rows by method, budget, split or metric<input value={draft} onChange={e => setDraft(e.target.value)} /></label><Button type="submit">Filter results</Button></form>
    {error ? <div role="alert"><p>{error}</p><Button onClick={() => setRetry(value => value + 1)}>Retry evaluation</Button></div> : !data ? <p role="status">Loading saved evaluation…</p> : <><h3>{data.title}</h3><p className="research-boundary">{data.study}. {data.limitation}</p>{data.columns && <><p>{data.total} matching rows. Showing {data.total ? offset + 1 : 0}–{Math.min(offset + 30, data.total ?? 0)}.</p><div className="table-wrap" role="region" tabIndex={0} aria-label="Saved experiment table"><table><caption>{data.title}</caption><thead><tr>{data.columns.map(key => <th scope="col" key={key}>{key.replaceAll('_', ' ')}</th>)}</tr></thead><tbody>{data.rows?.map((row, index) => <tr key={index}>{data.columns!.map(key => <td key={key}>{row[key] || '—'}</td>)}</tr>)}</tbody></table></div><Button disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - 30))}>Previous rows</Button><Button disabled={offset + 30 >= (data.total ?? 0)} onClick={() => setOffset(value => value + 30)}>Next rows</Button></>}{data.text && <details><summary>Read saved methods and experimental report</summary><pre className="source-text">{data.text}</pre></details>}<details><summary>Exact artifact provenance</summary><p><code>{data.source}</code></p><p>SHA-256: <code>{data.sha256}</code></p></details></>}
    {catalog && <details><summary>How the scientific methods connect to the application</summary>{catalog.implementation.map(item => <article key={item.method}><h3>{item.method}</h3><p>{item.capability}</p><code>{item.code}</code></article>)}<p>The claims-and-evidence table and complete results registry provide source paths, metric definitions, denominators and qualifications. No individual clinical record is served by this explorer.</p></details>}
  </section>
}
