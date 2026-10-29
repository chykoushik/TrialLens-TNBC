# Scientific findings

Public scientific excerpt; operational development-status notes omitted. Numerical results, scientific limitations and citations are retained. Original source SHA-256: `958fdd7c97e65e645096f2e9048160e505622678027e789d0461c8e55e78e040`.

## Scope and actual cohort

All labels are deterministic archival rules, not independent expert judgments or current trial eligibility. Exact retrieval uses actual source values. The separate observation-channel study simulates predicate errors around those source targets; it does not generate medical measurements.

The supplied METABRIC archive contains 2,509 patients and 2,509 samples. The primary sample-status rule gives 320 TNBC, 1,979 non-TNBC and 210 unresolved receptor classifications. 'Confirmed TNBC' means all three selected sample fields are Negative; 51 of those 320 have positive-coded patient-level ER-IHC, so clinical confirmation is not established. The strict cross-assay concordance sensitivity retains 233, without treating SNP6 as a substitute HER2 assay.

18 atomic archival mappings across 6 trial records produce 45,162 assessments and 15,054 patient-trial pairs; 14,933 pairs contain at least one supported observed subpredicate. These are scope-limited components, not complete protocol labels. Complete-reference benchmarking includes 1,466 patients: 445 development, 1,021 evaluation and 2,042 evaluation patient-proxy-trial pairs. Of the 1,021 evaluation patients, 154 meet the TNBC source rule. The other 1,043 original patients are retained in the audit but excluded from the four-field complete-case experiment; this can introduce selection bias.

## Executed experiments

507,990 per-scenario-policy metric rows and 1,057 fitted policies were produced. Exact retrieval: 1,021 patients, three seeds, four masking rates and admissible budgets 1–4, with nine methods. The modeled observation-error study uses 256 hash-selected evaluation patients, three seeds, seven reliability/dependence settings, four budgets and ten methods including interval certification. Cost sensitivity uses 128 patients and assumed [1,2,1,2] costs. A six-item experiment is infeasible; cost budget 6 in sensitivity still reveals at most four items.

## Primary exact-source result: all four attributes initially hidden, budget 2

| Method | Atomic correct/all | Proxy error/all | Proxy coverage | Cost |
|---|---:|---:|---:|---:|
| cheapest | 0.71866 | 0.03477 | 0.88981 | 2.000 |
| conservative | 0.50000 | 0.00000 | 0.77963 | 2.000 |
| eig | 0.54163 | 0.00343 | 0.92116 | 1.228 |
| lookahead1 | 0.73457 | 0.00343 | 0.92116 | 2.000 |
| lookahead2 | 0.73457 | 0.00343 | 0.92116 | 2.000 |
| random | 0.69858 | 0.04685 | 0.86990 | 2.000 |
| triallens_nominal | 0.73457 | 0.00343 | 0.92116 | 2.000 |
| uncertainty | 0.84868 | 0.03477 | 0.88981 | 2.000 |
| unconstrained | 0.73457 | 0.00343 | 0.92116 | 2.000 |

Nominal constrained TrialLens, unconstrained original planning, one-step lookahead and two-step lookahead have identical primary budget-2 metrics. Adding the risk constraint did not establish an incremental advantage in this comparison. Highest-uncertainty review has higher atomic correct/all agreement (84.87%) than the planner (73.46%), while answering fewer proxy tasks. The objectives and coverage must be considered together.

Patient-paired contrasts below average repeated seeds and both correlated proxy tasks within patient (n=1,021). Intervals are marginal 95% bootstrap intervals; Holm p values correct the full primary family.

triallens_nominal_minus_cheapest, utility: +0.19481, 95% CI [+0.14623, +0.24799], adjusted p=0.01600.

triallens_nominal_minus_random, utility: +0.26730, 95% CI [+0.22858, +0.30775], adjusted p=0.01600.

triallens_nominal_minus_unconstrained, utility: +0.00000, 95% CI [+0.00000, +0.00000], adjusted p=1.00000.

triallens_nominal_minus_cheapest, proxy_error: -0.03134, 95% CI [-0.04016, -0.02351], adjusted p=0.01600.

triallens_nominal_minus_random, proxy_error: -0.04342, 95% CI [-0.05191, -0.03526], adjusted p=0.01600.

triallens_nominal_minus_unconstrained, proxy_error: +0.00000, 95% CI [+0.00000, +0.00000], adjusted p=1.00000.

triallens_nominal_minus_cheapest, proxy_coverage: +0.03134, 95% CI [+0.02351, +0.04016], adjusted p=0.01600.

triallens_nominal_minus_random, proxy_coverage: +0.05126, 95% CI [+0.04032, +0.06236], adjusted p=0.01600.

