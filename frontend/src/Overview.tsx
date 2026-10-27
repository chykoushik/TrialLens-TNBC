import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { Assessed, Case, Evaluation, State, Trial } from './types'
import { Button, DataTable, EmptyState, Icon, Panel, StateBadge, StatusIndicator, TextField } from './ui'

type LoadState = 'loading' | 'ready' | 'error'
type Props = {
  trials: Trial[]; trialStatus: LoadState; trialWarnings: string[]
  cases: Case[]; casesStatus: LoadState; caseId: string; data: Evaluation | null
  mode: 'research' | 'tnbc'; connected: string; loading: boolean; controls: ReactNode
  chooseCase: (id: string) => void; navigate: (page: string) => void; retry: () => void
}

const states: State[] = ['satisfied', 'violated', 'unknown', 'temporal', 'conflict']
const stateNotes: Record<State, string> = {
  satisfied: 'Condition observed', violated: 'Condition not met', unknown: 'Evidence unresolved',
  temporal: 'Time requirement unresolved', conflict: 'Contradictory evidence',
}

export default function Overview({ trials, trialStatus, trialWarnings, cases, casesStatus, caseId, data, mode, connected, loading, controls, chooseCase, navigate, retry }: Props) {
  const [filter, setFilter] = useState('')
  useEffect(() => { setFilter('') }, [mode])
  const sourceRecords = trials.filter(trial => trial.is_synthetic !== true)
  const syntheticSources = trials.filter(trial => trial.is_synthetic === true)
  const snapshots = trials.reduce((total, trial) => total + (trial.snapshot_count ?? 1), 0)
  const activeCase = cases.find(item => item.case_id === caseId)
  const visibleCases = cases.filter(item => `${item.title ?? ''} ${item.case_id} ${item.description ?? ''}`.toLowerCase().includes(filter.toLowerCase()))
  const assessments: Assessed[] = data?.assessment.decisions.flatMap(decision => decision.assessment.assessments) ?? []
  const latest = sourceRecords.map(trial => trial.retrieved_at).filter((date): date is string => date !== null && Number.isFinite(Date.parse(date)))
    .sort((a, b) => Date.parse(b) - Date.parse(a))[0]
  const dateLabel = latest ? new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(latest)) : 'Not recorded'

  return <div className="overview">
    <div className="overview-lead">
      <div className="library-summary">
        <div className="section-heading"><p className="eyebrow">01 / SOURCE LIBRARY</p><span className="tag">Saved records</span></div>
        <div className="library-number"><strong aria-label="Saved public study count">{trialStatus === 'ready' ? sourceRecords.length.toString().padStart(2, '0') : '\u2014'}</strong><div><h2>Studies, at the source.</h2><p>ClinicalTrials.gov eligibility text,<br className="desktop-break" /> with its original provenance.</p></div></div>
        <div className="library-foot"><span>{trialStatus === 'ready' ? `${snapshots} saved study versions${syntheticSources.length ? ` / ${syntheticSources.length} synthetic source fixtures` : ''}` : trialStatus === 'loading' ? 'Loading saved records' : 'Source library unavailable'}</span><Button variant="primary" onClick={() => navigate('Trial explorer')}>Explore trials <Icon name="arrow" size={16} /></Button></div>
      </div>
      <section className="workspace-health" aria-label="Workspace status">
        <p className="eyebrow">WORKSPACE STATUS</p>
        <dl>
          <div><dt>Research engine</dt><dd><StatusIndicator tone={connected === 'Connected' ? 'success' : connected === 'Checking' ? 'neutral' : 'error'}>{connected}</StatusIndicator></dd></div>
          <div><dt>Source library</dt><dd><StatusIndicator tone={trialStatus === 'error' || trialWarnings.length ? 'warning' : 'neutral'}>{trialStatus === 'loading' ? 'Loading' : trialStatus === 'error' ? 'Unavailable' : trialWarnings.length ? 'Loaded with warnings' : 'Loaded'}</StatusIndicator></dd></div>
          <div><dt>Latest saved retrieval</dt><dd>{trialStatus === 'ready' ? dateLabel : '\u2014'}</dd></div>
          <div><dt>Extraction policy</dt><dd>Mock by default</dd></div>
        </dl>
        <p className="health-note">Live inference requires separate opt-in and approval. No inference runs from this overview.</p>
      </section>
    </div>

    <Panel title="Saved studies" eyebrow="PUBLIC SOURCE RECORDS" accessory={<Button variant="quiet" onClick={() => navigate('Trial explorer')}>View library <Icon name="arrow" size={16} /></Button>} className="protocol-panel">
      {trialStatus === 'loading' ? <EmptyState title="Loading source library" description="Reading locally saved trial records." />
        : trialStatus === 'error' ? <EmptyState error title="Source library unavailable" description={trialWarnings.join(' ') || 'Saved records could not be loaded.'} action={<Button onClick={retry}>Try again</Button>} />
          : !trials.length ? <EmptyState title="No saved protocols" description="Saved ClinicalTrials.gov records will appear here when available. This view does not retrieve trials." action={<Button onClick={() => navigate('Trial explorer')}>Open Trial Explorer</Button>} />
            : <DataTable label="Saved protocol overview"><thead><tr><th scope="col">Registry ID</th><th scope="col">Study</th><th scope="col">Registry status</th><th scope="col">Source</th></tr></thead><tbody>{trials.map((trial, index) => <tr key={`${trial.snapshot}-${index}`}>
              <td><code>{trial.nct_id ?? 'Not recorded'}</code></td><td className="study-title"><span title={trial.title ?? undefined}>{trial.title ?? 'Title not recorded'}</span></td><td><span className="registry-status">{trial.recruitment_status ? trial.recruitment_status.replaceAll('_', ' ').toLowerCase() : 'Not recorded'}</span></td><td><span className={`source-label ${trial.is_synthetic === true ? 'is-synthetic' : ''}`}>{trial.is_synthetic === true ? 'Synthetic fixture' : 'ClinicalTrials.gov'}</span></td>
            </tr>)}</tbody></DataTable>}
      {trialStatus === 'ready' && trialWarnings.length > 0 && <div className="inline-warning">{trialWarnings.map(warning => <p key={warning}>{warning}</p>)}</div>}
    </Panel>

    <section className="simulation-workspace" aria-label="Synthetic research workspace">
      <div className="section-heading simulation-heading"><div><p className="eyebrow">02 / CONTROLLED RESEARCH</p><h2>{mode === 'tnbc' ? 'Fictional TNBC demonstration cases' : 'Available research cases'}</h2><p>Explore evidence and review strategies in an explicitly synthetic workspace.</p></div><span className="tag synthetic-tag">Fictional data</span></div>
      <div className="simulation-body">{controls}
        <div className="simulation-grid">
          <div className="scenario-list">
            <div className="scenario-list-heading"><h3>Scenario library <span>{casesStatus === 'ready' ? cases.length : '\u2014'}</span></h3><TextField label="Filter scenarios" className="filter-field" hideLabel type="search" placeholder="Filter scenarios..." value={filter} onChange={event => setFilter(event.target.value)} /></div>
            {casesStatus === 'loading' ? <EmptyState title="Loading scenarios" description="Reading the selected demonstration catalog." />
              : casesStatus === 'error' ? <EmptyState title="Scenario catalog unavailable" description="Refresh the workspace to try again." action={<Button onClick={retry}>Try again</Button>} />
                : !visibleCases.length ? <EmptyState title={filter ? 'No matching scenarios' : 'No scenarios available'} description={filter ? 'Try a different title or scenario ID.' : 'The selected catalog contains no cases.'} action={filter ? <Button onClick={() => setFilter('')}>Clear filter</Button> : undefined} />
                  : <DataTable label="Synthetic scenario library"><thead><tr><th scope="col">Scenario</th><th scope="col">Protocols</th><th scope="col">Reviews</th></tr></thead><tbody>{visibleCases.map(item => <tr className={caseId === item.case_id ? 'selected-row' : ''} key={item.case_id}>
                    <td><button className="scenario-button" aria-pressed={caseId === item.case_id} onClick={() => chooseCase(item.case_id)}><h3>{item.title ?? item.case_id.replaceAll('_', ' ')}</h3><span>{item.unsupported ? 'Unsupported planning model' : caseId === item.case_id ? 'Selected scenario' : 'Select scenario'}</span>{caseId === item.case_id && <Icon name="check" size={15} />}</button></td><td>{item.trial_count}</td><td>{item.review_count}</td>
                  </tr>)}</tbody></DataTable>}
          </div>
          <section className="current-scenario" aria-label="Current synthetic scenario">
            <span className="sr-only" role="status">{loading ? 'Evaluating synthetic evidence' : data ? 'Synthetic assessment available' : 'No synthetic assessment available'}</span>
            <p className="eyebrow">SELECTED SCENARIO</p><p className="current-scenario-title">{activeCase?.title ?? activeCase?.case_id.replaceAll('_', ' ') ?? 'No scenario selected'}</p>
            {(activeCase?.description || data?.case_description) && <p>{activeCase?.description ?? data?.case_description}</p>}
            {activeCase?.unsupported && <p className="inline-warning">{activeCase.unsupported}</p>}
            <div className="scenario-reading"><span>Weighted uncertainty</span><strong>{loading ? '\u2014' : data?.assessment.uncertainty ?? '\u2014'}</strong><small>{loading ? 'Evaluating synthetic evidence' : 'Backend-computed model uncertainty'}</small></div>
            {data && !loading ? <>
              <div className="state-summary-heading"><span>Top-level criteria</span><strong>{assessments.length}</strong></div>
              <div className="state-breakdown" aria-label="Synthetic criterion state counts">{states.map(state => {
                const count = assessments.filter(node => node.state === state).length
                return <div className="state-count" key={state}><StateBadge state={state} /><span className="state-track" aria-hidden="true"><span className={state} style={{ width: `${assessments.length ? count / assessments.length * 100 : 0}%` }} /></span><span aria-label={`${state} criteria`}>{count}</span></div>
              })}</div>
              <details className="state-help"><summary>How to read these states</summary><dl>{states.map(state => <div key={state}><dt>{state}</dt><dd>{stateNotes[state]}</dd></div>)}</dl><p>A satisfied exclusion condition is a blocker. These counts are not eligibility decisions.</p></details>
            </> : <p className="muted">{loading ? 'The state summary appears after evaluation.' : 'No assessment is available for this scenario.'}</p>}
            <div className="scenario-actions"><Button onClick={() => navigate('Patient evidence')}>Inspect patient evidence <Icon name="arrow" size={16} /></Button><Button variant="quiet" onClick={() => navigate('Evidence prioritization')}>Review priorities <Icon name="arrow" size={16} /></Button></div>
          </section>
        </div>
      </div>
    </section>
    <div className="research-boundary"><span className="boundary-mark" aria-hidden="true">R</span><div><strong>Research use. Explicit boundaries.</strong><p>Public trial records stay separate from fictional patients and protocols. Generated criteria require review; this workspace does not determine clinical eligibility.</p></div></div>
  </div>
}
