from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from backend.app.prioritization_models import Portfolio
from backend.app.review_planning import scenario_distribution
from backend.app.review_planning_models import (
    JointReviewScenario, ReviewDependence, ReviewPlanningModel, ReviewReliability,
)
from backend.app.synthetic_prioritization import synthetic_portfolios, synthetic_protocol, synthetic_review


@dataclass
class EvaluationWorld:
    probability: Fraction
    outcomes: dict[str, str]
    truth: dict[str, str]


@dataclass
class SyntheticReviewCase:
    case_id: str
    model: ReviewPlanningModel
    budgets: list[str]
    evaluation_worlds: list[EvaluationWorld]


def reliability(portfolio, errors=None):
    errors = errors or {}
    return ReviewReliability(
        conditional_error_probabilities={
            action.item_id: {outcome.outcome_id: errors.get(action.item_id, "0") for outcome in action.outcomes}
            for action in portfolio.candidates
        },
        assumption="SYNTHETIC assumed conditional error rates, not calibrated; baseline evidence and reviewed bindings assumed correct.",
    )


def make_model(portfolio, **updates):
    return ReviewPlanningModel(
        portfolio=portfolio, dependence_mode="independent_disjoint", reliability=reliability(portfolio),
        assumptions=["Synthetic finite outcome model; probabilities and costs are illustrative assumptions.",
                     "Review error assumptions are held fixed across histories; union bound need not be tight."],
        **updates,
    )


def make_portfolio(identifier, trials, reviews):
    template = synthetic_portfolios()[0]
    return Portfolio(
        portfolio_id=identifier, patient=template.patient, trials=trials, candidates=reviews,
        cost_unit=template.cost_unit, outcome_model="independent_review_outcomes",
        assumptions=["SYNTHETIC research case; independent marginals are overridden by an explicit joint wrapper when declared."],
    )


def label(consistent):
    return "constraints_consistent" if consistent else "observed_blocker"


