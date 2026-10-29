# Offline prioritization sensitivity

11480 realized method/world rows; 1106 forecasts; 247 skipped/unsupported records.
World seeds: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]. Action cap: 4. All instances are constructed synthetic examples.

Paired effects are left minus right within a fixed model/budget, not across clinical cases. Intervals describe conditional Monte Carlo seed variation only.
Correctness fractions use protocol counts, not weighted uncertainty. Different lambda values have different objectives; gaps use the same lambda only. Adaptive gaps are undefined.

| Instance / budget | Comparison | Incorrect fraction difference | Conditional 95% bootstrap interval |
| --- | --- | --- | --- |
| adaptive_branch / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| adaptive_branch / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| complementarity / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| complementarity / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| correlated_duplicates / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| correlated_duplicates / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| cost-multiplier-0.5 / 3 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| cost-multiplier-0.5 / 6 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| cost-multiplier-2 / 3 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| cost-multiplier-2 / 6 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| error-0.1-assumed-0.01 / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| error-0.1-assumed-0.01 / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| error-0.1-assumed-0.01 / 3 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| error-0.1-assumed-0.4 / 1 | risk_exact − exact_nonadaptive | -0.0500 | [-0.15, 0.0] |
| error-0.1-assumed-0.4 / 2 | risk_exact − exact_nonadaptive | -0.0500 | [-0.2, 0.0] |
| error-0.1-assumed-0.4 / 3 | risk_exact − exact_nonadaptive | -0.0500 | [-0.15, 0.0] |
| error-0.1-assumed-0.7 / 1 | risk_exact − exact_nonadaptive | -0.0500 | [-0.15, 0.0] |
| error-0.1-assumed-0.7 / 2 | risk_exact − exact_nonadaptive | -0.0500 | [-0.15, 0.0] |
| error-0.1-assumed-0.7 / 3 | risk_exact − exact_nonadaptive | -0.0500 | [-0.15, 0.0] |
| error-0.4-assumed-0.01 / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| error-0.4-assumed-0.01 / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| error-0.4-assumed-0.01 / 3 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| error-0.4-assumed-0.4 / 1 | risk_exact − exact_nonadaptive | -0.3500 | [-0.55, -0.15] |
| error-0.4-assumed-0.4 / 2 | risk_exact − exact_nonadaptive | -0.3500 | [-0.55, -0.15] |
| error-0.4-assumed-0.4 / 3 | risk_exact − exact_nonadaptive | -0.3500 | [-0.6, -0.15] |
| error-0.4-assumed-0.7 / 1 | risk_exact − exact_nonadaptive | -0.3500 | [-0.55, -0.15] |
| error-0.4-assumed-0.7 / 2 | risk_exact − exact_nonadaptive | -0.3500 | [-0.55, -0.15] |
| error-0.4-assumed-0.7 / 3 | risk_exact − exact_nonadaptive | -0.3500 | [-0.55, -0.15] |
| error-0.7-assumed-0.01 / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| error-0.7-assumed-0.01 / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| error-0.7-assumed-0.01 / 3 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| error-0.7-assumed-0.4 / 1 | risk_exact − exact_nonadaptive | -0.7500 | [-0.95, -0.55] |
| error-0.7-assumed-0.4 / 2 | risk_exact − exact_nonadaptive | -0.7500 | [-0.95, -0.55] |
| error-0.7-assumed-0.4 / 3 | risk_exact − exact_nonadaptive | -0.7500 | [-0.95, -0.55] |
| error-0.7-assumed-0.7 / 1 | risk_exact − exact_nonadaptive | -0.7500 | [-0.95, -0.55] |
| error-0.7-assumed-0.7 / 2 | risk_exact − exact_nonadaptive | -0.7500 | [-0.9, -0.55] |
| error-0.7-assumed-0.7 / 3 | risk_exact − exact_nonadaptive | -0.7500 | [-0.95, -0.55] |
| misspecified_reliability / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| misspecified_reliability / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| noisy-lambda-zero / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| noisy-lambda-zero / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| noisy_review / 1 | risk_exact − exact_nonadaptive | -0.3000 | [-0.5, -0.1] |
| noisy_review / 2 | risk_exact − exact_nonadaptive | -0.3000 | [-0.5, -0.1] |
| prerequisite-removed / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| prerequisite-removed / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| ratio_trap / 3 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| ratio_trap / 6 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r2-t2-uniform / 0 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r2-t2-uniform / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r2-t2-uniform / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r3-t6-heterogeneous / 0 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r3-t6-heterogeneous / 3 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r3-t6-heterogeneous / 6 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r4-t4-uniform / 0 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r4-t4-uniform / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r4-t4-uniform / 4 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r4-t8-heterogeneous / 0 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r4-t8-heterogeneous / 3.5 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| scale-r4-t8-heterogeneous / 7 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| synthetic-breadth-versus-resolution / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| synthetic-breadth-versus-resolution / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| synthetic-prerequisite-records / 1 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |
| synthetic-prerequisite-records / 2 | risk_exact − exact_nonadaptive | 0.0000 | [0.0, 0.0] |

No clinical benefit, calibration, novelty or general superiority is established. Zero-width intervals can arise from deterministic outcomes and do not prove general certainty.
No inferential pooling, p-values or multiple-comparison significance claims are made. Ratios exclude zero-cost histories and are null there.
Legacy methods are unsupported on nonfactorizing joint models and retain forced spending. All methods within a supported cell share candidates, costs, prerequisites and reported-outcome distributions.
No large-instance performance guarantee or hard timeout benchmark is provided. See failures.json for explicit skips, paired_effects.json for all effects, and forecasts.json for objective values/gaps/timing.
