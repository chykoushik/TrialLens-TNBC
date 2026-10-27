import facts from './fixtures/research_showcase.json'

export default function ResearchShowcase() {
  return <section className="research-showcase" aria-labelledby="showcase-title" id="research-showcase">
    <p className="simple-kicker">RESEARCH SHOWCASE / SAVED RESULTS, NO LIVE INFERENCE</p>
    <h2 id="showcase-title">An AI proposal must earn its evidence link.</h2>
    <p>Nemotron proposes clinical-trial criteria. Deterministic checks verify structure, exact source wording, scope and provenance before any research use. The fictional patient demonstration uses authored examples and a separate symbolic planner.</p>
    <div className="showcase-grid"><article><h3>Tested on real registry text</h3><p>NVIDIA Nemotron 3 Super ran through Nebius Token Factory in three separately authorized, single-request attempts. No retries were automatic.</p><ol><li>First request: timeout; provider processing and billing unknown.</li><li>Second: output limit exhausted by reasoning; no usable final criteria.</li><li>Third: {facts.evidence_entries} evidence entries, rejected by strict validation.</li></ol></article>
    <article><h3>Recovery without invented logic</h3><p>Unique text matches locate candidate clauses in the unchanged source. Recovered quotations retain original characters and complete boundaries. Ambiguous scope and compound meaning stay blocked.</p><dl><div><dt>Source-aligned entries passing per-entry checks</dt><dd>{facts.automatically_recovered} / {facts.evidence_entries}</dd></div><div><dt>Entries still requiring correction</dt><dd>{facts.remaining_entries}</dd></div><div><dt>Whole-extraction validation errors remaining</dt><dd>{facts.validation_errors}</dd></div></dl></article></div>
    <p className="clause-warning"><strong>Full extraction: validation_failed.</strong> No validated whole-extraction output exists. All model results, including the five source-aligned entries, remain unreviewed. These counts are validation diagnostics, not clinical accuracy or human-reviewed ground truth.</p>
    <p><strong>What is distinctive:</strong> source-linked model proposals are separated from deterministic five-state reasoning and budgeted review prioritization. Missing, conflicting and time-dependent evidence stay explicit. The planner selects existing records for review; it does not order medical tests.</p>
    <p><strong>Limits:</strong> small fictional portfolios, illustrative probabilities, incomplete cohort and Boolean interpretation, no clinical eligibility decision, and no measured clinical performance. Hosted visitors cannot call Nebius or annotate real sources.</p>
    <p>Model: <code>{facts.model}</code>. Source: <a href="https://clinicaltrials.gov/study/NCT01770353" target="_blank" rel="noreferrer">ClinicalTrials.gov NCT01770353</a>. Saved results are shown retrospectively; this page does not run an extraction.</p>
  </section>
}