def research_cases() -> list[SyntheticReviewCase]:
    cases = []
    broad, prerequisite = synthetic_portfolios()
    for portfolio in (broad, prerequisite):
        model = make_model(portfolio)
        worlds = []
        for probability, outcomes in scenario_distribution(model):
            if portfolio is broad:
                truth = {f"broad-{index}": label(outcomes["broad-record"] == "positive") for index in range(3)}
                truth["decisive"] = label(outcomes["decisive-record"] == "positive")
            else:
                truth = {"complementary": label(all(outcomes[item] == "positive" for item in outcomes))}
            worlds.append(EvaluationWorld(probability, outcomes, truth))
        cases.append(SyntheticReviewCase(portfolio.portfolio_id, model, ["1", "2"], worlds))

    protocols, reviews = [], []
    for identifier, weight, cost in (("a", "3", "2"), ("b", "4", "3"), ("c", "4", "3")):
        protocol = synthetic_protocol(identifier, [identifier.upper()])
        protocol.weight = Decimal(weight)
        protocols.append(protocol)
        reviews.append(synthetic_review(identifier, identifier.upper(), [protocol], cost=cost))
    model = make_model(make_portfolio("ratio_trap", protocols, reviews))
    worlds = [EvaluationWorld(p, outcomes, {key: label(value == "positive") for key, value in outcomes.items()})
              for p, outcomes in scenario_distribution(model)]
    cases.append(SyntheticReviewCase("ratio_trap", model, ["3", "6"], worlds))

    joint, distractor = synthetic_protocol("joint", ["A", "B"]), synthetic_protocol("distractor", ["D"])
    distractor.weight = Decimal("0.4")
    reviews = [synthetic_review("a", "A", [joint], cost="1", positive_probability="1"),
               synthetic_review("b", "B", [joint], cost="1", positive_probability="1"),
               synthetic_review("d", "D", [distractor], cost="1")]
    model = make_model(make_portfolio("complementarity", [joint, distractor], reviews))
    worlds = [EvaluationWorld(p, outcomes, {"joint": label(True), "distractor": label(outcomes["d"] == "positive")})
              for p, outcomes in scenario_distribution(model)]
    cases.append(SyntheticReviewCase("complementarity", model, ["1", "2"], worlds))

    joint, alternative = synthetic_protocol("branch", ["A", "B"]), synthetic_protocol("alternative", ["C"])
    alternative.weight = Decimal("0.6")
    reviews = [synthetic_review("a", "A", [joint], cost="1"),
               synthetic_review("b", "B", [joint], cost="1", positive_probability="1"),
               synthetic_review("c", "C", [alternative], cost="1", positive_probability="1")]
    model = make_model(make_portfolio("adaptive_branch", [joint, alternative], reviews))
    worlds = [EvaluationWorld(p, outcomes, {"branch": label(outcomes["a"] == "positive"), "alternative": label(True)})
              for p, outcomes in scenario_distribution(model)]
    cases.append(SyntheticReviewCase("adaptive_branch", model, ["1", "2"], worlds))

    for identifier, assumed_error in (("noisy_review", "0.4"), ("misspecified_reliability", "0.01")):
        trial = synthetic_protocol("noisy", ["R"])
        reviews = [synthetic_review("cheap", "R", [trial], cost="1"),
                   synthetic_review("reliable", "R", [trial], cost="2")]
        portfolio = make_portfolio(identifier, [trial], reviews)
        model = ReviewPlanningModel(
            portfolio=portfolio, dependence_mode="explicit_joint",
            dependence_groups=[ReviewDependence(item_ids=["cheap", "reliable"], relationship="shared_fact",
                                                assumption="Two existing records describe the same synthetic attribute; joint reports specified explicitly.")],
            joint_scenarios=[
                JointReviewScenario(scenario_id="report_pair_1", probability="0.2", outcomes={"cheap": "negative", "reliable": "positive"}),
                JointReviewScenario(scenario_id="report_pair_2", probability="0.3", outcomes={"cheap": "positive", "reliable": "positive"}),
                JointReviewScenario(scenario_id="report_pair_3", probability="0.2", outcomes={"cheap": "positive", "reliable": "negative"}),
                JointReviewScenario(scenario_id="report_pair_4", probability="0.3", outcomes={"cheap": "negative", "reliable": "negative"}),
            ], reliability=reliability(portfolio, {"cheap": assumed_error, "reliable": "0.01"}),
            assumptions=["SYNTHETIC shared-fact reports; error rates are illustrative, not clinical calibration.",
                         "The misspecified case intentionally understates cheap-review errors.",
                         "Baseline data and reviewed protocol mappings assumed correct."],
        )
        worlds = [EvaluationWorld(p, outcomes, {"noisy": label(outcomes["reliable"] == "positive")})
                  for p, outcomes in scenario_distribution(model)]
        cases.append(SyntheticReviewCase(identifier, model, ["1", "2"], worlds))

    trial = synthetic_protocol("duplicate", ["D"])
    reviews = [synthetic_review("first", "D", [trial], cost="1"), synthetic_review("copy", "D", [trial], cost="1")]
    reviews[1].existing_record = reviews[0].existing_record.model_copy(deep=True)
    portfolio = make_portfolio("correlated_duplicates", [trial], reviews)
    model = ReviewPlanningModel(
        portfolio=portfolio, dependence_mode="explicit_joint",
        dependence_groups=[ReviewDependence(item_ids=["copy", "first"], relationship="duplicate_record",
                                            assumption="The same source record is duplicated; reports are perfectly correlated.")],
        joint_scenarios=[
            JointReviewScenario(scenario_id="positive", probability="0.5", outcomes={"first": "positive", "copy": "positive"}),
            JointReviewScenario(scenario_id="negative", probability="0.5", outcomes={"first": "negative", "copy": "negative"}),
        ], reliability=reliability(portfolio), assumptions=["SYNTHETIC perfectly correlated accurate duplicate reports."],
    )
    worlds = [EvaluationWorld(p, outcomes, {"duplicate": label(outcomes["first"] == "positive")})
              for p, outcomes in scenario_distribution(model)]
    cases.append(SyntheticReviewCase("correlated_duplicates", model, ["1", "2"], worlds))
    unsupported = model.model_copy(deep=True)
    unsupported.joint_scenarios = None
    cases.append(SyntheticReviewCase("overlap_without_joint", unsupported, ["2"], []))
    return cases
