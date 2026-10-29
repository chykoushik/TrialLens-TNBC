import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import { DEMO_STORAGE, loadSession, parseSession } from './demoSession'
import type { DemoSession } from './demoSession'
import TrialExplorer from './TrialExplorer'
import Overview from './Overview'
import TrialSearch from './TrialSearch'
import PaperPlanner from './PaperPlanner'
import OperatorWorkspace from './OperatorWorkspace'
import ResearchShowcase from './ResearchShowcase'
import { publicDemo, publicResearch } from './publicDemo'
import GuidedDemo from './GuidedDemo'
import ReviewJourney from './ReviewJourney'
import type { AppliedReview } from './SimpleDemo'
import EvidenceSummary from './EvidenceSummary'
import TrialReader from './TrialReader'
import ResearchReports from './ResearchReports'
import ResearchResults from './ResearchResults'
import ProtocolAnnotation from './ProtocolAnnotation'
import PatientEvidence from './PatientEvidence'
import CriterionAssessments from './CriterionAssessments'
import EvidencePrioritization from './EvidencePrioritization'
import { Button, Icon, StateBadge, StatusIndicator } from './ui'
import type { Assessed, Case, Evaluation, Trial } from './types'

export { StateBadge } from './ui'


const label = (value: string) => value.replaceAll('_', ' ')
const shown = (value: string | null | undefined) => value ?? 'Not recorded'

export function CriterionCard({ node }: { node: Assessed }) {
  return <article className="criterion">
    <div className="row">
      <code>{node.criterion_id}</code>
      <StateBadge state={node.state} />
    </div>
    <p>{node.criterion.original_text}</p>
    <small>Cohort: {shown(node.criterion.cohort)} · Logic: {shown(node.criterion.logical_operator)}</small>
    <p className="muted">{node.explanation || label(node.reason_code)}</p>
    <small>Evidence: {node.evidence_ids.length ? node.evidence_ids.join(', ') : 'None'} · Temporal constraint: {shown(node.criterion.temporal_constraint)}</small>
    <Source url={node.criterion.source_url} />
    {node.dependencies.length > 0 && <div className="nested" aria-label="Logical dependencies">{node.dependencies.map(child => <CriterionCard key={child.criterion_id} node={child} />)}</div>}
  </article>
}

function Source({ url }: { url: string | null }) {
  return url && /^https:\/\/clinicaltrials.gov\/study\/NCT\d{8}$/.test(url)
    ? <p>
      <a href={url} target="_blank" rel="noreferrer">ClinicalTrials.gov source ↗</a>
    </p>
    : <p className="muted">Source: {shown(url)}</p>
}

type Mode = 'research' | 'tnbc'
type Workspace = { caseId: string; algorithm: string; budget: string; outcomes: Record<string, string>; drafts: Record<string, string>; evidenceId: string | null; reviewId: string | null }
const workspace = (caseId = ''): Workspace => ({ caseId, algorithm: 'exact_nonadaptive', budget: '3', outcomes: {}, drafts: {}, evidenceId: null, reviewId: null })
const labViews = publicDemo ? ['Research Showcase'] : publicResearch ? ['Research Results', 'Research Showcase'] : ['Research Results', 'Research Showcase', 'Research overview', 'Patient evidence', 'Criterion assessments', 'Evidence prioritization', 'Reports & benchmarks', 'Source fixtures', 'Protocol annotation']

