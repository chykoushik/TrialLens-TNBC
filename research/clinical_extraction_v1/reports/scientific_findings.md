# Clinical evidence extraction v1

## Main finding

The new frozen rule-based extractor improves recovery of known literal receptor values, but reduces categorical assertion precision and fails important negation controls. It is a research candidate generator requiring source review, not a clinically ready extractor. Source alignment alone does not validate the meaning of an observation. No new clinical planner accuracy or policy superiority is established.

## Cohort, design and contamination

The study reuses the unchanged authentic breast report collection and the previous 48 assistant image transcriptions: fifteen patients, eighteen documents and twenty categorical receptor facts from eight contributing patients. All 84 original predictions are reproduced and indexed. The new pipeline produces 111 observations, including measurements, histology, grades, pathologic tokens and unasserted mentions. Every observation retains raw OCR offsets; a source index and TrialLens bundles supply document hashes and source paths.

Before implementation evaluation, a deterministic hash split froze five development and ten evaluation patients. Four patients in each partition contribute categorical references: eight development and twelve evaluation facts. All records of one patient remain together. Local LSA fitting uses development documents plus fixed query templates; no evaluation documents or reference outcomes enter the SVD fit. There are no pretrained clinical encoder weights in the used environment and no model downloads or paid inference calls were made.

These are historically exposed references: all were available in prior scripts and an earlier study. This split is not a pristine external holdout, and its very small denominators do not justify confirmatory inference. `implementation_freeze.json` pins pipeline and unit-test hashes before evaluation and new annotation. The frozen extractor was not changed to repair observed evaluation failures. Post hoc manual source audits are labeled separately.

## Original versus improved results

| Task and denominator | Original | Improved |
|---|---:|---:|
| Document-field categorical reference value recovery, all twenty facts | 5/20 (25%) | 14/20 (70%) |
| Same metric, evaluation twelve facts | 5/12 (41.7%) | 7/12 (58.3%) |
| Post hoc source-context support for the twenty referenced results | 4/20 (20%) | 13/20 (65%) |
| Same source-context metric, evaluation twelve facts | 4/12 (33.3%) | 6/12 (50%) |
| Source-supported categorical assertion precision, audited emitted spans | 7/7 (100%) | 19/22 (86.4%) |
| Unsupported categorical assertion rate in that output audit | 0/7 | 3/22 (13.6%) |
| Literal numeric percent recovery, seven original facts | 2/7 | 5/7 |
| Oracle reference-passage precision | 11/11 (100%) | 20/20 (100%) |
| Oracle reference-passage recall | 11/20 (55%) | 20/20 (100%) |
| Oracle reference-passage F1 | 0.7097 | 1.0000 |
| Synthetic software controls, twenty cases | 19/20 | 17/20 |

The source-support audit measures whether emitted categorical spans are supported by the inspected source page. It does not exhaustively annotate every missed result in eighteen documents, so document-wide precision across all entity types, exhaustive recall and F1 remain unavailable. Oracle-passage metrics run each algorithm on the original image-transcribed reference quote with a specified target receptor. They isolate parsing under favorable transcription and known evidence location; their perfect improved scores are not end-to-end clinical extraction performance.

The old five document-field matches include one historical original-breast-tumor ER statement rather than the referenced current specimen result. The improved fourteen include a PR negative match taken from control text. These explain the source-context-adjusted four and thirteen. The three unsupported new categorical assertions are one control-derived PR negative and two PR borderline threshold-legend readings. Two other categorical candidates are explicitly rejected and not counted among the 22 accepted assertions. Duplicate overlapping positive spans remain counted as emitted assertions, not independent patients.

## Retrieval comparisons

All six implementations execute: original full-document regex, improved keyword passage retrieval, TF-IDF/SVD latent-semantic retrieval, equal-weight lexical/LSA hybrid, hybrid with explicit-result reranking, and improved full-document extraction with offset verification. Retrieval methods use the same improved parser on at most three 65-word windows, stride forty; original and full extraction read the whole document. Thus their reference recovery comparison is a workflow comparison, not a claim that parser changes are caused by ranking alone.

Keyword, LSA, hybrid and reranking each recover fourteen of twenty document-field reference values, seven of twelve in evaluation. No incremental value-recovery benefit of LSA, hybrid weighting or reranking is demonstrated. Heuristic source-anchor overlap is also exported, but short OCR-damaged references sometimes align to unrelated text. Those counts are localization diagnostics rather than validated evidence retrieval recall. A separately annotated OCR-span gold set is still required for trustworthy retrieval recall at k. Evidence location within a document never becomes an independent review action or a new report.

## Failure causes and component attribution

`data/reviewed_failure_analysis_private.csv` links every categorical reference to PDF/page/hash, image quote, OCR localization, original outcome, improved outcome and reviewed cause. Five misses involve assay modifiers, parenthetical text or spacing. Two joint ER/PR facts require shared “both are interpreted” handling, with OCR corruption. One reference requires bridging numeric HSCORE text. Seven original misses involve missing/corrupted OCR result text or biomarker aliases; the remaining source-context issue is the old historical-specimen match. The four straightforward original source-context matches remain explicit in the taxonomy.

