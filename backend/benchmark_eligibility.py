import argparse
from pathlib import Path

from backend.app.eligibility_benchmark import build_dataset, evaluate_dataset

DEFAULT_DATASET = Path("data/benchmarks/tnbc-eligibility-v1")
DEFAULT_REPORT = Path("results/benchmark/tnbc-eligibility-v1")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline eligibility extraction benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--output", type=Path, default=DEFAULT_DATASET)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    evaluate.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    evaluate.add_argument("--predictions", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build_dataset(args.output)
        else:
            evaluate_dataset(args.dataset, args.output, predictions=args.predictions)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print("Benchmark operation failed")
        return 1
    print("Benchmark dataset saved" if args.command == "build" else "Benchmark reports saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
