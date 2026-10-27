import argparse
import json
import re
from pathlib import Path

from backend.app.extraction import extract_snapshot
from backend.app.extraction_source import load_source
from backend.app.extraction_prompt import build_messages
from backend.app.nebius import DEFAULT_MODEL, build_chat_payload, inference_timeout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract saved trial criteria")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--nct-id", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print credential-free request; no allocation or network")
    mode.add_argument("--mock", action="store_true", help="Offline mode (default)")
    mode.add_argument("--live", action="store_true", help="Send a paid extraction request")
    parser.add_argument("--mock-response", type=Path)
    parser.add_argument("--approve-one-live-request", action="store_true")
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--authorization-id")
    args = parser.parse_args(argv)
    if args.dry_run:
        if args.authorization_id or args.approve_one_live_request or args.mock_response:
            parser.error("Dry run forbids live approval, authorization and mock response")
        source = load_source(args.snapshot, args.nct_id)
        if args.snapshot_sha256 and source.sha256 != args.snapshot_sha256:
            parser.error("Snapshot hash mismatch")
        payload = build_chat_payload(build_messages(source), model=DEFAULT_MODEL, max_tokens=8192, non_reasoning=True)
        print(json.dumps({"request_body": payload, "timeout_seconds": inference_timeout(),
                          "automatic_retries": 0, "request_sent": False}, indent=2))
        return 0
    if args.authorization_id and not args.live:
        parser.error("Authorization ID requires live mode")
    if args.live and not args.approve_one_live_request:
        parser.error("Live mode requires --approve-one-live-request")
    if args.live and (not args.snapshot_sha256 or not re.fullmatch(r"[a-f0-9]{64}", args.snapshot_sha256)):
        parser.error("Live mode requires --snapshot-sha256")
    if not args.live and args.mock_response is None:
        parser.error("Mock mode requires --mock-response")
    if args.live and args.mock_response is not None:
        parser.error("Live mode forbids --mock-response")
    try:
        output = extract_snapshot(
            args.snapshot, args.nct_id, mock=not args.live, mock_response=args.mock_response,
            live_approved=args.approve_one_live_request, expected_sha256=args.snapshot_sha256,
            **({"authorization_id": args.authorization_id} if args.authorization_id else {}),
        )
        status = json.loads((output / "manifest.json").read_text(encoding="utf-8"))["status"]
    except OSError:
        print("Extraction storage failed")
        return 1
    print("Extraction validated" if status == "validated" else "Extraction needs review")
    return 0 if status == "validated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
