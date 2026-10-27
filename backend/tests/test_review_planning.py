import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import ValidationError

from backend.app.prioritization_models import ExperimentConfig, STRATEGIES
from backend.app.prioritization import select_reviews
from backend.app.review_planning import ReviewPlanner, legacy_compatible, scenario_distribution
from backend.app.review_planning_models import ReviewPlanningModel, UnsupportedReviewModel
from backend.app.synthetic_review_research import research_cases


@pytest.fixture
def cases():
    return {case.case_id: case for case in research_cases()}


def test_exact_reference_beats_ratio_greedy_and_enumerates_empty_plan(cases):
    planner = ReviewPlanner(cases["ratio_trap"].model)
    exact = planner.exact(6)
    assert exact["selected_items"] == ["b", "c"]
    assert exact["spent"] == 6
    assert exact["expected_utility"] == 8
    greedy = select_reviews(planner.model.portfolio, "expected_per_cost", ExperimentConfig(budget=6))
    assert greedy["expected_reduction"] == 7
    assert exact["expected_utility"] - planner.value(greedy["selected_items"])["expected_utility"] == 1
    assert planner.exact(0)["selected_items"] == []
    assert planner.exact(0)["expected_utility"] == 0


def test_exact_prerequisites_and_heterogeneous_cost_budget(cases):
    planner = ReviewPlanner(cases["synthetic-prerequisite-records"].model)
    sets = list(planner.feasible_sets(2))
    assert ("linked-record",) not in sets
    assert ("linked-record", "retrieve-record") in sets
    assert planner.exact(2)["selected_items"] == ["retrieve-record", "linked-record"]
    assert planner.exact(1)["expected_reduction"] == 0
    with pytest.raises(ValueError, match="prerequisite"):
        planner.value(["linked-record"])
    with pytest.raises(ValueError, match="Repeated"):
        planner.value(["retrieve-record", "retrieve-record"])
    with pytest.raises(ValueError, match="Negative"):
        planner.exact(-1)


def test_unlinked_complementarity_remains_a_greedy_failure(cases):
    planner = ReviewPlanner(cases["complementarity"].model)
    assert planner.value(["a"])["expected_reduction"] == 0
    assert planner.value(["b"])["expected_reduction"] == 0
    assert planner.exact(2)["expected_reduction"] == 1
    assert planner.greedy(2)["expected_reduction"] == Fraction(2, 5)


@pytest.mark.parametrize("outcome,next_action", [("positive", "b"), ("negative", "c")])
def test_adaptive_reveals_one_result_before_replanning(cases, outcome, next_action):
    case = cases["adaptive_branch"]
    planner = ReviewPlanner(case.model)
    original = case.model.model_dump_json()
    calls = []

    def reveal(identifier):
        calls.append(identifier)
        if len(calls) == 1:
            assert identifier == "a"
            return outcome
        assert identifier == next_action
        return "positive"

    result = planner.simulate(2, reveal)
    assert calls == ["a", next_action]
    assert result["spent"] == 2
    assert result["trace"][0]["forecast_before_observation"]["selected_items"] == ["a", "c"]
    assert case.model.model_dump_json() == original
    assert planner.exact(2)["expected_reduction"] == Fraction(11, 10)
    assert planner.adaptive_value(2)["expected_reduction"] == Fraction(13, 10)


def test_risk_objective_uses_assumptions_and_can_abstain(cases):
    planner = ReviewPlanner(cases["noisy_review"].model)
    assert planner.exact(2)["selected_items"] == ["cheap"]
    assert planner.exact(2)["expected_reduction"] == 1
    assert planner.value(["cheap"], risk_weight=3)["expected_error_bound"] == Fraction(2, 5)
    assert planner.value(["cheap"], risk_weight=3)["expected_utility"] == Fraction(-1, 5)
    safer = planner.exact(2, risk_weight=3)
    assert safer["selected_items"] == ["reliable"]
    assert safer["expected_utility"] == Fraction(97, 100)
    assert planner.exact(1, risk_weight=3)["selected_items"] == []


def test_wrong_resolution_regression_and_hidden_truth_separation(cases):
    case = cases["noisy_review"]
    planner = ReviewPlanner(case.model)
    world = next(world for world in case.evaluation_worlds
                 if world.outcomes["cheap"] == "negative" and world.truth["noisy"] == "constraints_consistent")
    forecast = planner.exact(2)
    result = planner.assessment({"cheap": "negative"})
    assert planner.assessment({}).uncertainty - result.uncertainty == 1
    assert result.decisions[0].decision == "observed_blocker"
    assert world.truth["noisy"] == "constraints_consistent"
    world.truth["noisy"] = "observed_blocker"
    assert planner.exact(2) == forecast
    assert planner.exact(2, risk_weight=3)["selected_items"] == ["reliable"]


def test_misspecified_reliability_does_not_silently_use_actual_truth(cases):
    planner = ReviewPlanner(cases["misspecified_reliability"].model)
    assert planner.exact(2, risk_weight=3)["selected_items"] == ["cheap"]
    assert planner.value(["cheap"])["expected_error_bound"] == Fraction(1, 100)


