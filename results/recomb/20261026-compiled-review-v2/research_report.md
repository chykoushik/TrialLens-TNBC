# Consolidated final computational research report

Public scientific excerpt; operational development-status notes omitted. Numerical results, scientific limitations and citations are retained. Original source SHA-256: `432ab479e3778b70ddac2f5cab2c4b665d236a9997e83fcc928aa8c794146aca`.

**Verified outcome:** an exact compiled-belief backend removes the previous explicit truth-assignment sum for the specified source model and materially extends feasible inference/planning instances. The factorization, decision diagrams, weighted counting and constrained-policy procedure are established techniques; an original general computational method has not been established.

## Implemented improvement

The new isolated module is research/compiled_review_v1. It replaces the old 2^n truth sum with a finite mixture of product distributions and reduced ordered decision diagrams for protocol logic. It supports repeated Boolean operands, multiple known source groups, and a third independent unavailable-report outcome. Both exact world enumeration and the unchanged earlier analytical class remain executable comparators. Production code and historical algorithms/results are unchanged.

For b reviewed reports, the pre-merge component bound is C(h) <= (n+2) product_{g:k_g>=2}(k_g+2) <= (n+2)2^b. With one active group, C(h) <= (n+2)(b+2). This is a model-specific consequence of latent-interval conditioning, not a claimed new general tractability theorem. Diagrams, source-component products, protocol classes and adaptive histories retain exponential worst cases.

What is avoided: full 2^n R^m worlds, the prior analytical 2^n truth enumeration, and independent-protocol approximations that mishandle repeated/shared variables. What is not avoided: general decision-diagram compilation, budget-feasible adaptive history growth, finite-model dependence assumptions, modelwise pricing and master LP iterations. Exact substitution preserves decision objectives; backend speedup is not predictive-accuracy improvement.

## Benchmark evidence

252 isolated serial runs, three repetitions per comparison: 159 successful, 84 explicitly unsupported, 9 timed out, zero worker errors. All 96 successful matched reference comparisons agree within 5.22e-15. Full statuses are preserved; censored references receive no fabricated speedup or memory estimate.

| Criteria | Reports | Groups | Outcomes | Task | Backend | Median seconds | Peak RSS MiB |
|---:|---:|---:|---:|---|---|---:|---:|
| 3 | 4 | 1 | 2 | queries | legacy | 0.00032 | 16.66 |
| 3 | 4 | 1 | 2 | queries | compiled | 0.00206 | 17.05 |
| 12 | 10 | 1 | 2 | queries | legacy | 0.22162 | 18.87 |
| 12 | 10 | 1 | 2 | queries | compiled | 0.00857 | 17.02 |
| 24 | 12 | 1 | 2 | solve | compiled | 5.19366 | 33.22 |
| 64 | 16 | 4 | 3 | queries | compiled | 0.09357 | 18.32 |

Query times cover 40 identical budget-feasible histories. The 64-criterion figure is posterior inference, not full adaptive planning. The largest certified criterion count in this benchmark is 24. Process peak RSS includes the interpreter/imported code. Small cases favor the old analytical backend. Three medians/ranges are local hardware measurements, not universal scaling guarantees.

## New adaptive-planning evaluation

48 fresh held-out instances, six families and two budgets give 96 matched conditions; 24 separate OOD instances give 48 more. All 72 worker cases completed. Baselines include VOI/cost, information gain, EC2 adaptation, one/two-step planning, exact adaptive/fixed selection, replanning, rectangular robust planning and fixed-penalty controls. Their strongest feasible comparison is an optimized mixture over the entire baseline library at the same modelwise error cap.

| Method | Utility | Protocol error fraction | Correct protocols | Abstention | Cost | Violating cells |
|---|---:|---:|---:|---:|---:|---:|
| raw_exact_dp | 0.086847 | 0.112188 | 1.075470 | 0.700154 | 1.829541 | 77/96 |
| safe_exact_dp | -0.032634 | 0.069073 | 0.683494 | 1.178360 | 1.195925 | 0/96 |
| safe_robust_dp | 0.001291 | 0.067000 | 0.716741 | 1.149259 | 1.166551 | 0/96 |
| library_hull | 0.055524 | 0.068199 | 0.829248 | 1.034354 | 1.820773 | 0/96 |
| multi_cg | 0.060589 | 0.068543 | 0.839343 | 1.023572 | 1.843302 | 0/96 |
| depth2_cg | 0.060843 | 0.068413 | 0.838191 | 1.024983 | 1.826297 | 0/96 |
| nominal_cg | 0.072441 | 0.085365 | 0.933902 | 0.895368 | 1.844503 | 51/96 |
| report_independent_cg | 0.048386 | 0.070402 | 0.834510 | 1.024686 | 1.855077 | 15/96 |

