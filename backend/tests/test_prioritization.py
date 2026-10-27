import copy
from datetime import timedelta
import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import ValidationError

from backend import prioritization_experiment
from backend.app import portfolio as portfolio_module
from backend.app.assessment_models import EvidenceProvenance
from backend.app.portfolio import apply_outcome, evaluate_portfolio
from backend.app.prioritization import (
    hypothetical_reviews, rank_candidates, sample_outcomes, select_reviews,
)
from backend.app.prioritization_models import (
    EvidenceRetraction, ExperimentConfig, Portfolio, ReviewOutcome, STRATEGIES,
)
from backend.app.synthetic_prioritization import synthetic_portfolios


@pytest.fixture
def portfolios():
    return synthetic_portfolios()


def changed(portfolio, update):
    payload = portfolio.model_dump(mode="json")
    update(payload)
    return Portfolio.model_validate(payload)


def row_for(portfolio, identifier, **config):
    return next(row for row in rank_candidates(portfolio, "expected_per_cost", ExperimentConfig(**config))
                if row["item_id"] == identifier)


def test_uncertainty_counts_protocol_decisions_not_missing_fields(portfolios):
    portfolio, _ = portfolios
    assessment = evaluate_portfolio(portfolio)
    assert assessment.uncertainty == 4
    assert sum(len(item.unresolved_criterion_ids) for item in assessment.decisions) == 7
    assert all(item.decision == "unresolved" for item in assessment.decisions)
    assert all(item.assessment.criteria_set.is_synthetic is True for item in assessment.decisions)


def test_observed_blocker_resolves_decision_despite_missing_fields(portfolios):
    portfolio, _ = portfolios
    patient = hypothetical_reviews(portfolio, {"broad-record": "negative"})
    assessment = evaluate_portfolio(portfolio, patient)
    assert assessment.uncertainty == 1
    blocked = [item for item in assessment.decisions if item.decision == "observed_blocker"]
    assert len(blocked) == 3
    assert all(len(item.unresolved_criterion_ids) == 1 for item in blocked)
    assert all(len(item.blocker_criterion_ids) == 1 for item in blocked)


def test_exclusion_condition_is_not_consistency(portfolios):
    portfolio, _ = portfolios

    def exclusion(payload):
        protocol = payload["trials"][-1]
        protocol["criteria_set"]["criteria"][0]["criterion_type"] = "exclusion"
        protocol["bindings"][0]["criterion"]["criterion_type"] = "exclusion"

    modified = changed(portfolio, exclusion)
    for outcome, expected in (("positive", "observed_blocker"), ("negative", "constraints_consistent")):
        assessment = evaluate_portfolio(modified, hypothetical_reviews(modified, {"decisive-record": outcome}))
        result = next(item for item in assessment.decisions if item.trial_id == "decisive")
        assert result.decision == expected


def test_expected_reduction_formula_and_noop(portfolios):
    portfolio, _ = portfolios
    broad = row_for(portfolio, "broad-record")
    assert broad["uncertainty_before"] == 4
    assert broad["expected_uncertainty_after"] == Fraction(77, 20)
    assert broad["delta_U"] == Fraction(3, 20)
    assert sum(trace["probability"] for trace in broad["outcome_traces"]) == 1
    decisive = row_for(portfolio, "decisive-record")
    assert decisive["delta_U"] == 1
    assert decisive["score"] == Fraction(1, 2)
    assert row_for(portfolio, "noop-record")["delta_U"] == 0


def test_heuristics_disagree_with_expected_resolution(portfolios):
    portfolio, _ = portfolios
    config = ExperimentConfig(budget=2)
    assert rank_candidates(portfolio, "expected_per_cost", config)[0]["item_id"] == "decisive-record"
    for strategy in ("affected_trials", "uncertainty_only", "decisiveness_per_cost"):
        assert rank_candidates(portfolio, strategy, config)[0]["item_id"] == "broad-record"
    assert rank_candidates(portfolio, "cost_only", config)[0]["item_id"] == "noop-record"


def test_weights_are_explicit(portfolios):
    portfolio, _ = portfolios
    modified = changed(portfolio, lambda payload: payload["trials"][-1].update(weight="2"))
    assert evaluate_portfolio(modified).uncertainty == 5
    assert row_for(modified, "decisive-record")["delta_U"] == 2


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_common_candidates_costs_budget_and_determinism(portfolios, strategy):
    portfolio, _ = portfolios
    config = ExperimentConfig(seed=19, budget="2")
    original = portfolio.model_dump_json()
    ranking = rank_candidates(portfolio, strategy, config)
    assert {row["item_id"] for row in ranking} == {action.item_id for action in portfolio.candidates}
    assert {row["item_id"]: row["cost"] for row in ranking} == {
        "broad-record": 1, "decisive-record": 2, "noop-record": Fraction(1, 2),
    }
    result = select_reviews(portfolio, strategy, config)
    assert result == select_reviews(portfolio, strategy, config)
    assert result["spent"] <= 2
    assert result["spent"] + result["remaining_budget"] == 2
    assert len(result["selected_items"]) == len(set(result["selected_items"]))
    assert portfolio.model_dump_json() == original
    reordered = changed(portfolio, lambda payload: payload["candidates"].reverse())
    assert [row["item_id"] for row in ranking] == [row["item_id"] for row in rank_candidates(reordered, strategy, config)]


