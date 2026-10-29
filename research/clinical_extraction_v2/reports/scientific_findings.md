# Clinical extraction and verification v2: technical findings

Public scientific excerpt; operational development-status notes omitted. Numerical results, scientific limitations and citations are retained. Original source SHA-256: `5f22f9677caa574d3c43e54b03911c954101bd71135a0346aaf2d4b602de0b6c`.

## Result and interpretation

The context filter removes the three previously accepted unsupported assertions while retaining all thirteen previously source-supported legacy reference matches on unchanged OCR. A stricter independently callable source verifier also removes these errors, but recovers only eleven legacy references on unchanged OCR. It withholds correct evidence as well. Ten image-assisted transcription operations restore the full pipeline to twenty of twenty legacy references. That is assisted OCR on exposed examples, not autonomous clinical inference or a new held-out accuracy claim.

The new patient evaluation yields five of six categorical references for both v1 and the full pipeline. There is no measured recovery advantage over v1 on this evaluation set. Zero unsupported accepted assertions were observed in its five emitted assertions. The sample is too small and the references insufficiently independent for a clinical accuracy claim.

## Cohorts and annotations

The preserved fifteen-patient/eighteen-report corpus supplies the exposed regression set. All prior 54 factual annotations remain unchanged. Eight additional patients and eight original canonical PDFs were selected by patient hash without inspecting prediction yield or receptor status. Four additional patients are development and four are evaluation; none overlaps the old patients. Only three new development and two new evaluation patients contribute categorical facts. No shared transcript hash crosses partitions in the selected corpus.

Direct inspection of the first two pages where available added 59 positive factual annotations: thirty development and 29 evaluation, including eight and six categorical receptor facts respectively. This brings the inventory to 113, with 35 categorical receptor facts across old and new material, including the prior weakly-positive literal. The fixed legacy primary denominator remains twenty; the additional weakly-positive prior fact is not silently added to that denominator. The full pipeline supports 32/35 categorical references across all cohorts. This is positive-reference recovery, not exhaustive recall.

The additions include grades, stage strings, specimen descriptions, lymph-node findings, explicit absent invasion, assay ratios and a literal treatment-none source field. Regional lymph-node involvement is not relabeled as distant metastasis. A historical grade I biopsy and current G2 finding remain context-separated; IHC positive/score 2+ and FISH not-amplified remain separate assay findings, not an invented binary clinical truth or automatically adjudicated contradiction. All annotations are assistant image transcriptions, independently inspectable but not qualified independent clinician labels. Broader inventory fields do not imply that the automated verifier supports every field: unsupported entity schemas remain unresolved.

## Measured legacy results

| Method | Value matches / 20 | Source-supported / 20 | Supported accepted categorical spans | Report-field coverage |
|---|---:|---:|---:|---:|
| Original | 5 | 4 | 7/7 | 7/54 (13.0%) |
| Previous v1 | 14 | 13 | 19/22 | 19/54 (35.2%) |
| Context filter, unchanged OCR | 13 | 13 | 19/19 | 17/54 (31.5%) |
| Strict verification, unchanged OCR | 11 | 11 | 15/15 | 15/54 (27.8%) |
| Image-assisted OCR alone | 20 | 20 | 28/29 | 24/54 (44.4%) |
| Full, image-assisted legacy input | 20 | 20 | 25/25 | 24/54 (44.4%) |

Precision is an assistant audit of emitted categorical assertions only. Coverage is unique report/receptor pairs with an accepted assertion divided by three receptor opportunities per report; it is not reference recall or clinical eligibility coverage. Duplicate overlapping spans affect the assertion counts but do not become independent patients. Whole-document precision across every entity type, exhaustive recall and F1 are not available and remain null. Oracle transcription-passage results are not used as end-to-end performance in this phase.

The fixed legacy reference comparison alone does not measure every emitted result. Historical original-breast-tumor ER text explains the original five value matches versus four context-supported matches. A control-derived PR negative explains the old fourteen versus thirteen. Two PR borderline readings come from HSCORE legends. These three false accepted assertions are withheld by context rules; their values are not rewritten.

## Independent source verification and abstention

`verification.py` reads only a candidate and source envelope, never benchmark labels. It implements directly supported, contradicted, ambiguous, insufficient evidence and source-unavailable/unreliable outcomes. It checks source offsets, text hashes and patient/report linkage, applies intervening and preceding negation, rejects family/historical/pending contexts and control/threshold text, requires an explicit field/value relationship, and checks supplied unit/specimen/assay/date consistency. Unknown assay, specimen or date remains null; a source-supported literal with missing context never establishes a current screening-time clinical fact. Identity relies on the frozen canonical source registry, not an independent re-identification procedure.

Every accepted full-pipeline categorical assertion passes explicit source-linkage and support checks. Across 26 documents, the assisted full pipeline emits 46 categorical candidates: 38 are accepted as source literals, seven remain ambiguous and one has insufficient evidence. The eight abstentions include five source-supported spans: four unfamiliar/corrupted intervening-text spans and one incomplete joint-receptor span. Three of these are overlapping/redundant legacy spans; two are actual additional-development ER/PR facts lost to strict grammar. The other abstentions concern control or historical contexts. Nothing becomes a confirmed clinical fact, even when the source literal is accepted.