OCR can omit an entire result, substitute `2CGATIVE`, deform HER2 aliases, or remove borderline status. Such absent information cannot be faithfully reconstructed by guessing a clinical label. New broad status windows also attach controls or threshold legends to receptors. The improved normalizer preserves source offsets through Unicode normalization and a small development-derived OCR substitution list; it does not rewrite the underlying transcripts.

Frozen one-component-removal ablations show: removing synonyms reduces recovery from fourteen to seven overall (development 7 to 4; evaluation 7 to 3); removing OCR correction reduces fourteen to thirteen, entirely in development; removing joint interpretation reduces fourteen to thirteen, entirely in development. These effects overlap and are not additive causal contributions. Removing the existing context filter or offset verification changes no known-reference recovery. Offset verification checks source identity, not semantic validity. Semantic and reranking additions yield no value-recovery increase over keyword retrieval.

Four negation controls give original 4/4 versus improved 2/4. Three reference/control cases give original 3/3 versus improved 2/3. Missing-result handling remains 2/2 for both. The improved failures include negation between receptor and status and plural control wording. These are diagnostic failures, retained in `synthetic_controls.csv`; they are not hidden by the passing regression tests, and their expected values are synthetic software specifications rather than patient labels.

## Benchmark expansion and provenance

Six positive factual annotations were added after model freeze by direct inspection of four original page images: histologic grade III, nuclear grade III, another SBR grade III, separate left/right SBR grade 2 statements and Nottingham score 8/9. Their exact source contexts and hashes are retained in `additional_references_private.json`, bringing the factual inventory to 54. They are independently inspectable assistant transcriptions, not independent clinician annotations. Original references were never changed. Both extractors recover four of these six by the stated document-field value rule; nuclear-grade schema separation and Nottingham-score extraction remain incomplete, and specimen-linked extraction is not established.

All 111 new observations align exactly with saved source text. Audited categorical assertions additionally retain page-image hashes. Structural alignment does not erase the three demonstrated semantic errors. Unreviewed treatment and metastasis mentions have null asserted values; no mention is promoted to treatment receipt, metastatic status, clinical eligibility or a screening date.

The MACCROBAT audit rechecks all 25,189 published entity spans. Of these, 25,188 match exactly. PMID 25661749, entity T145, spans [2837,2841), slices `8\u2005mg`; the published text adds trailing tab/four-per-em whitespace. Whitespace-normalized strings agree. The source and annotation were preserved; the unmatched exact span is excluded from any proposed strict span training/evaluation. No corrected clinical gold was invented, and MACCROBAT was not repurposed as longitudinal patient reports.

## Statistical uncertainty

Ten thousand patient-cluster bootstrap replicates use seed 20261027. All-reference patient mean value recovery is 22.92% original and 75% improved, with descriptive 95% intervals [2.08%,50%] and [45.83%,100%]. The evaluation improved patient mean is 58.33%, interval [16.67%,100%]. The paired evaluation patient-mean improvement is 12.5 percentage points, interval [0,25] points, based on four patients. This is not a confirmatory superiority result.

Post hoc improved categorical assertion precision has a descriptive patient-cluster interval [65.38%,100%] over nine contributing patients. The original seven assertions from four patients have no observed errors, yielding a degenerate [100%,100%] percentile interval; this is not evidence of perfect population precision. Oracle improved F1 likewise has a degenerate interval because every positive reference passage matches. The original oracle F1 interval is [0.2667,0.9057]. These intervals condition on the convenience cohort and annotations and exclude independent annotation uncertainty, refitting and external domain shift. No hypothesis-test p-values or population clinical guarantees are reported.

## TrialLens readiness and remaining requirements

Fifteen structured bundles preserve report identity, patient observations, missing mappings, competing candidate values, exact original criterion text, source audit and unknown dates. All sixty candidate criterion states remain unknown with null clinical references. Unverified contradictions are retained for review rather than automatically becoming a clinical conflict judgment. The genuine solver/certifier import successfully and retain their original hashes. All fifteen incomplete bundles are rejected by the clinical-input guard. No clinical solver or certification run is performed without grounded criteria, calibrated joint observation likelihoods, prior, measured review costs, screening dates and independent clinical labels.

No new multi-report collection became available. The preserved source inventory still has only three distinct-record paired patients, two excluding autopsy, zero with three canonical reports and zero with verified longitudinal chronology. n2c2 individual approval/DUA, THYME authorized text access, MIMIC credentialing or an authorized institutional breast cohort remain possible access routes documented in the prior fourteen-source matrix. Appropriate independent clinicians must annotate actual screening-time criterion states and adjudicate disagreement. Splitting reports into passages does not solve those requirements.

Thirty-six new software/integrity tests and 207 original solver/certifier/backend/METABRIC regression tests pass. Independent verification reexecutes the algorithms and retrieval, recalculates metrics and bootstrap intervals, verifies source linkage and protected-file hashes, and records the environment and artifact manifest. It does not constitute a second clinician review. Three PDF figures were rendered and visually checked. No source downloads, uploads, paid inference, website changes, commits, pushes or deployments were performed.