def test_seed_controls_random_ranking_and_shared_outcomes(portfolios):
    portfolio, _ = portfolios
    ranks = {tuple(row["item_id"] for row in rank_candidates(portfolio, "random", ExperimentConfig(seed=seed)))
             for seed in range(10)}
    assert len(ranks) > 1
    assert sample_outcomes(portfolio, 7) == sample_outcomes(portfolio, 7)
    reordered = changed(portfolio, lambda payload: payload["candidates"].reverse())
    assert sample_outcomes(portfolio, 7) == sample_outcomes(reordered, 7)


def test_ties_use_item_identifier(portfolios):
    portfolio, _ = portfolios

    def duplicate(payload):
        action = copy.deepcopy(payload["candidates"][0])
        action["item_id"] = "aaa-tied-review"
        for outcome in action["outcomes"]:
            for addition in outcome["additions"]:
                addition["evidence_id"] = "synthetic-distinct-record"
        payload["candidates"].append(action)

    modified = changed(portfolio, duplicate)
    tied = [row for row in rank_candidates(modified, "expected_per_cost", ExperimentConfig())
            if row["item_id"] in ("aaa-tied-review", "broad-record")]
    assert tied[0]["score"] == tied[1]["score"]
    assert tied[0]["item_id"] == "aaa-tied-review"


def test_dependency_bundles_and_complementarity(portfolios):
    _, portfolio = portfolios
    ranking = rank_candidates(portfolio, "expected_per_cost", ExperimentConfig(budget=2))
    assert ranking[0]["item_id"] == "linked-record"
    assert ranking[0]["bundle"] == ["retrieve-record", "linked-record"]
    assert ranking[0]["cost"] == 2
    assert ranking[0]["delta_U"] == 1
    assert row_for(portfolio, "retrieve-record")["delta_U"] == 0
    result = select_reviews(portfolio, "expected_per_cost", ExperimentConfig(budget=2))
    assert result["selected_items"] == ["retrieve-record", "linked-record"]
    assert result["final_expected_uncertainty"] == 0
    assert row_for(portfolio, "linked-record", budget=1)["status"] == "over_budget"
    with pytest.raises(ValueError, match="prerequisite"):
        hypothetical_reviews(portfolio, {"linked-record": "positive"})


def test_completed_reviews_are_not_paid_twice(portfolios):
    _, portfolio = portfolios
    result = rank_candidates(portfolio, "expected_per_cost", ExperimentConfig(budget=2), {"retrieve-record": "positive"})
    assert len(result) == 1
    assert result[0]["bundle"] == ["linked-record"]
    assert result[0]["cost"] == 1
    assert result[0]["delta_U"] == 1
    with pytest.raises(ValueError, match="exceed budget"):
        rank_candidates(portfolio, "random", ExperimentConfig(budget="0.5"), {"retrieve-record": "positive"})


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_missing_probabilities_excluded_for_every_method(portfolios, strategy):
    _, portfolio = portfolios

    def missing(payload):
        for outcome in payload["candidates"][0]["outcomes"]:
            outcome["probability"] = None

    modified = changed(portfolio, missing)
    rows = rank_candidates(modified, strategy, ExperimentConfig(budget=10))
    assert all(row["status"] == "missing_outcome_probabilities" for row in rows)
    assert select_reviews(modified, strategy, ExperimentConfig(budget=10))["selected_items"] == []


@pytest.mark.parametrize("probabilities", [
    ["0.5", "0.4"], ["-0.1", "1.1"], ["NaN", "1"], ["0.5", None],
])
def test_invalid_distributions_rejected(portfolios, probabilities):
    portfolio, _ = portfolios

    def invalid(payload):
        for outcome, probability in zip(payload["candidates"][0]["outcomes"], probabilities):
            outcome["probability"] = probability

    with pytest.raises(ValidationError):
        changed(portfolio, invalid)


def test_distribution_assumption_cannot_be_omitted(portfolios):
    portfolio, _ = portfolios
    with pytest.raises(ValidationError, match="assumptions"):
        changed(portfolio, lambda payload: payload["candidates"][0].update(probability_basis=None))


