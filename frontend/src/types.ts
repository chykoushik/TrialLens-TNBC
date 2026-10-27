export type State = 'satisfied' | 'violated' | 'unknown' | 'temporal' | 'conflict'
export type Evidence = { evidence_id: string; clinical_attribute: string; value: string | null; units: string | null; assay: string | null; observation_date: string | null; specimen_context?: string | null; scoring_method?: string | null; availability?: 'recorded' | 'unknown' | 'unavailable' | null; source: string; provenance: { record_id: string; reference: string } }
export type Criterion = { criterion_id: string; criterion_type: 'inclusion' | 'exclusion' | null; original_text: string; source_url: string | null; cohort: string | null; logical_operator: string | null; biomarker: string | null; assay: string | null; temporal_constraint: string | null; comparator?: string | null; threshold?: string | null; unit?: string | null; nct_id?: string | null }
export type Assessed = { criterion_id: string; criterion: Criterion; state: State; explanation: string | null; reason_code: string; evidence_ids: string[]; dependencies: Assessed[] }
export type Case = { case_id: string; title?: string; description?: string; trial_count: number; review_count: number; budgets: string[]; unsupported: string | null }
export type Review = { item_id: string; cost: string; depends_on: string[]; description: string; existing_record: { record_id: string; reference: string }; probability_basis: string | null; targets?: { trial_id: string; criterion_id: string }[]; outcomes: { additions?: Evidence[]; outcome_id: string; probability: string | null; description: string }[] }
export type RankingRow = { item_id: string; bundle: string[]; cost: string; score?: string | null; status?: string; delta?: string; delta_U?: string; uncertainty_before?: string; expected_uncertainty_after?: string }
export type PlanningStep = { ranking: RankingRow[]; selected: string | null }
export type Evaluation = {
  demo_fixture_sha256?: string
  case_title?: string; case_description?: string; display_labels?: Record<string, string>; protocol_titles?: Record<string, string>
  patient: { patient_id: string; evidence: Evidence[] }
  assessment: { uncertainty: string; decisions: { trial_id: string; decision: string; assessment: { context: { as_of: string }; assessments: Assessed[]; criteria_set: { source_snapshot: string | null; is_synthetic?: boolean | null; nct_id?: string | null } } }[] }
  candidates: Review[]; assumptions: string[]; cost_unit: string
  trials: { bindings: { clinical_attribute: string | null; criterion: Criterion; temporal_rule?: { kind: 'freshness' | 'elapsed'; max_age_days: string | null; source_text: string } | null }[] }[]
  plan: { selected_items: string[]; spent: string; expected_reduction: string; expected_utility: string; expected_error_bound: string | null; risk_weight: string; expected_final_uncertainty?: string; feasible_sets_evaluated?: number; trace?: PlanningStep[]; steps?: PlanningStep[] }
  spent: string; remaining_budget: string; plan_scope: string; next_review: string | null
  reliability: { assumption: string; conditional_error_probabilities: Record<string, Record<string, string>> } | null
  dependence_groups: { item_ids: string[]; relationship: string; assumption: string }[]
}
export type Trial = { nct_id: string | null; title: string | null; recruitment_status: string | null; eligibility_criteria: string | null; source_url: string | null; conditions: string[]; snapshot: string; snapshot_sha256?: string; snapshot_count?: number; retrieved_at: string | null; is_synthetic: boolean | null }
