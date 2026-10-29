import { useRef, useState } from 'react'
import { EmptyState } from './ui'

const reports: Record<string, () => Promise<unknown>> = import.meta.env.VITE_PUBLIC_DEMO === '1' ? {} : {
  '../../results/prioritization/coherent/20261025-imperfect-analysis-v1/report.md': () => import('../../results/prioritization/coherent/20261025-imperfect-analysis-v1/report.md?raw').then(module => module.default),
  '../../results/prioritization/sensitivity/20261025-final/report.md': () => import('../../results/prioritization/sensitivity/20261025-final/report.md?raw').then(module => module.default),
}
export default function ResearchReports() {
  const generation = useRef(0)
  const [selected, setSelected] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  async function read(path: string) {
    const version = ++generation.current
    setSelected(path); setText(''); setError('')
    try { const report = await reports[path]() as string; if (generation.current === version) setText(report) } catch { if (generation.current === version) setError('Saved report could not be loaded.') }
  }
  return <section className="research-reports"><p className="eyebrow">SAVED RESEARCH ARTIFACTS / READ ONLY</p><h2>Reports & benchmarks</h2><p>Existing reports are preserved verbatim. Software fixtures, missing reviewed labels and experimental limitations retain their original descriptions. No benchmark is run from this page.</p><div className="report-layout"><nav aria-label="Saved report list">{Object.keys(reports).sort().map(path => <button key={path} aria-pressed={selected === path} onClick={() => read(path)}>{path.replace('../../results/', '')}</button>)}</nav><div>{error ? <EmptyState error title="Report unavailable" description={error} /> : text ? <><h3>{selected.replace('../../results/', '')}</h3><pre tabIndex={0} aria-label="Original saved report">{text}</pre></> : <EmptyState title={Object.keys(reports).length ? 'Select a saved report' : 'No saved reports available in this build'} description="Reports are loaded from existing local artifacts. No performance values are invented." />}</div></div></section>
}
