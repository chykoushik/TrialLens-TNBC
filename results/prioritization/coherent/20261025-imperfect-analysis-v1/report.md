# Imperfect-report verification and revised findings

Reuses `results/prioritization/coherent/20261025-imperfect-v1` without any new experimental worlds or forecast calculations.

## Internal coherence

All 32 actual/assumed configuration pairs normalize exactly; all shared-fact pair inequalities hold. All accurately specified history-safe bounds cover actual conditional errors. Actual and assumed distributions are independently parameterized coherent laws; estimates need not describe the actual world.
14 misspecified history-safe configurations fail actual-model conditional coverage. 6 single-report-rate ablations fail their own assumed conditional-history bounds. See validity.json; these are diagnostic assumption failures, not repaired probabilities.

## Revised findings

| Scenario, budget 2 | Assumption | Method | Correct | Incorrect | Abstaining | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| shared-truth | optimistic | exact_nonadaptive | 0.700 | 0.300 | 0.000 | 1.000 |
| shared-truth | optimistic | risk_exact | 0.900 | 0.100 | 0.000 | 2.000 |
| shared-truth | accurate | exact_nonadaptive | 0.700 | 0.300 | 0.000 | 1.000 |
| shared-truth | accurate | risk_exact | 0.900 | 0.100 | 0.000 | 2.000 |
| shared-truth | pessimistic | exact_nonadaptive | 0.700 | 0.300 | 0.000 | 1.000 |
| shared-truth | pessimistic | risk_exact | 0.900 | 0.100 | 0.000 | 2.000 |
| shared-source | optimistic | exact_nonadaptive | 0.780 | 0.220 | 0.000 | 1.000 |
| shared-source | optimistic | risk_exact | 0.829 | 0.171 | 0.000 | 2.000 |
| shared-source | accurate | exact_nonadaptive | 0.780 | 0.220 | 0.000 | 1.000 |
| shared-source | accurate | risk_exact | 0.829 | 0.171 | 0.000 | 2.000 |
| shared-source | pessimistic | exact_nonadaptive | 0.780 | 0.220 | 0.000 | 1.000 |
| shared-source | pessimistic | risk_exact | 0.000 | 0.000 | 1.000 | 0.000 |
| imperfect-copy | optimistic | exact_nonadaptive | 0.800 | 0.200 | 0.000 | 1.000 |
| imperfect-copy | optimistic | risk_exact | 0.800 | 0.200 | 0.000 | 1.000 |
| imperfect-copy | accurate | exact_nonadaptive | 0.800 | 0.200 | 0.000 | 1.000 |
| imperfect-copy | accurate | risk_exact | 0.800 | 0.200 | 0.000 | 1.000 |
| imperfect-copy | pessimistic | exact_nonadaptive | 0.800 | 0.200 | 0.000 | 1.000 |
| imperfect-copy | pessimistic | risk_exact | 0.800 | 0.200 | 0.000 | 1.000 |

The imperfect reference does not remove all errors: accurate risk selection in the shared-truth condition yields 0.9 correct and 0.1 incorrect per world at cost 2, versus 0.7/0.3 at cost 1 for ordinary exact uncertainty selection. This is a model-specific accuracy/cost tradeoff, not a clinical benefit or general dominance result.
Pessimistic shared-source assumptions yield complete abstention rather than the accurate assumption's 0.829 correct, 0.171 incorrect at cost 2. Counting fewer incorrect assertions alone would incorrectly reward abstention. The imperfect-copy control stays 0.8 correct/0.2 incorrect: agreement and repeat review do not recover truth.
Optimistic bounds can fail conditional coverage without changing the selected plan. Conversely, pessimistic primitive error multipliers need not increase every conditional bound. Reliability labels refer to primitive assumptions, not a monotone guarantee for decisions.
Shared-source and common-shock mechanisms have identical authored joint laws and produce matching outcomes. This is an identifiability negative control, not evidence that modeled dependencies match clinical phenomena. There is no isolated claim of dependency-aware superiority.
All 56 two-report same-lambda adaptive comparisons had zero objective gap. These small single-fact/disjoint-fact examples do not establish adaptive superiority or discrimination between replanning and an optimal adaptive policy.

## Paired inference and computational limits

There are 224 distinct family/seed draws (7 authored families x 32 seeds), not 28,160 independent samples. The cost control shares the shared-truth family. Shared-source/common-shock laws are identical illustrative constructions, not independent evidence of a biological effect. No inference pools them as separate independent replicates.
Within each fixed family, truth/report-vector draws are the paired experimental units. All methods, budgets, estimates, duplicated protocols and cost variants are repeated observations. Exact integrated effects have no sampling uncertainty under the specified finite law; 1000-resample paired bootstrap intervals describe Monte Carlo variability only. No p-values, clinical intervals or multiplicity-adjusted superiority claims are made.
contrasts.json adds paired optimistic/accurate, pessimistic/accurate, single-rate/history-safe and equal-cost/original-cost differences with exact effects, descriptive intervals and paired dz. paired.json in the input run contains method contrasts. Random selection conditions on one ranking seed; variability across ranking seeds remains unmeasured.
Maximum cold forecast time: 0.031952s; maximum subsequent integrated evaluation: 0.014751s. Evaluation reuses caches and timings are not a matched speed comparison. No hard timeout was imposed. There are 784 explicit independence-incompatible skipped cells, zero recorded runtime failures, and no infeasible output plans.
The limited authored study varies primitive errors, dependence mechanisms, costs, budgets and portfolio size; it is not a powered factorial design. Enlarged portfolios repeat fact-linked protocols rather than introduce independent truths. Scaling beyond four records and two-report DP, richer calibrated models, asymmetric errors, prerequisites, temporal-report error processes and independently calibrated clinical parameters remain open.

## Remaining milestone

The new finite generative model is internally coherent, including imperfect reports and dependence. Decision-time estimates can intentionally be wrong; the unsafe marginal-rate ablation remains explicitly assumption-limited. Original historical settings remain untouched and invalid as joint error bounds.
Additional offline experiments are worthwhile only for a specific gap: informative asymmetric priors/error channels, heterogeneous source quality with identifiable structure, independent random-ranking repetitions, and branching multi-criterion scenarios able to distinguish adaptive policies. More seeds on these same simple models would reduce simulation error without establishing clinical validity or algorithmic novelty.

## Reproduction

Run `.\.venv\Scripts\python.exe -B -m backend.analyze_coherent_reliability --dataset results/prioritization/coherent/20261025-imperfect-v1 --output results/prioritization/coherent/<new-analysis-version>` from the project root. Use docs/coherent_reliability.md for the experiment command. Both commands reject existing output versions. No API or credentials are used.
