import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.app.nebius import NebiusError, check_connectivity, configuration_check

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results" / "nebius"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic Nebius connectivity test")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--mock", action="store_true", help="Offline test (default)")
    modes.add_argument("--live", action="store_true", help="Send one paid synthetic request")
    modes.add_argument("--config", action="store_true", help="Offline settings check")
    parser.add_argument("--approve-one-live-request", action="store_true")
    args = parser.parse_args(argv)
    if args.live and not args.approve_one_live_request:
        parser.error("Live mode requires --approve-one-live-request")
    if args.approve_one_live_request and not args.live:
        parser.error("Approval requires live mode")
    if args.config:
        result = configuration_check()
        print(json.dumps(result))
        return 0 if result["configured"] else 1
    timestamp = datetime.now(timezone.utc)
    result = {
        "timestamp": timestamp.isoformat(),
        "mode": "live" if args.live else "mock",
        "synthetic": True,
    }
    exit_code = 0
    try:
        result.update(check_connectivity(mock=not args.live, live_approved=args.approve_one_live_request))
        result["status"] = "ok"
    except NebiusError as error:
        result.update(status="error", error_code=error.code)
        if error.code == "timeout":
            result["message"] = str(error)
        exit_code = 1
    try:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / f"{timestamp:%Y%m%dT%H%M%S%fZ}_{uuid4().hex}.json"
        with path.open("x", encoding="utf-8") as file:
            json.dump(result, file, indent=2)
    except OSError:
        print("Result storage failed")
        return 1
    print("Connectivity check passed" if exit_code == 0 else f"Nebius {result['error_code']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