@pytest.mark.parametrize("cost", ["0", "-1", "NaN", "Infinity"])
def test_nonpositive_or_invalid_costs_rejected(portfolios, cost):
    portfolio, _ = portfolios
    with pytest.raises(ValidationError):
        changed(portfolio, lambda payload: payload["candidates"][0].update(cost=cost))


@pytest.mark.parametrize("mode", ["unknown", "cycle", "self"])
def test_invalid_dependencies_rejected(portfolios, mode):
    _, portfolio = portfolios

    def invalid(payload):
        payload["candidates"][0]["depends_on"] = [{
            "unknown": "absent", "cycle": "linked-record", "self": "retrieve-record",
        }[mode]]

    with pytest.raises(ValidationError):
        changed(portfolio, invalid)


def test_new_testing_is_not_a_candidate_type(portfolios):
    portfolio, _ = portfolios
    with pytest.raises(ValidationError):
        changed(portfolio, lambda payload: payload["candidates"][0].update(action_type="order_new_test"))


def test_contradictory_evidence_is_preserved_and_can_increase_uncertainty(portfolios):
    portfolio, _ = portfolios
    original = portfolio.model_dump_json()
    patient = hypothetical_reviews(portfolio, {"broad-record": "negative"})
    patient.evidence[0].evidence_id = "baseline-known-negative"
    modified = Portfolio.model_validate({**portfolio.model_dump(), "patient": patient})
    positive = portfolio.candidates[0].outcomes[0].model_copy(deep=True)
    positive.additions[0].evidence_id = "distinct-positive-record"
    after = evaluate_portfolio(modified, apply_outcome(patient, positive))
    assert after.uncertainty == 4
    assert evaluate_portfolio(modified).uncertainty == 1
    assert any(node.state.value == "conflict" for decision in after.decisions for node in decision.assessment.assessments)
    assert portfolio.model_dump_json() == original
    action = modified.candidates[0].model_dump()
    for outcome in action["outcomes"]:
        outcome["additions"][0]["evidence_id"] = "new-independent-record"
    payload = modified.model_dump()
    payload["candidates"][0] = action
    modified = Portfolio.model_validate(payload)
    assert row_for(modified, "broad-record")["delta_U"] == Fraction(-57, 20)


def test_explicit_retraction_has_provenance_and_does_not_mutate_patient(portfolios):
    portfolio, _ = portfolios
    action = portfolio.candidates[1]
    positive, negative = [outcome.additions[0].model_copy(deep=True) for outcome in action.outcomes]
    positive.evidence_id, negative.evidence_id = "old-positive", "old-negative"
    patient = portfolio.patient.model_copy(deep=True)
    patient.evidence = [positive, negative]
    correction = ReviewOutcome(
        outcome_id="adjudicated", probability="1", description="Synthetic documented record correction",
        retractions=[EvidenceRetraction(
            evidence_id=negative.evidence_id, reason="Synthetic duplicate record documented as erroneous",
            provenance=EvidenceProvenance(record_id="synthetic-correction", reference="synthetic://correction"),
        )],
    )
    payload = portfolio.model_dump()
    payload["patient"] = patient
    payload["candidates"][1]["outcomes"] = [correction]
    modified = Portfolio.model_validate(payload)
    original = modified.model_dump_json()
    assert row_for(modified, action.item_id)["delta_U"] == 1
    updated = hypothetical_reviews(modified, {action.item_id: "adjudicated"})
    assert [item.evidence_id for item in updated.evidence] == ["old-positive"]
    assert modified.model_dump_json() == original
    assert correction.retractions[0].provenance.record_id == "synthetic-correction"


def test_pure_updates_reject_overwrites_and_absent_retractions(portfolios):
    portfolio, _ = portfolios
    outcome = portfolio.candidates[0].outcomes[0]
    patient = apply_outcome(portfolio.patient, outcome)
    with pytest.raises(ValueError, match="overwrite"):
        apply_outcome(patient, outcome)
    retraction = ReviewOutcome(
        outcome_id="bad", description="synthetic invalid update", retractions=[EvidenceRetraction(
            evidence_id="absent", reason="synthetic", provenance=portfolio.candidates[0].existing_record,
        )],
    )
    with pytest.raises(ValueError, match="absent"):
        apply_outcome(patient, retraction)


def test_targets_cannot_omit_shared_trial_effects(portfolios):
    portfolio, _ = portfolios
    with pytest.raises(ValidationError, match="affected"):
        changed(portfolio, lambda payload: payload["candidates"][0].update(targets=payload["candidates"][0]["targets"][:1]))


def test_budget_zero_and_scenario_limit(portfolios):
    portfolio, dependent = portfolios
    assert select_reviews(portfolio, "random", ExperimentConfig(budget=0))["selected_items"] == []
    with pytest.raises(ValueError, match="scenario limit"):
        rank_candidates(portfolio, "cost_only", ExperimentConfig(max_scenarios=1))
    rows = rank_candidates(dependent, "expected_per_cost", ExperimentConfig(max_scenarios=1))
    assert rows[0]["delta_U"] == 1