export default function App() {
  const [saved] = useState(loadSession)
  const [restoreStatus, setRestoreStatus] = useState<'checking' | 'ready' | 'error'>(saved.session ? 'checking' : 'ready')
  const [sessionNotice, setSessionNotice] = useState(saved.notice)
  const [restoreAttempt, setRestoreAttempt] = useState(0)
  const [lastReview, setLastReview] = useState<AppliedReview | null>(null)
  const [advanced, setAdvanced] = useState(false)
  const [page, setPage] = useState('Home')
  const [mode, setMode] = useState<Mode>('tnbc')
  const [contexts, setContexts] = useState<Record<Mode, Workspace>>({ tnbc: workspace('tnbc-record-gaps'), research: workspace() })
  const context = contexts[mode]
  const { caseId, algorithm, budget, outcomes, drafts, evidenceId, reviewId } = context
  const [catalogs, setCatalogs] = useState<Record<Mode, Case[]>>({ tnbc: [], research: [] })
  const cases = catalogs[mode]
  const [calculation, setData] = useState<Evaluation | null>(null)
  const [trials, setTrials] = useState<Trial[]>([])
  const [trialWarnings, setTrialWarnings] = useState<string[]>([])
  const [trialStatus, setTrialStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [casesStatus, setCasesStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [connected, setConnected] = useState('Checking')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [pendingReview, setPendingReview] = useState<{ id: string; outcome: string } | null>(null)
  const confirmed = useRef<{ signature: string; data: Evaluation } | null>(null)
  const data = confirmed.current?.signature === JSON.stringify([mode, caseId, algorithm, budget, outcomes, refresh]) ? calculation : null
  const reviewFailure = useRef(false)
  const [step, setStep] = useState(0)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [labView, setLabView] = useState(publicDemo ? 'Research Showcase' : publicResearch ? 'Research Results' : 'Research overview')
  const [mobileOpen, setMobileOpen] = useState(false)
  const pageHeading = useRef<HTMLHeadingElement>(null)
  const sidebar = useRef<HTMLElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const returnMenuFocus = useRef(false)
  function closeNavigation() { returnMenuFocus.current = true; setMobileOpen(false) }
  const focusPage = useRef(false)
  useEffect(() => {
    if (!saved.session || restoreStatus !== 'checking') return
    const controller = new AbortController()
    api<{ session: DemoSession; validated: boolean }>('/tnbc/session/restore', saved.session, controller.signal).then(result => {
      if (controller.signal.aborted) return
      if (result.validated !== true) throw new Error('Session validation unavailable')
      const restored = parseSession(JSON.stringify(result.session))
      setContexts(previous => ({ ...previous, tnbc: { ...workspace(restored.caseId), algorithm: restored.algorithm, budget: restored.budget, outcomes: restored.outcomes, drafts: restored.drafts } }))
      setStep(restored.step); setRestoreStatus('ready'); setSessionNotice('')
    }).catch(e => {
      if (controller.signal.aborted) return
      if (e instanceof ApiError && [400, 409, 422].includes(e.status)) {
        try { localStorage.removeItem(DEMO_STORAGE) } catch { /* Storage unavailable */ }
        setRestoreStatus('ready'); setSessionNotice('Saved fictional demonstration rejected by the backend. A new demonstration has started.')
      } else { setRestoreStatus('error'); setSessionNotice('Saved demonstration could not be checked. Retry after starting the backend, or start a new demonstration. No reviews have been restored.') }
    })
    return () => controller.abort()
  }, [saved, restoreAttempt, restoreStatus])
  useEffect(() => {
    if (restoreStatus !== 'ready' || mode !== 'tnbc' || loading || pendingReview || error || !data?.demo_fixture_sha256) return
    if (confirmed.current?.signature !== JSON.stringify([mode, caseId, algorithm, budget, outcomes, refresh])) return
    try {
      const value = parseSession(JSON.stringify({ version: 1, kind: 'fictional-tnbc-demo', savedAt: Date.now(), fixtureHash: data.demo_fixture_sha256, caseId, step, algorithm, budget, outcomes, drafts }))
      localStorage.setItem(DEMO_STORAGE, JSON.stringify(value))
    } catch { setSessionNotice('Current state was not saved. Check the budget and fictional selections; browser storage may be unavailable.') }
  }, [restoreStatus, mode, loading, pendingReview, error, data, caseId, step, algorithm, budget, outcomes, drafts, refresh])
  function newDemo() {
    try { localStorage.removeItem(DEMO_STORAGE) } catch { /* Storage unavailable */ }
    setLastReview(null); setPendingReview(null); confirmed.current = null
    setContexts(previous => ({ ...previous, tnbc: workspace('tnbc-record-gaps') }))
    setData(null); setStep(0); setRestoreStatus('ready'); setSessionNotice('')
    navigate('Interactive Demo'); setRefresh(value => value + 1)
  }
  function update(change: Partial<Workspace>) {
    if ('caseId' in change || 'algorithm' in change || 'budget' in change || 'outcomes' in change) { setPendingReview(null); setLastReview(null) }
    setContexts(previous => ({ ...previous, [mode]: { ...previous[mode], ...change } }))
  }
  function chooseCase(id: string) { if (id !== caseId) update({ caseId: id, outcomes: {}, drafts: {}, evidenceId: null, reviewId: null }) }
  function navigate(destination: string) {
    if (destination === 'Real Review' || destination === 'Research Results') { setMobileOpen(false); setPage(destination); focusPage.current = true; return }
    if ((destination === 'Research Lab' && mode !== 'research') || (destination === 'Interactive Demo' && mode !== 'tnbc')) setPendingReview(null)
    const name = destination === 'Overview' ? 'Research overview' : destination
    if (labViews.includes(name) && !(page === 'Interactive Demo' && name !== 'Research overview' && name !== 'Reports & benchmarks')) setPendingReview(null)
    setMobileOpen(false)
    if (labViews.includes(name)) {
      if (page === 'Interactive Demo' && name !== 'Research overview' && name !== 'Reports & benchmarks') setStep(name === 'Patient evidence' ? 1 : name === 'Criterion assessments' ? 2 : 3)
      else { setLabView(name); setMode('research'); setPage('Research Lab') }
    } else {
      if (name === 'Interactive Demo' || name === 'Review Evidence') setMode('tnbc')
      if (name === 'Research Lab') setMode('research')
      setPage(name)
    }
    focusPage.current = true
  }
  useEffect(() => {
    const controller = new AbortController()
    const signal = controller.signal
    if (!['Interactive Demo', 'Review Evidence', 'Research Lab'].includes(page)) return
    setCasesStatus('loading')
    api<Case[]>(`/${mode}/cases`, undefined, signal).then(items => {
      if (signal.aborted) return
      setCatalogs(previous => ({ ...previous, [mode]: items })); setCasesStatus('ready')
      setContexts(previous => ({ ...previous, [mode]: { ...previous[mode], caseId: items.some(item => item.case_id === previous[mode].caseId) ? previous[mode].caseId : items[0]?.case_id ?? '' } }))
    }).catch(e => { if (!signal.aborted) { setCasesStatus('error'); setError(e.message) } })
    return () => controller.abort()
  }, [mode, refresh, page])
  useEffect(() => {
    const controller = new AbortController()
    const signal = controller.signal
    api<{ status: string }>('/health', undefined, signal).then(result => { if (!signal.aborted) setConnected(result.status === 'ok' ? 'Connected' : 'Unavailable') }).catch(() => { if (!signal.aborted) setConnected('Unavailable') })
    api<{ trials: Trial[]; warnings: string[] }>('/research/trials', undefined, signal).then(result => { if (!signal.aborted) { setTrials(result.trials); setTrialWarnings(result.warnings); setTrialStatus('ready') } }).catch(e => { if (!signal.aborted) { setTrialWarnings([e.message]); setTrialStatus('error') } })
    return () => controller.abort()
  }, [refresh])
  useEffect(() => {
    if (!['Interactive Demo', 'Review Evidence', 'Research Lab'].includes(page)) { setLoading(false); return }
    if (mode === 'tnbc' && restoreStatus !== 'ready') { setData(null); setLoading(false); return }
    if (!caseId) { setData(null); setLoading(false); return }
    const requested = pendingReview ? { ...outcomes, [pendingReview.id]: pendingReview.outcome } : outcomes
    const signature = JSON.stringify([mode, caseId, algorithm, budget, requested, refresh])
    if (confirmed.current?.signature === signature) {
      setData(confirmed.current.data); setLoading(false)
      if (!reviewFailure.current) setError('')
      reviewFailure.current = false
      return
    }
    const controller = new AbortController()
    setLoading(true); setError(''); setData(null)
    api<Evaluation>(`/${mode}/cases/${encodeURIComponent(caseId)}/evaluate`, { algorithm, budget, outcomes: requested, seed: 7 }, controller.signal)
      .then(result => {
        if (controller.signal.aborted) return
        confirmed.current = { signature, data: result }
        setData(result)
        if (pendingReview) {
          setContexts(previous => {
            const retained = { ...previous[mode].drafts }; delete retained[pendingReview.id]
            return { ...previous, [mode]: { ...previous[mode], outcomes: requested, drafts: retained } }
          })
          setPendingReview(null)
        }
      }).catch(e => {
        if (controller.signal.aborted) return
        setError(pendingReview ? `Review not applied. Draft retained. ${e.message}` : e.message)
        if (pendingReview) { reviewFailure.current = true; setPendingReview(null) }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [mode, caseId, algorithm, budget, outcomes, pendingReview, refresh, restoreStatus, page])
  useEffect(() => {
    document.title = `${page === 'Interactive Demo' ? 'Try a Demo' : page === 'Real Review' ? 'Evidence Review' : page === 'Trial Library' ? 'Explore Trials' : page === 'Research Lab' ? 'Research Tools' : page} | TrialLens-TNBC`
    if (focusPage.current) { pageHeading.current?.focus(); focusPage.current = false }
  }, [page, step, labView])
  useEffect(() => {
    if (!mobileOpen) {
      if (returnMenuFocus.current) { returnMenuFocus.current = false; menuButton.current?.focus() }
      return
    }
    sidebar.current?.querySelector<HTMLButtonElement>('button')?.focus()
    function close(event: KeyboardEvent) { if (event.key === 'Escape') closeNavigation() }
    function resize() { if (window.innerWidth > 800) setMobileOpen(false) }
    document.addEventListener('keydown', close); window.addEventListener('resize', resize)
    return () => { document.removeEventListener('keydown', close); window.removeEventListener('resize', resize) }
  }, [mobileOpen])
  function retry() { setConnected('Checking'); setTrialStatus('loading'); setError(''); setRefresh(value => value + 1) }
  function stage(id: string, outcome: string) {
    const next = { ...drafts }
    if (outcome) next[id] = outcome
    else delete next[id]
    update({ drafts: next })
  }
  function apply(id: string, outcome: string) { if (outcome && !outcomes[id] && !loading && !pendingReview && data) { setLastReview({ before: data, id, outcome }); setPendingReview({ id, outcome }) } }
  const [selectedTrial, setSelectedTrial] = useState<Trial | null>(null)
  const realTrials = trials.filter(trial => trial.is_synthetic !== true)
  const currentCase = cases.find(item => item.case_id === caseId)
  const names: Record<string, string> = { Home: 'Home', 'Interactive Demo': 'Try a Demo', 'Real Review': 'Evidence Review', 'Research Results': 'Research Results', 'Trial Library': 'Explore Trials', 'Review Evidence': 'Review Evidence', 'Research Lab': 'Research Tools' }
  const navigation = [{ name: 'Home', icon: 'overview' as const }, { name: 'Real Review', icon: 'evidence' as const }, { name: 'Research Results', icon: 'priority' as const }]
  const annotationActive = page === 'Research Lab' && labView === 'Protocol annotation'
  const showcaseActive = page === 'Research Results' || (page === 'Research Lab' && ['Research Showcase', 'Research Results'].includes(labView))
  const showContext = page === 'Research Lab' && !annotationActive && !showcaseActive
  const fullView = page === 'Interactive Demo' ? step === 1 ? 'Patient evidence' : step === 2 ? 'Criterion assessments' : step >= 3 ? 'Evidence prioritization' : 'Research overview' : labView
  const evidence = data && <PatientEvidence key={`${mode}/${caseId}`} data={data} initialEvidenceId={evidenceId} />
  const assessments = data && <CriterionAssessments key={`${mode}/${caseId}`} data={data} inspectEvidence={id => { update({ evidenceId: id }); navigate('Patient evidence'); setDetailsOpen(true) }} />
  const prioritization = <EvidencePrioritization key={`${mode}/${caseId}`} data={data} algorithm={algorithm} mode={mode} budget={budget} outcomes={outcomes} selectedId={reviewId} selectReview={id => update({ reviewId: id })} changeAlgorithm={value => { if (value !== algorithm) update({ algorithm: value, outcomes: {}, drafts: {} }) }} simulate={apply} drafts={drafts} stage={stage} loading={loading} failed={Boolean(error)} />
  const legacy = fullView === 'Patient evidence' ? evidence : fullView === 'Criterion assessments' ? assessments : fullView === 'Evidence prioritization' ? prioritization : <Overview trials={trials} trialStatus={trialStatus} trialWarnings={trialWarnings} cases={cases} casesStatus={casesStatus} caseId={caseId} data={data} mode={mode} connected={connected} loading={loading} controls={null} chooseCase={chooseCase} navigate={destination => navigate(destination === 'Trial explorer' ? 'Trial Library' : destination)} retry={retry} />
  const contextControls = <section className="persistent-context" aria-label="Persistent workspace context"><div className="context-identity"><span className="eyebrow">{mode === 'tnbc' ? 'FICTIONAL TNBC DEMO' : 'MATHEMATICAL RESEARCH'}</span><strong>{currentCase?.title ?? currentCase?.case_id ?? 'Choose a scenario'}</strong><small>{Object.keys(outcomes).length} hypothetical reviews applied</small><span className="sr-only" aria-label="Calculated scenario">{data?.case_title ?? ''}</span></div><label>Application mode<select value={mode} onChange={event => { setAdvanced(true); navigate(event.target.value === 'tnbc' ? 'Interactive Demo' : 'Research Lab') }}><option value="tnbc">TNBC demonstration cases</option><option value="research">Mathematical research scenarios</option></select></label><label>{mode === 'tnbc' ? 'Fictional TNBC case' : 'Synthetic portfolio'}<select value={caseId} disabled={!cases.length} aria-describedby="case-selection-status" onChange={event => chooseCase(event.target.value)}>{!cases.length && <option value="">Loading choices…</option>}{cases.map(item => <option key={item.case_id} value={item.case_id}>{item.title ?? item.case_id}{item.unsupported ? ' / unsupported' : ''}</option>)}</select></label><label>Total review budget<input type="number" min="0" max="100" step="0.5" value={budget} onChange={event => update({ budget: event.target.value })} /></label><Button onClick={() => update({ outcomes: {}, drafts: {} })}>Reset hypothetical reviews</Button>{mode === 'tnbc' && <Button variant="quiet" onClick={newDemo}>Start new demonstration</Button>}<p id="case-selection-status" className="context-status">{casesStatus === 'error' ? 'Scenario refresh failed. Cached choices remain available; refresh connection to retry.' : 'Fictional data only. Case changes reset reviews; page navigation preserves them.'}</p></section>
  return <div className="app product-shell simple-product" data-page={page}>
    <a className="skip-link" href="#workspace-content" onClick={event => { event.preventDefault(); document.getElementById('workspace-content')?.focus() }}>Skip to content</a>
    {mobileOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={closeNavigation} />}
    <aside ref={sidebar} className={`sidebar ${mobileOpen ? 'is-open' : ''}`} id="workspace-sidebar" aria-label="Workspace sidebar" onKeyDown={event => {
      if (!mobileOpen || event.key !== 'Tab') return
      const buttons = sidebar.current?.querySelectorAll<HTMLButtonElement>('button')
      if (!buttons?.length) return
      const first = buttons[0], last = buttons[buttons.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }}>
      <div className="brand-row"><button className="brand" aria-label="TrialLens home" onClick={() => navigate('Home')}><span className="product-mark" aria-hidden="true">T<span>↗</span></span><span>TrialLens<span className="brand-subtitle">EVIDENCE INTO FOCUS</span></span></button><button className="mobile-close icon-button" aria-label="Close menu" onClick={closeNavigation}><Icon name="close" /></button></div>
      <p className="product-edition">{publicDemo ? 'PUBLIC DEMO / FICTIONAL RECORDS' : 'TNBC RESEARCH / PROTOTYPE'}</p><nav aria-label="Main navigation">{navigation.map(item => <button key={item.name} className={(page === item.name || (item.name === 'Real Review' && page === 'Interactive Demo') || (item.name === 'Research Results' && ['Research Lab', 'Trial Library'].includes(page))) ? 'active' : ''} aria-current={(page === item.name || (item.name === 'Real Review' && page === 'Interactive Demo') || (item.name === 'Research Results' && ['Research Lab', 'Trial Library'].includes(page))) ? 'page' : undefined} onClick={() => navigate(item.name)}><Icon name={item.icon} /><span>{names[item.name]}</span>{(page === item.name || (item.name === 'Real Review' && page === 'Interactive Demo') || (item.name === 'Research Results' && ['Research Lab', 'Trial Library'].includes(page))) && <span className="nav-active-mark" />}</button>)}</nav>

    </aside>
    <main inert={mobileOpen}>{publicDemo && <p className="public-demo-banner" role="note">Public demonstration / Fictional patient records only / No live AI requests or patient uploads</p>}<header className="topbar"><div className="breadcrumb"><button ref={menuButton} className="mobile-toggle icon-button" aria-label="Open navigation" aria-expanded={mobileOpen} aria-controls="workspace-sidebar" onClick={() => setMobileOpen(true)}><Icon name="menu" /></button><span>TrialLens</span><span aria-hidden="true">/</span><strong>{page === 'Home' ? 'TrialLens' : names[page]}</strong></div><div className="topbar-status"><StatusIndicator tone={connected === 'Connected' ? 'success' : 'neutral'}>{connected}</StatusIndicator><Button variant="quiet" onClick={retry} aria-label="Refresh connection"><Icon name="refresh" size={14} /></Button></div></header>
      {showContext && contextControls}
      <div className="content" id="workspace-content" tabIndex={-1}>{page === 'Interactive Demo' && sessionNotice && <div className="notice" role="status">{sessionNotice}{restoreStatus === 'error' && <Button onClick={() => { setRestoreStatus('checking'); setRestoreAttempt(value => value + 1) }}>Retry saved demonstration</Button>}</div>}{page === 'Interactive Demo' && restoreStatus === 'checking' && <p role="status">Checking saved fictional demonstration…</p>}{page !== 'Home' && <div className="product-page-heading"><div><p className="eyebrow">{page === 'Trial Library' ? 'REAL TRIAL SOURCES' : showcaseActive ? 'SAVED RESEARCH / NO LIVE INFERENCE' : page === 'Research Lab' ? 'ADVANCED MODE' : 'FICTIONAL EVIDENCE / NO CLINICAL USE'}</p><h1 ref={pageHeading} tabIndex={-1}>{names[page]}</h1></div><span className="tag">{showcaseActive ? 'Saved research evaluations' : page === 'Trial Library' || annotationActive ? 'Public source protocols' : 'Fictional evidence'}</span></div>}
        {page === 'Home' ? <TrialSearch allowVisitor={!publicResearch} trials={realTrials} research={() => navigate('Research Results')} demo={() => navigate('Real Review')} /> : page === 'Real Review' ? <><PaperPlanner /><section className="secondary-research"><h2>Fictional clinical examples</h2><p>A separate demonstration of the five-state clinical evidence interface.</p><Button variant="quiet" onClick={() => navigate('Interactive Demo')}>Try a Demo</Button></section></> : page === 'Research Results' ? <>{publicDemo ? <ResearchShowcase /> : <ResearchResults />}<details className="secondary-research"><summary>Explore sources and research tools</summary><p>Read original trial criteria, inspect scientific methods, or open the detailed research workspace.</p><Button onClick={() => navigate('Interactive Demo')}>Try a Demo</Button><Button onClick={() => navigate('Trial Library')}>Browse saved trials</Button><Button onClick={() => navigate('Research Lab')}>Research Tools</Button><ResearchShowcase /></details>{!publicResearch && !publicDemo && <details className="secondary-research"><summary>Operator tools</summary><OperatorWorkspace trials={realTrials} /></details>}</> : page === 'Trial Library' ? publicDemo ? <section><h2>Real source, separate workflow</h2><p>The research integration used saved ClinicalTrials.gov registry text. Source browsing and annotation stay in the controlled local workspace. This hosted demo performs no retrieval or inference.</p><a href="https://clinicaltrials.gov/study/NCT01770353" target="_blank" rel="noreferrer">Open the NCT01770353 registry study</a></section> : <><p className="library-boundary">Genuine saved ClinicalTrials.gov records. Mock extraction is simulated; live inference requires separate approval. Neither enables patient assessment.</p><TrialReader allowExtraction={!publicResearch} trials={realTrials} status={trialStatus} warnings={trialWarnings} selected={selectedTrial} onSelect={setSelectedTrial} retry={retry} /></> : <>
          {loading && <p role="status" className="workspace-progress">Updating the fictional research calculation…</p>}{error && <div role="alert" className="error"><strong>Research calculation unavailable</strong><p>We could not update this review. Your selections have been kept. Please try again.</p><details><summary>Technical details</summary><p>{error}</p></details><Button onClick={retry}>Retry calculation</Button></div>}
          {page === 'Interactive Demo' ? <>{!advanced && <ReviewJourney step={step} setStep={setStep} home={() => navigate('Home')} data={data} cases={cases} caseId={caseId} chooseCase={chooseCase} drafts={drafts} stage={stage} apply={apply} outcomes={outcomes} loading={loading} lastReview={lastReview} reviewEvidence={() => navigate('Review Evidence')} restart={newDemo} />}<details className="simple-advanced" open={advanced} onToggle={e => setAdvanced(e.currentTarget.open)}><summary onClick={e => { e.preventDefault(); setAdvanced(!advanced) }}>Advanced Mode</summary>{advanced && <>{contextControls}<GuidedDemo key={caseId} step={step} detailsOpen={detailsOpen} setDetailsOpen={setDetailsOpen} setStep={value => { setStep(value); setDetailsOpen(false); focusPage.current = true }} cases={cases} caseId={caseId} chooseCase={chooseCase} data={data} drafts={drafts} stage={stage} apply={apply} outcomes={outcomes} details={legacy} /></>}</details></> : page === 'Review Evidence' ? <><p>What is recorded, missing or conflicting in the fictional case.</p>{data && <EvidenceSummary data={data} />}<Button variant="primary" onClick={() => navigate('Interactive Demo')}>Review the proposed report</Button><details className="simple-advanced"><summary>Advanced Mode: evidence inspector</summary>{evidence}</details></> : <><nav className="lab-tabs" aria-label="Research Tools sections">{labViews.map(view => <button key={view} aria-current={labView === view ? 'page' : undefined} onClick={() => { setLabView(view); focusPage.current = true }}>{view}</button>)}</nav><p hidden={annotationActive || showcaseActive} className="lab-context">Abstract research scenarios are separate from the guided TNBC cases. Strategies and forecasts retain their original mathematical assumptions.</p>{labView === 'Research Showcase' ? <ResearchShowcase /> : labView === 'Protocol annotation' ? null : labView === 'Research Results' ? <ResearchResults /> : labView === 'Reports & benchmarks' ? <ResearchReports /> : labView === 'Source fixtures' ? <><p>Explicitly synthetic source fixtures, excluded from Trial Library.</p><TrialExplorer trials={trials.filter(trial => trial.is_synthetic === true)} status={trialStatus} warnings={trialWarnings} selected={selectedTrial} onSelect={setSelectedTrial} retry={retry} /></> : legacy}</>}
          {data && !annotationActive && !showcaseActive && (page === 'Research Lab' || advanced) && <details className="research-disclosure"><summary>Sources & model limitations</summary><ul>{data.assumptions.map((assumption, index) => <li key={index}>{assumption}</li>)}</ul>{data.reliability && <><p>{data.reliability.assumption}</p><pre>{JSON.stringify(data.reliability.conditional_error_probabilities, null, 2)}</pre></>}{data.dependence_groups.map(group => <p key={group.item_ids.join(',')}>{group.item_ids.join(' + ')} / {label(group.relationship)}: {group.assumption}</p>)}<p>Exact optimization is bounded to small portfolios. Adaptive replanning is not a globally optimal adaptive policy. Lower uncertainty does not establish clinical correctness.</p></details>}
        </>}<ProtocolAnnotation active={annotationActive} trials={realTrials} /><footer>TrialLens / Research prototype / No clinical eligibility determination / <a href="https://github.com/chykoushik/TrialLens-TNBC" target="_blank" rel="noreferrer">Source code</a></footer>
      </div>
    </main>
  </div>
}

