import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.app.extraction_prompt import PROMPT_VERSION, build_messages
from backend.app.extraction_source import ROOT, load_source
from backend.app.extraction_validation import validate_extraction
from backend.app.nebius import (
    MAX_INPUT_TOKENS, NebiusConfig, NebiusError, chat_completion, pricing, reserve_live_request, safe_usage,
)

RESULTS_DIR = ROOT / "results" / "extraction"


def extract_snapshot(
    snapshot: Path, nct_id: str, *, mock: bool = True, mock_response: Path | None = None,
    live_approved: bool = False, expected_sha256: str | None = None,
    authorization_id: str | None = None,
) -> Path:
    timestamp = datetime.now(timezone.utc)
    output = RESULTS_DIR / f"{timestamp:%Y%m%dT%H%M%S%fZ}_{uuid4().hex}"
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "prompt_version": PROMPT_VERSION, "timestamp": timestamp.isoformat(),
        "mode": "mock" if mock else "live", "requested_model": None,
        "returned_model": None, "status": "failed", "usage": None,
        "estimated_cost_usd": None, "pricing": None, "request_count": 0,
        "validation_scope": "structural_and_source_only", "human_review_required": True,
    }
    raw_response = None
    validated = None
    errors = []
    messages = None
    try:
        if authorization_id and (mock or not live_approved or not expected_sha256):
            raise NebiusError("invalid_authorization_mode")
        source = load_source(snapshot, nct_id)
        manifest.update(
            nct_id=source.nct_id, source_snapshot=source.source_snapshot,
            snapshot_sha256=source.sha256, is_synthetic=source.is_synthetic,
            source_url=source.source_url, retrieval_timestamp=source.retrieval_timestamp,
        )
        if expected_sha256 is not None and source.sha256 != expected_sha256:
            raise NebiusError("source_identity_changed")
        messages = build_messages(source)
        if mock:
            if mock_response is None:
                raise ValueError("Mock response required")
            path = (ROOT / mock_response).resolve()
            if not path.is_relative_to(ROOT):
                raise ValueError("Mock response must be project-local")
            fixture = json.loads(path.read_text(encoding="utf-8"))
            if fixture.get("mock") is not True or not isinstance(fixture.get("content"), str):
                raise ValueError("Explicit mock label and content required")
            raw_response = json.dumps(fixture, ensure_ascii=False)
            response = {
                "content": fixture["content"], "requested_model": "mock-no-model",
                "returned_model": "mock-no-model",
            }
        else:
            if mock_response is not None:
                raise ValueError("Mock response not allowed in live mode")
            if not live_approved:
                raise NebiusError("manual_approval_required")
            config = NebiusConfig.from_environment()
            manifest["pricing"] = pricing()
            manifest["requested_model"] = config.model
            if sum(len(message["content"].encode("utf-8")) + 256 for message in messages) > MAX_INPUT_TOKENS:
                raise NebiusError("input_limit_exceeded")
            if authorization_id:
                from backend.extraction_authorization import reserve_authorized_request
                manifest["request_authorization_id"] = authorization_id
                manifest["request_id"] = authorization_id
                manifest["request_claim"] = reserve_authorized_request(authorization_id, source, config, output)
            else:
                reserve_live_request()
            manifest["request_count"] = 1
            response = chat_completion(messages, config=config, max_tokens=8192, non_reasoning=True)
            raw_response = response["raw_response"]
        manifest.update({key: response[key] for key in ("requested_model", "returned_model")})
        manifest["usage"] = response.get("usage")
        validated, errors = validate_extraction(
            response["content"], source,
            method=f"nebius:{PROMPT_VERSION}:{manifest['mode']}", timestamp=timestamp.isoformat(),
        )
        manifest["status"] = "validated" if validated else "validation_failed"
    except NebiusError as error:
        raw_response = error.raw_response
        errors = [{"code": error.code}]
        if error.code == "timeout":
            errors[0]["message"] = str(error)
        if raw_response:
            try:
                provider = json.loads(raw_response)
                if isinstance(provider, dict):
                    manifest["usage"] = safe_usage(provider.get("usage"))
                    returned = provider.get("model")
                    manifest["returned_model"] = returned if isinstance(returned, str) else None
            except ValueError:
                pass
    except (OSError, ValueError, TypeError, AttributeError, KeyError, RecursionError):
        errors = [{"code": "invalid_source_or_configuration"}]

    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    usage, rates = manifest["usage"], manifest["pricing"]
    if usage and rates and all(name in usage for name in ("prompt_tokens", "completion_tokens")):
        manifest["estimated_cost_usd"] = (usage["prompt_tokens"] * rates["input_usd_per_million"]
                                          + usage["completion_tokens"] * rates["output_usd_per_million"]) / 1_000_000
    artifacts = {
        "manifest.json": manifest,
        "prompt.json": messages,
        "raw_response.json": raw_response,
        "validated.json": validated.model_dump(mode="json") if validated else None,
        "validation_errors.json": errors,
    }
    secret = os.environ.get("NEBIUS_API_KEY", "").strip()
    decoded_echo = False
    if secret and isinstance(artifacts["raw_response.json"], str):
        try:
            decoded = json.dumps(json.loads(artifacts["raw_response.json"]), ensure_ascii=False)
            if secret in decoded:
                artifacts["raw_response.json"] = decoded.replace(secret, "[REDACTED]")
                decoded_echo = True
        except ValueError:
            pass
    serialized = {name: (value if name == "raw_response.json" and isinstance(value, str)
                         else json.dumps(value, ensure_ascii=False, indent=2))
                  for name, value in artifacts.items()}
    if secret and (decoded_echo or any(secret in text for text in serialized.values())):
        serialized = {name: text.replace(secret, "[REDACTED]") for name, text in serialized.items()}
        manifest["status"] = "privacy_failed"
        serialized["manifest.json"] = json.dumps(manifest).replace(secret, "[REDACTED]")
        serialized["validated.json"] = "null"
        serialized["validation_errors.json"] = json.dumps([{"code": "credential_echo_redacted"}])
    for name, text in serialized.items():
        with (output / name).open("x", encoding="utf-8") as file:
            file.write(text)
    return output