def test_existing_reasoning_engine_is_called(portfolios, monkeypatch):
    portfolio, _ = portfolios
    original = portfolio_module.assess_criteria
    calls = []

    def assess(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(portfolio_module, "assess_criteria", assess)
    evaluate_portfolio(portfolio)
    assert len(calls) == len(portfolio.trials)


def test_cli_saves_reproducible_configuration_and_new_results(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    with TemporaryDirectory(dir=root / "cache") as directory:
        monkeypatch.setattr(prioritization_experiment, "RESULTS_DIR", Path(directory))
        config = ExperimentConfig(seed=11, budget=2)
        first = prioritization_experiment.run_experiment(config)
        previous = (first / "results.json").read_bytes()
        second = prioritization_experiment.run_experiment(config)
        assert first != second
        assert (first / "results.json").read_bytes() == previous == (second / "results.json").read_bytes()
        saved = json.loads((first / "config.json").read_text())
        assert saved["experiment"]["seed"] == 11
        assert len(saved["portfolios"]) == 2
        assert all(portfolio["assumptions"] for portfolio in saved["portfolios"])
        results = json.loads(previous)
        assert all(len(item["methods"]) == len(STRATEGIES) for item in results)
        assert prioritization_experiment.main(["--seed", "11", "--budget", "2"]) == 0


def test_cli_invalid_config():
    with pytest.raises(SystemExit) as error:
        prioritization_experiment.main(["--budget", "-1"])
    assert error.value.code == 2


def test_multiple_unresolved_states_still_one_protocol_decision(portfolios):
    _, portfolio = portfolios
    a = portfolio.candidates[0].outcomes[0].additions[0].model_copy(deep=True)
    a.evidence_id = "baseline-a-positive"
    contradictory = a.model_copy(deep=True)
    contradictory.evidence_id, contradictory.value = "baseline-a-negative", "0"
    b = portfolio.candidates[1].outcomes[0].additions[0].model_copy(deep=True)
    b.evidence_id = "baseline-future-b"
    b.observation_date += timedelta(days=1)
    payload = portfolio.model_dump()
    payload["patient"]["evidence"] = [a, contradictory, b]
    modified = Portfolio.model_validate(payload)
    assessment = evaluate_portfolio(modified)
    assert assessment.uncertainty == 1
    states = {node.state.value for node in assessment.decisions[0].assessment.assessments}
    assert states == {"conflict", "temporal"}


def test_empty_protocol_stays_unresolved(portfolios):
    _, portfolio = portfolios
    payload = portfolio.model_dump()
    payload["trials"][0]["criteria_set"]["criteria"] = []
    payload["trials"][0]["bindings"] = []
    payload["candidates"] = []
    modified = Portfolio.model_validate(payload)
    assert evaluate_portfolio(modified).uncertainty == 1
    assert select_reviews(modified, "random", ExperimentConfig())["selected_items"] == []


def test_exact_multi_review_expectation_preserves_conflicting_branches(portfolios):
    portfolio, _ = portfolios

    def duplicate(payload):
        action = copy.deepcopy(payload["candidates"][0])
        action["item_id"] = "second-x-record"
        for outcome in action["outcomes"]:
            outcome["probability"] = "0.5"
            outcome["additions"][0]["evidence_id"] = "second-x-observation"
        payload["candidates"].append(action)

    modified = changed(portfolio, duplicate)
    result = select_reviews(modified, "expected_per_cost", ExperimentConfig(budget=10))
    assert result["final_expected_uncertainty"] == Fraction(117, 40)
    assert result["expected_reduction"] == Fraction(43, 40)
    conditional = rank_candidates(
        modified, "expected_per_cost", ExperimentConfig(budget=2), {"broad-record": "negative"},
    )
    second = next(row for row in conditional if row["item_id"] == "second-x-record")
    assert second["delta_U"] == Fraction(-3, 2)


def test_no_silent_normalization_or_zero_probability_scenarios(portfolios):
    portfolio, _ = portfolios

    def certain(payload):
        action = payload["candidates"][1]
        action["outcomes"][0]["probability"] = "1"
        action["outcomes"][1]["probability"] = "0"

    modified = changed(portfolio, certain)
    row = row_for(modified, "decisive-record")
    assert len(row["outcome_traces"]) == 1
    assert row["outcome_traces"][0]["probability"] == 1
    assert row["delta_U"] == 1


@pytest.mark.parametrize("budget", ["-1", "NaN", "Infinity"])
def test_invalid_budgets_rejected(budget):
    with pytest.raises(ValidationError):
        ExperimentConfig(budget=budget)