For unchanged candidates across all 23 patients, context filtering withholds three unsupported assertions and zero supported assertions. Strict verification withholds three unsupported and six supported assertions. These are selection effects, not evidence that the system corrected the underlying clinical values. Image assistance changes the text input and is evaluated separately. The runtime/source-ablation tables contain all eleven fixed method variants, including adverse results.

Development-only score selection considered thresholds 0, 0.9, 0.96 and 0.99. The first two retain the same five supported development assertions; the latter two retain none. The tie rule chooses zero. Therefore selective score thresholding adds no benefit beyond the source rules here; source verification and full-without-score-threshold agree. Rule scores are uncalibrated priorities, not probabilities. High-threshold precision is undefined when no output exists. Span identity checks alone do not reduce semantic errors. No semantic encoder or language-model component was retained because local v1 evidence supplied no incremental retrieval benefit.

## New development and evaluation

Additional development has eight categorical facts across three contributing patients. V1 supports eight; strict/full supports six, with two legitimate activity/was-judged-as-negative statements withheld by the narrower verifier. This adverse outcome is retained. No new development reference was used to choose the already frozen score threshold.

New evaluation has six categorical facts across two contributing patients among four selected reports. Original supports three; v1 and full support five. Both v1 and full emit five supported categorical spans, giving 5/5 audited precision and 5/12 report-field coverage (41.7%). One PR fact remains missed in corrupted OCR; evaluation text was not manually corrected to rescue it. The two other selected reports contribute noncategorical factual inventory items but do not inflate the categorical sample size.

The new patient split and inference rules were frozen before evaluation images, labels or predictions were inspected. One post-freeze software hardening change rejects a nonsensical non-null unit on a categorical value, identified through an independent software constraint rather than clinical labels. The initial freeze and amended source hash are retained. Independent reconstruction confirms all seven previously computed scientific tables are unchanged; added linkage/alignment columns in one table are excluded when reconstructing its earlier schema. No threshold, clinical candidate rule or reference was tuned to new evaluation outcomes. This is locally frozen evaluation, not external preregistration or independent expert validation.

## Diagnostic controls and tests

All original twenty control inputs and expected outputs were preserved. Full verification passes 20/20, versus v1 17/20 and original 19/20. Its fixed negation subset passes 4/4, versus v1 2/4; plural control wording is also fixed. A separate expanded 24-case suite passes 22/24 for full versus 15/24 for each prior implementation. The two retained failures are shared ER/PR-negative forms for which the unchanged generator fails to emit the ER result. No control was weakened, removed or relabeled.

The automated suite passes 47 tests; 207 original solver/certifier/METABRIC/backend regression tests pass. Tests cover linkage, source hashes/offsets, missing text, contradictory values, supplied assay/specimen/date inconsistency, incompatible units, frozen annotations/splits, reference isolation, abstention, retained failures and blocked clinical model execution. Passing software tests are distinguished from the two expanded diagnostic failures.

## Uncertainty and resources

Patient-aware bootstrap intervals use 10,000 replicates, seed 20261027. New evaluation full patient-mean reference recovery is 83.33%, descriptive interval [66.67%,100%], based on only two patients. Full-minus-v1 is exactly zero on both patients, producing a degenerate [0,0] paired interval that does not prove equivalence. Legacy assisted-minus-v1 patient-mean supported recovery is +27.08 percentage points, interval [0,56.25], conditional on exposed source transcriptions. No clinical population generalization follows.

Precision intervals resample emitting patients and condition on the assistant source audit. Zero observed errors yields degenerate intervals for some methods; this is not a guarantee of perfect population precision. All fixed methods, thresholds and negative results are descriptive. No unadjusted confirmatory p-values or selectively reported significance claim is produced.

`runtime_memory.csv` records warm-process time and peak Python allocations for all methods on 26 documents; it excludes total process RSS, GPU memory and human review cost. Runtime and memory vary between replays. The pipeline uses the existing CPU research environment; it makes no external model requests or paid calls.

## OCR, TrialLens and remaining limits

Ten verified transcription overlays on four exposed reports retain original PDF/image hashes, original and corrected fragments, both transcript copies, correction provenance and original/corrected intervals. Replacement characters map to the entire replaced original interval rather than a guessed one-character alignment. Original sources are unchanged. No automatic OCR engine improvement or new-evaluation OCR correction is claimed. The existing MACCROBAT whitespace defect remains preserved in prior work and is not a clinical label.

Twenty-three structured evidence bundles preserve report identity, source values/units, available assay/block context, uncertainty, unknown dates, opposing values and verification status. The genuine original solver and certifier import with unchanged signatures and hashes. All clinical runs are blocked because screening-time references, grounded Boolean criterion semantics, calibrated observation laws/priors and measured review costs are absent. Source support never substitutes for these inputs.

There is still no adequate new sequential clinical review cohort: the full preserved collection has three paired canonical-record patients, two excluding autopsy, zero with three records and zero with verified chronology. Passages are never counted as separate reports. Further validation needs authorized longitudinal records, stable patient/specimen/date linkage, qualified independent annotation and an independently calibrated clinical observation model.