triallens_nominal_minus_unconstrained, proxy_coverage: +0.00000, 95% CI [+0.00000, +0.00000], adjusted p=1.00000.

These comparisons support better rule-proxy error/coverage than random or fixed field-order review in this selected benchmark. They do not establish clinical matching benefit or superiority over the simpler lookahead/unconstrained methods. The two targets share receptors and are not an independent sample of trials.

## TNBC stratum

For the 154 confirmed-by-source-rule evaluation patients at budget 2, nominal TrialLens has zero observed proxy errors and 50% proxy coverage; random review has 20.67% proxy error and 58.55% coverage. Unconstrained, one/two-step lookahead, cheapest and highest-uncertainty methods also have zero observed error and 50% coverage. Thus the TNBC subset does not show a unique benefit from the risk constraint. Zero observed errors in a selected finite sample is not a clinical zero-error guarantee. Exploratory patient-bootstrap comparisons are in stratified_statistics.csv.

## Declared observation-channel study

| Method | Atomic correct/all | Proxy error/all | Proxy coverage | Cost |
|---|---:|---:|---:|---:|
| cheapest | 0.67773 | 0.00521 | 0.78255 | 2.000 |
| conservative | 0.47461 | 0.00521 | 0.78255 | 2.000 |
| eig | 0.57194 | 0.00651 | 0.78646 | 2.000 |
| lookahead1 | 0.69434 | 0.02083 | 0.91146 | 2.000 |
| lookahead2 | 0.69434 | 0.02083 | 0.91146 | 2.000 |
| random | 0.65462 | 0.04036 | 0.82096 | 2.000 |
| triallens_certified | 0.69434 | 0.02083 | 0.91146 | 2.000 |
| triallens_nominal | 0.69434 | 0.02083 | 0.91146 | 2.000 |
| uncertainty | 0.81185 | 0.00521 | 0.78255 | 2.000 |
| unconstrained | 0.69434 | 0.02083 | 0.91146 | 2.000 |

At budget 2, nominal, unconstrained and interval-certified planning all have 2.08% observed proxy error and 91.15% coverage in the 256-patient noisy-observation subset. No extra benefit from interval certification is demonstrated at this budget. Its role is to enclose modeled error over a declared interval, not automatically improve predictions.

All 4 interval-certified fitted policies satisfy their original rational upper-bound checks (epsilon=0.05 with tolerance 1e-7); solver gaps and exact upper enclosures are in fitted_policy_diagnostics.csv. The objective uses the nominal factor-1 law, while the certificate checks [0.65,1.8]. These are guarantees under the developmental joint prior and assumed observation process only.

At severe reliability factor 2.5, observed budget-2 error rises to 5.47% for nominal, unconstrained and interval-certified methods. That factor is outside the certificate interval. Source-dependence and missingness sensitivities are saved separately. Evaluation-sample error and a certificate under a fitted prior have different denominators/population assumptions; an observed exceedance does not by itself invalidate the in-model proof. No clinical safety claim follows.

## What remains unvalidated

There are no independent clinician-adjudicated eligibility labels, prospective screening dates, current assay verification, actual report review actions, measured review costs or validated clinical observation probabilities. Source-level receptor discordance is unresolved, not repaired. Complete-case restriction, historical cohort selection, only two proxy graphs, and a smoothed prior limit generalization. The positive result is narrower than end-to-end clinical trial matching; the incremental contribution of constraints/certification over simpler exact/lookahead planning is not demonstrated by the primary comparison.

## Validation and corrections

214 tests passed in the final targeted suite, covering source identity and masking, mapping spans, three-state rule handling, patient-disjoint prior estimation, conditional Bayesian updates, original solver/rational risk agreement, budgets/costs, deterministic behavior, statistics, independent finite-world metrics and saved trace recalculation. Existing clinical criterion/five-state tests were also executed.

No experiment configuration failed. A random-order forecast accounting issue was found and corrected: observed outcomes and selections were already correct, but the modeled forecast initially used canonical order. The original output is retained in results/initial_run; final forecasts integrate each actual seeded order. Tests verify order-specific forecasts.

## Outputs and next priorities

Every displayed number traces to saved CSV/JSON results. Ten figures are exported in PDF/PNG with input provenance, plus LaTeX and CSV tables. Raw patient identities and reveal traces remain in ignored local data files.

Next, independently adjudicate the assay discrepancies and archive-to-trial semantic mappings, obtain dated same-person reports and screening labels, and predeclare a larger trial/graph design. Validate the observation model on disjoint patients before testing real clinical error or claiming a constraint-related benefit. The present work is a reproducible real-attribute proxy benchmark with an explicitly model-based planner analysis.