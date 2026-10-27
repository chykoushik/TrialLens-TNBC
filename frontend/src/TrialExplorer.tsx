import { useEffect, useRef, useState } from 'react'
import type { Trial } from './types'
import TrialExtraction from './TrialExtraction'
import { Button, DataTable, EmptyState, Panel, TextField } from './ui'

type Props = {
  trials: Trial[]; status: 'loading' | 'ready' | 'error'; warnings: string[]
  selected: Trial | null; onSelect: (trial: Trial) => void; retry: () => void
}

export default function TrialExplorer({ trials, status, warnings, selected, onSelect, retry }: Props) {
  const [search, setSearch] = useState('')
  const [registryStatus, setRegistryStatus] = useState('')
  const [libraryOpen, setLibraryOpen] = useState(true)
  const inspector = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const libraryContent = useRef<HTMLDivElement>(null)
  const pendingFocus = useRef(false)
  const pendingLibraryFocus = useRef(false)
  const current = trials.find(trial => trial.nct_id === selected?.nct_id && trial.snapshot === selected?.snapshot) ?? null
  const libraryExpanded = libraryOpen || !current
  const terms = search.toLowerCase().trim().split(/\s+/).filter(Boolean)
  const visible = trials.filter(trial => {
    const metadata = [trial.nct_id, trial.title, ...trial.conditions, trial.recruitment_status, trial.retrieved_at, trial.snapshot].join(' ').toLowerCase()
    return (!registryStatus || trial.recruitment_status === registryStatus) && terms.every(term => metadata.includes(term))
  })
  const statuses = [...new Set(trials.map(trial => trial.recruitment_status).filter((value): value is string => Boolean(value)))].sort()

  function focusInspector() {
    inspector.current?.focus({ preventScroll: true })
    inspector.current?.scrollIntoView?.({ behavior: 'auto', block: 'start' })
  }

  function select(trial: Trial) {
    if (!libraryExpanded && current?.nct_id === trial.nct_id && current?.snapshot === trial.snapshot) { focusInspector(); return }
    pendingFocus.current = true
    setLibraryOpen(false)
    onSelect(trial)
  }

  function changeStudy() {
    pendingLibraryFocus.current = true
    setLibraryOpen(true)
  }

  useEffect(() => {
    if (pendingFocus.current) { focusInspector(); pendingFocus.current = false }
  }, [current, libraryExpanded])

  useEffect(() => {
    if (!libraryExpanded || !pendingLibraryFocus.current) return
    const target = list.current?.querySelector<HTMLButtonElement>('button[data-study][aria-pressed="true"]')
      ?? libraryContent.current?.querySelector<HTMLInputElement>('input')
    target?.focus({ preventScroll: true })
    libraryContent.current?.parentElement?.scrollIntoView?.({ behavior: 'auto', block: 'start' })
    pendingLibraryFocus.current = false
  }, [libraryExpanded])

  return <div className="trial-explorer">
    <Panel title="Study library" eyebrow="SAVED CLINICALTRIALS.GOV RECORDS" className="study-library"
      accessory={<div className="library-actions"><span className="tag">{status === 'ready' ? `${visible.length} / ${trials.length} studies` : status === 'loading' ? 'Loading' : 'Unavailable'}</span>
        {current && <Button aria-expanded={libraryExpanded} aria-controls="study-library-content" onClick={() => {
          if (libraryExpanded) { pendingFocus.current = true; setLibraryOpen(false) } else changeStudy()
        }}>{libraryExpanded ? 'Return to inspection' : 'Change study'}</Button>}
      </div>}>
      {!libraryExpanded && current && <div className="library-selection-summary"><code>{current.nct_id}</code><span>{current.title ?? 'Title not recorded'}</span></div>}
      <div id="study-library-content" ref={libraryContent} hidden={!libraryExpanded}>
      <div className="study-filters">
        <TextField label="Search trials" type="search" placeholder="NCT ID, title, condition or metadata" value={search} onChange={event => setSearch(event.target.value)} />
        <label>Registry status<select value={registryStatus} onChange={event => setRegistryStatus(event.target.value)}><option value="">All statuses</option>{statuses.map(value => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></label>
      </div>
      {status === 'loading' ? <EmptyState title="Loading saved studies" description="Reading the local registry catalog." />
        : status === 'error' ? <EmptyState error title="Study library unavailable" description={warnings.join(' ') || 'Saved records could not be loaded.'} action={<Button onClick={retry}>Retry library</Button>} />
          : !trials.length ? <EmptyState title="No saved studies" description="No locally saved trial records are available. No live retrieval is performed here." />
            : !visible.length ? <EmptyState title="No matching studies" description="Try another registry ID, title, condition or status." action={<Button onClick={() => { setSearch(''); setRegistryStatus('') }}>Clear study filters</Button>} />
              : <div ref={list} onKeyDown={event => {
                if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || !(event.target instanceof HTMLButtonElement)) return
                const buttons = Array.from(list.current?.querySelectorAll<HTMLButtonElement>('button[data-study]:not(:disabled)') ?? [])
                const index = buttons.indexOf(event.target)
                if (index < 0) return
                event.preventDefault()
                const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))
                buttons[next]?.focus()
              }}><DataTable label="Saved study selection"><thead><tr><th scope="col">Study / registry ID</th><th scope="col">Conditions</th><th scope="col">Registry status</th><th scope="col">Versions</th></tr></thead>
                <tbody>{visible.map((trial, index) => <tr key={`${trial.snapshot}-${trial.nct_id}-${index}`} className={current === trial ? 'selected-row' : ''}>
                  <td><button data-study className="study-select" disabled={!trial.nct_id} aria-label={`Inspect extraction for ${trial.nct_id ?? 'record without NCT ID'}`} aria-pressed={current === trial} aria-controls="protocol-inspection" onClick={() => select(trial)}>
                    <code>{trial.nct_id ?? 'NCT ID unavailable'}</code><span className="study-list-title" title={trial.title ?? undefined}>{trial.title ?? 'Title not recorded'}</span><small>{trial.is_synthetic === true ? 'Synthetic source fixture' : 'ClinicalTrials.gov source'}</small>
                  </button></td><td><span className="study-list-conditions">{trial.conditions.join(' / ') || 'Not recorded'}</span></td><td><span className="registry-status">{trial.recruitment_status?.replaceAll('_', ' ').toLowerCase() ?? 'Not recorded'}</span></td><td>{trial.snapshot_count ?? 1}</td>
                </tr>)}</tbody></DataTable></div>}
      {status === 'ready' && warnings.map(warning => <p className="inline-warning" key={warning}>{warning}</p>)}
      {current && !visible.includes(current) && <p className="muted">The selected study is outside the current filter. Its inspection remains open.</p>}
      </div>
    </Panel>
    {current && !libraryExpanded && <div className="inspection-navigation"><span>Inspecting saved source / {current.nct_id}</span><Button variant="quiet" onClick={changeStudy}>Back to study list</Button></div>}
    <div id="protocol-inspection" ref={inspector} tabIndex={-1} role="region" aria-label={current ? `Extraction panel for ${current.nct_id}` : 'Protocol inspection workspace'}>
      {current?.nct_id ? <TrialExtraction key={`${current.nct_id}-${current.snapshot}`} nctId={current.nct_id} snapshot={current.snapshot} study={current} />
        : <div className="inspection-placeholder"><EmptyState title="Select a study to inspect" description="Choose a saved registry record to compare its original eligibility text with structured extraction and validation results." /></div>}
    </div>
  </div>
}