def test_synthetic_reliability_reference_and_deliberate_misspecification(cases):
    case = cases["noisy_review"]
    for reported in ("positive", "negative"):
        selected = [world for world in case.evaluation_worlds if world.outcomes["cheap"] == reported]
        mass = sum((world.probability for world in selected), Fraction())
        errors = sum((world.probability for world in selected
                      if (reported == "positive") != (world.truth["noisy"] == "constraints_consistent")), Fraction())
        assert errors / mass == Fraction(2, 5)
        assert Fraction(case.model.reliability.conditional_error_probabilities["cheap"][reported]) == errors / mass
    assert ReviewPlanner(case.model).value(["cheap"])["expected_error_bound"] == Fraction(2, 5)
    misspecified = ReviewPlanner(cases["misspecified_reliability"].model)
    assert misspecified.value(["cheap"])["expected_error_bound"] < Fraction(2, 5)


def test_correlated_duplicate_reviews_require_joint_distribution(cases):
    model = cases["correlated_duplicates"].model
    planner = ReviewPlanner(model)
    assert legacy_compatible(model) is False
    assert len(planner.distribution) == 2
    assert planner.conditional({"first": "positive"})[0][1]["copy"] == "positive"
    assert planner.value(["copy", "first"])["expected_reduction"] == 1
    assert planner.exact(2)["spent"] == 1
    with pytest.raises(UnsupportedReviewModel, match="zero_model_probability"):
        planner.conditional({"first": "positive", "copy": "negative"})
    with pytest.raises(UnsupportedReviewModel, match="missing_joint"):
        ReviewPlanner(cases["overlap_without_joint"].model)
    independent = model.model_copy(deep=True)
    independent.dependence_mode = "independent_disjoint"
    independent.joint_scenarios = None
    with pytest.raises(UnsupportedReviewModel, match="overlap"):
        ReviewPlanner(independent)


def test_risk_union_bound_does_not_assume_independent_errors(cases):
    model = cases["correlated_duplicates"].model.model_copy(deep=True)
    for labels in model.reliability.conditional_error_probabilities.values():
        for label in labels:
            labels[label] = Fraction(7, 10)
    planner = ReviewPlanner(model)
    assert planner.value(["copy", "first"])["expected_error_bound"] == 1


def test_models_reject_missing_rates_and_inconsistent_joint_marginals(cases):
    payload = cases["noisy_review"].model.model_dump(mode="json")
    payload["joint_scenarios"][0]["probability"] = "0.1"
    payload["joint_scenarios"][1]["probability"] = "0.4"
    with pytest.raises(ValidationError, match="marginal"):
        ReviewPlanningModel.model_validate(payload)
    payload = cases["noisy_review"].model.model_dump(mode="json")
    del payload["reliability"]["conditional_error_probabilities"]["cheap"]["negative"]
    with pytest.raises(ValidationError, match="every review outcome"):
        ReviewPlanningModel.model_validate(payload)
    model = cases["noisy_review"].model.model_copy(deep=True)
    model.reliability = None
    planner = ReviewPlanner(model)
    assert planner.exact(2)["expected_reduction"] == 1
    with pytest.raises(UnsupportedReviewModel, match="reliability"):
        planner.exact(2, risk_weight=3)


def test_exact_limits_are_explicit(cases):
    model = cases["ratio_trap"].model.model_copy(deep=True)
    model.max_actions = 2
    with pytest.raises(UnsupportedReviewModel, match="action_limit"):
        scenario_distribution(model)
    model.max_actions, model.max_scenarios = 3, 2
    with pytest.raises(UnsupportedReviewModel, match="scenario_limit"):
        scenario_distribution(model)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_legacy_expected_values_match_exact_joint_evaluator(cases, strategy):
    planner = ReviewPlanner(cases["ratio_trap"].model)
    assert legacy_compatible(planner.model)
    selected = select_reviews(planner.model.portfolio, strategy, ExperimentConfig(seed=7, budget="6"))
    forecast = planner.value(selected["selected_items"])
    assert selected["expected_reduction"] == forecast["expected_reduction"]
    result = {**selected, **forecast}
    assert result["expected_utility"] <= planner.exact(6)["expected_utility"]
    assert result["spent"] <= 6


def test_research_artifacts_reproducibility_and_gap_labels(monkeypatch):
    from backend import research_prioritization_experiment as experiment
    root = Path(__file__).resolve().parents[2]
    with TemporaryDirectory(dir=root / "cache") as directory:
        monkeypatch.setattr(experiment, "RESULTS_DIR", Path(directory))
        first = experiment.run_research([7])
        before = (first / "results.json").read_bytes()
        second = experiment.run_research([7])
        assert first != second
        assert before == (second / "results.json").read_bytes() == (first / "results.json").read_bytes()
        rows = json.loads(before)
        assert all(row["optimality_gap"] is None for row in rows if row["policy_type"] == "adaptive")
        assert all(Fraction(row["spent"]) <= Fraction(row["budget"]) for row in rows)
        sizes = {case.case_id: len(case.model.portfolio.trials) for case in research_cases()}
        assert all(row["correct_resolved"] + row["incorrect_resolved"] + row["unresolved"] == sizes[row["case_id"]]
                   for row in rows)
        failures = json.loads((first / "failures.json").read_text())
        assert any(item["reason"] == "missing_joint_distribution" for item in failures)
        assert json.loads((first / "manifest.json").read_text())["preserved_previous_files"] is True
