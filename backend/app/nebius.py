import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

BASE_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
REGIONAL_BASE_URL = "https://api.tokenfactory.us-central1.nebius.com/v1"
DEFAULT_TIMEOUT_SECONDS = 120.0
TIMEOUT_MESSAGE = (
    "No complete response received before the timeout. Provider processing and billing "
    "are unknown; this does not mean the provider did not process the request. "
    "The request reservation remains consumed. No automatic retry is performed."
)
MAX_INPUT_TOKENS = 24000
MAX_OUTPUT_TOKENS = 8192
LIVE_CLAIM = Path(__file__).resolve().parents[2] / "results/nebius/live-request.claim"
SYNTHETIC_PROMPT = "Synthetic connectivity test only. Reply with exactly: SYNTHETIC_OK"


class NebiusError(Exception):
    def __init__(self, code: str, *, raw_response: str | None = None):
        self.code = code
        self.raw_response = raw_response
        super().__init__(TIMEOUT_MESSAGE if code == "timeout" else code)


@dataclass(frozen=True)
class NebiusConfig:
    api_key: str = field(repr=False)
    model: str
    base_url: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_environment(cls) -> "NebiusConfig":
        timeout = inference_timeout()
        api_key = os.environ.get("NEBIUS_API_KEY", "").strip()
        model = os.environ.get("NEBIUS_MODEL", "").strip()
        base_url = os.environ.get("NEBIUS_BASE_URL", BASE_URL).strip().rstrip("/")
        if not api_key or not model or base_url not in (BASE_URL, REGIONAL_BASE_URL):
            raise NebiusError("configuration_error")
        return cls(api_key=api_key, model=model, base_url=base_url, timeout_seconds=timeout)


def inference_timeout() -> float:
    try:
        value = float(os.environ.get("NEBIUS_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        raise NebiusError("invalid_timeout") from None
    if not math.isfinite(value) or value <= 0:
        raise NebiusError("invalid_timeout")
    return value


def error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error", payload) if isinstance(payload, dict) else {}
        details = str(error).lower()
    except ValueError:
        details = ""
    if response.status_code == 401:
        return "authentication_error"
    if response.status_code == 402 or any(term in details for term in (
        "insufficient_quota", "insufficient_credit", "insufficient credit",
        "insufficient balance", "not enough credit", "credit balance", "out of credits",
    )):
        return "insufficient_credits"
    if response.status_code == 403:
        return "permission_denied"
    if response.status_code == 429:
        return "rate_limited"
    if response.status_code in (400, 404, 422) and (
        response.status_code == 404 or "model" in details
    ):
        return "invalid_model"
    return "http_error"


def build_chat_payload(messages, *, model, max_tokens=32, non_reasoning=False):
    if not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
        raise NebiusError("output_limit_exceeded")
    if sum(len(message["content"].encode("utf-8")) + 256 for message in messages) > MAX_INPUT_TOKENS:
        raise NebiusError("input_limit_exceeded")
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": False}
    if non_reasoning:
        payload["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    return payload


def chat_completion(
    messages: list[dict[str, str]], *, config: NebiusConfig, max_tokens: int = 32,
    non_reasoning: bool = False,
) -> dict[str, object]:
    payload = build_chat_payload(messages, model=config.model, max_tokens=max_tokens, non_reasoning=non_reasoning)
    try:
        with httpx.Client(timeout=config.timeout_seconds, follow_redirects=False) as client:
            response = client.post(
                f"{config.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {config.api_key}"},
                json=payload,
            )
    except httpx.TimeoutException:
        raise NebiusError("timeout") from None
    except httpx.HTTPError:
        raise NebiusError("connection_error") from None
    if not response.is_success:
        raise NebiusError(error_code(response), raw_response=response.text)
    try:
        payload = response.json()
        choice = payload["choices"][0]
        if not isinstance(choice, dict):
            raise ValueError
    except (ValueError, KeyError, IndexError, TypeError):
        raise NebiusError("invalid_response", raw_response=response.text) from None
    returned = payload.get("model")
    if returned is not None and returned != config.model:
        raise NebiusError("returned_model_mismatch", raw_response=response.text)
    if choice.get("finish_reason") in ("length", "content_filter"):
        raise NebiusError("incomplete_response", raw_response=response.text)
    try:
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise NebiusError("invalid_response", raw_response=response.text) from None
    return {
        "content": content, "raw_response": response.text,
        "requested_model": config.model,
        "returned_model": payload.get("model"),
        "usage": safe_usage(payload.get("usage")),
    }


def check_connectivity(*, mock: bool = True, live_approved: bool = False) -> dict[str, object]:
    if mock:
        return {"mode": "mock", "synthetic": True, "response_matches": True}
    if not live_approved:
        raise NebiusError("manual_approval_required")
    config = NebiusConfig.from_environment()
    reserve_live_request()
    response = chat_completion(
        [{"role": "user", "content": SYNTHETIC_PROMPT}],
        config=config,
    )
    return {
        "mode": "live", "synthetic": True,
        "response_matches": response["content"].strip() == "SYNTHETIC_OK",
    }


def safe_usage(value):
    if not isinstance(value, dict):
        return None
    return {name: value[name] for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            if type(value.get(name)) is int and value[name] >= 0} or None


def pricing():
    values = []
    for name in ("NEBIUS_INPUT_USD_PER_MILLION", "NEBIUS_OUTPUT_USD_PER_MILLION"):
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            values.append(None)
            continue
        try:
            value = float(raw)
        except ValueError:
            raise NebiusError("invalid_pricing") from None
        if not math.isfinite(value) or value < 0:
            raise NebiusError("invalid_pricing")
        values.append(value)
    if any(value is None for value in values):
        return None
    return {"input_usd_per_million": values[0], "output_usd_per_million": values[1]}


def configuration_check():
    errors = []
    timeout = None
    try:
        timeout = inference_timeout()
        config = NebiusConfig.from_environment()
        if config.model != DEFAULT_MODEL:
            errors.append("unsupported_extraction_model")
        pricing()
    except NebiusError as error:
        errors.append(error.code)
    enabled = os.environ.get("NEBIUS_LIVE_EXTRACTION") == "1"
    public = os.environ.get("TRIALLENS_PUBLIC_DEMO") == "1"
    available = not LIVE_CLAIM.exists()
    return {"configured": not errors, "api_key_present": bool(os.environ.get("NEBIUS_API_KEY", "").strip()),
            "live_enabled": enabled, "request_available": available,
            "ready": not errors and enabled and available and not public, "errors": errors,
            "public_demo": public,
            "model": DEFAULT_MODEL, "max_requests": 1, "max_input_tokens": MAX_INPUT_TOKENS,
            "max_output_tokens": MAX_OUTPUT_TOKENS, "timeout_seconds": timeout}


def reserve_live_request():
    if not configuration_check()["ready"]:
        raise NebiusError("live_extraction_unavailable")
    LIVE_CLAIM.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LIVE_CLAIM.open("x", encoding="utf-8") as file:
            file.write("One request reserved; no automatic retries.\n")
    except FileExistsError:
        raise NebiusError("request_limit_reached") from None