Exact constrained planning minus the feasible hull improves utility by 0.005065, paired synthetic-seed bootstrap 95% interval [0.003057,0.007053], with 48 wins, 37 ties and 11 losses. Correct protocol counts change by 0.010095, incorrect counts by 0.000687, abstention by -0.010782, and spending by 0.022529. This is not dominance in correctness, errors or cost.

The exact method has no consistent actual-utility advantage over depth-two pricing: mean difference -0.000254, interval includes zero. Exactness supplies a nominal numerical gap, not immunity to misspecification. Correct-law constrained regret remains about .027743. The eight synthetic seed bundles, bootstrap assumptions and six-contrast Holm adjustment are explicit; no clinical statistical interpretation is made.

Attribution is separated. Matched backend comparisons show numerical objective preservation. Planning-depth comparisons change the pricing algorithm. Nominal-only and report-independent comparisons change reliability constraints/assumptions and decoding. Report independence preserves truth dependence but changes both interpretation and selection, so it is not a pure selection ablation. Historical factorial results are reused, not pooled.

There are zero primary exact-policy expected-risk violations under the finite set containing actual P by construction. Nominal-only planning violates the cap in 51/96 cells; removing conditional report dependence produces 15/96. Outside the assumed reliability set, the new method fails in 46/48 cells; the conservative repaired robust baseline fails in 34/48 and has higher mean utility. No clinical safety or learned calibration guarantee follows.

## Biological evidence and unavoidable human work

The five saved registry sections and three saved extraction attempts remain unchanged. Existing derived exact anchors locate 24 quotations, but the unchanged validator still rejects the whole output with 54 errors. New source-only packets contain 138 tasks for each of two unassigned reviewer roles plus a separate adjudication queue. All new judgment slots are unreviewed. Existing review flags are audited separately; no independently adjudicated gold is established and no clinical accuracy is computed.

The indispensable external requirement is qualified independent human annotation/adjudication and appropriate real reliability/cost evidence. No human judgment can be supplied by further offline computation.

## Novelty and submission assessment

The targeted primary-source comparison covers Bryant decision diagrams, Boutilier/Poole and Hansen/Feng factored POMDPs, Chavira/Darwiche weighted model counting, Walraven/Spaan constrained policy-column generation, static multi-environment POMDPs, and noisy evidence acquisition. A model-specific implementation and derived component bound are verified; original general factorization, recurrence, planning procedure and clinical validation remain unestablished. This does not meet a defensible claim of a strong new RECOMB method. The official scope emphasizes substantial computational/methodological advances, and the local manuscript states that boundary candidly.

## Complete manuscript and exact artifact map

- manuscript.pdf: complete ten-page main draft, including results, figures, limitations and references; manuscript.html: editable source.
- supplement.pdf: separate eight-page supporting material with proofs, counterexamples, benchmark accounting, statistics and human protocol; supplement.html: editable source.
- abstract.md; formulation_and_proofs.md; formulation.tex; novelty_assessment.md; references.json/references.bib; citation_check.json.
- benchmark.csv/benchmark_summary.csv, numerical_fidelity.csv, benchmark_checks.json, hardware.json and jobs/: all exact inputs/results/censoring statuses.
- decision.csv/decision_means.csv, paired_effects.csv, statistics.json, family_effects.csv, failures.csv and decision_cases.json.
- development.csv, ordering_counterexample.csv and development_decision.json: intermediate versions/negative controls.
- paper_runtime.svg, paper_memory.svg, paper_decision.svg: full-width vector figures with effective label font >=10 points; decision_table.tex and benchmark_table.tex: LaTeX tables.
- adjudication/: source-only reviewer packets, empty adjudication tasks, existing-label audit, source texts and protocol.
- reproducibility.md, final_verification.json, tests.xml, executed_source/, artifact_sha256.json and artifact_index.md.

The failed development-only memory-wrapper integration run is retained at ../20261026-compiled-review-v1. It was corrected before the numerical freeze. No result-dependent algorithm tuning occurred after the final freeze. All new numerical results are synthetic.
