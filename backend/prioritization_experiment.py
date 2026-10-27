import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from backend.app.portfolio import decision_trace, evaluate_portfolio
from backend.app.prioritization import hypothetical_reviews, sample_outcomes, select_reviews
from backend.app.prioritization_models import ExperimentConfig, STRATEGIES
from backend.app.synthetic_prioritization import synthetic_portfolios

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results" / "prioritization"


def json_value(value):
    if isinstance(value, (Fraction, Decimal)):
        return str(value)
    raise TypeError("Unsupported result type")


def run_experiment(config: ExperimentConfig) -> Path:
    portfolios = synthetic_portfolios()
    comparisons = []
    for portfolio in portfolios:
        sampled = sample_outcomes(portfolio, config.seed)
        methods = []
        for strategy in STRATEGIES:
            result = select_reviews(portfolio, strategy, config)
            realized = {identifier: sampled[identifier] for identifier in result["selected_items"]}
            assessment = evaluate_portfolio(portfolio, hypothetical_reviews(portfolio, realized))
            result.update(
                sampled_review_outcomes=realized, realized_uncertainty=assessment.uncertainty,
                realized_decisions=decision_trace(assessment),
            )
            methods.append(result)
        comparisons.append({
            "portfolio_id": portfolio.portfolio_id, "shared_sampled_outcomes": sampled,
            "initial_assessment": evaluate_portfolio(portfolio).model_dump(mode="json"),
            "methods": methods,
        })
    timestamp = datetime.now(timezone.utc)
    path = RESULTS_DIR / f"{timestamp:%Y%m%dT%H%M%S%fZ}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    artifacts = {
        "config.json": {"experiment": config.model_dump(mode="json"), "strategies": STRATEGIES,
                        "portfolios": [portfolio.model_dump(mode="json") for portfolio in portfolios]},
        "results.json": comparisons,
        "manifest.json": {"framework_version": "portfolio-baselines-v1", "seed": config.seed,
                          "timestamp": timestamp.isoformat(), "synthetic": True,
                          "python_version": platform.python_version(),
                          "uncertainty_version": "weighted-unresolved-protocols-v1",
                          "source_hashes": {
                              name: hashlib.sha256((Path(__file__).parent / "app" / name).read_bytes()).hexdigest()
                              for name in (
                                  "assessment.py", "assessment_models.py", "assessment_values.py", "criteria.py",
                                  "portfolio.py", "prioritization.py", "prioritization_models.py", "synthetic_prioritization.py",
                              )
                          },
                          "status": "illustrative baseline comparison; no scientific validation claim"},
    }
    for name, value in artifacts.items():
        with (path / name).open("x", encoding="utf-8") as file:
            json.dump(value, file, default=json_value, indent=2, ensure_ascii=False)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic portfolio baseline comparison")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--budget", default="2")
    parser.add_argument("--max-scenarios", type=int, default=512)
    args = parser.parse_args(argv)
    try:
        config = ExperimentConfig(seed=args.seed, budget=args.budget, max_scenarios=args.max_scenarios)
    except ValidationError:
        parser.error("Invalid experiment configuration")
    try:
        run_experiment(config)
    except (OSError, ValueError):
        print("Experiment failed")
        return 1
    print("Synthetic comparison saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
