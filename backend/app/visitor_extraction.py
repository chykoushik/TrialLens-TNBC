import asyncio
import hashlib
import json
import os
import re
import secrets
import threading
import time
from contextlib import suppress
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from backend.app.extraction_prompt import CLINICAL_FIELDS, build_messages
from backend.app.extraction_validation import validate_extraction
from backend.app.nebius import BASE_URL, DEFAULT_MODEL, MAX_INPUT_TOKENS, NebiusConfig, NebiusError, pricing
from backend.app.trial_extraction_api import select_source
import httpx

router = APIRouter(prefix="/visitor-analysis", tags=["ephemeral visitor extraction"])
lock = threading.Lock()
plans = {}
attempts = {}
active = set()
OUTPUT_LIMIT = 8192
MAX_SECTIONS = 24
TTL = 600


class Preparation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nct_id: str = Field(pattern=r"^NCT\d{8}$")
    snapshot: str = Field(max_length=200)
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    analysis_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    api_key: SecretStr
    confirmed: bool = False
    maximum_cost_usd: Decimal = Field(ge=0, allow_inf_nan=False)


def boundary(request):
    if os.environ.get("TRIALLENS_BYOK_ENABLED") != "1" or os.environ.get("TRIALLENS_PUBLIC_RESEARCH") == "1":
        raise HTTPException(503, "Visitor extraction is disabled pending deployment security review.")
    if request.url.scheme != "https" and request.client.host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(400, "Visitor credentials require HTTPS.")
    origin = request.headers.get("origin")
    allowed = {str(request.base_url).rstrip("/")}
    allowed.update(os.environ.get("TRIALLENS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))
    if origin and origin not in allowed:
        raise HTTPException(403, "Untrusted request origin.")
    return hashlib.sha256(request.client.host.encode()).hexdigest()


def sections(source):
    headings = list(re.finditer(r"^[ \t]*(?:#+[ \t]*)?(Inclusion|Exclusion)(?:[ \t]+Criteria)?[ \t]*:?[ \t]*$", source.text, re.M | re.I))
    if not headings or source.text[:headings[0].start()].strip():
        raise HTTPException(422, "Criteria require source review before section extraction.")
    units = []
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(source.text)
        body = source.text[heading.end():end]
        if len(body.encode()) > 4500 and re.search(r"^[ \t]*(?:[*-] )?(?:For )?(?:cohort|arm|group|part)\b", body, re.M | re.I):
            raise HTTPException(422, "Long cohort-scoped criteria require source review before splitting.")
        starts = [m.start() for m in re.finditer(r"^(?:\* |[-•] |\d+[.)] )", body, re.M)]
        cuts = [0] + [p for p in starts if p > 0] + [len(body)]
        blocks = [body[a:b] for a, b in zip(cuts, cuts[1:]) if body[a:b].strip()]
        grouped = []
        for block in blocks:
            if len(block.encode()) > 4500:
                raise HTTPException(422, "A dependent criterion is too long for safe automatic splitting. Source review required.")
            if grouped and len((grouped[-1] + block).encode()) <= 4500:
                grouped[-1] += block
            else:
                grouped.append(block)
        cursor = heading.end()
        for block in grouped:
            text = heading.group() + "\n" + block
            part = replace(source, text=text)
            messages = build_messages(part)
            bound = sum(len(m["content"].encode()) + 256 for m in messages)
            if bound > MAX_INPUT_TOKENS:
                raise HTTPException(422, "Section exceeds safe input limit.")
            start = source.text.index(block, cursor, end)
            cursor = start + len(block)
            units.append({"source": part, "messages": messages, "input_limit": bound,
                          "source_start": start, "source_end": cursor,
                          "heading_start": heading.start(), "heading_end": heading.end(),
                          "body_offset": len(heading.group()) + 1})
    if not units or len(units) > MAX_SECTIONS:
        raise HTTPException(422, "Source exceeds the visitor request limit; source review required.")
    coverage = {i for unit in units for i in range(unit["source_start"], unit["source_end"])}
    if any(not char.isspace() and i not in coverage and not any(h.start() <= i < h.end() for h in headings)
           for i, char in enumerate(source.text)):
        raise HTTPException(422, "Source sections do not provide complete coverage.")
    return units


@router.post("/prepare")
def prepare(body: Preparation, request: Request):
    owner = boundary(request)
    now = time.monotonic()
    with lock:
        for identifier in list(plans):
            if plans[identifier]["expires"] < now:
                del plans[identifier]
        for identifier in list(attempts):
            if now - attempts[identifier][0] >= TTL:
                del attempts[identifier]
        since, count = attempts.get(owner, (now, 0))
        if count >= 6 or len(plans) >= 256:
            raise HTTPException(429, "Visitor preparation limit reached. Please wait ten minutes.")
        attempts[owner] = (since, count + 1)
    source = select_source(body.nct_id, body.snapshot)
    if source.sha256 != body.snapshot_sha256 or source.is_synthetic is True:
        raise HTTPException(409, "Choose an unchanged real registry snapshot.")
    try:
        rates = pricing()
    except NebiusError:
        rates = None
    if rates is None:
        raise HTTPException(503, "Operator must configure verified provider pricing before visitor extraction.")
    units = sections(source)
    cost = sum(Decimal(unit["input_limit"]) * Decimal(str(rates["input_usd_per_million"]))
               + Decimal(OUTPUT_LIMIT) * Decimal(str(rates["output_usd_per_million"])) for unit in units) / Decimal(1000000)
    try:
        ceiling = Decimal(os.environ.get("TRIALLENS_BYOK_MAX_USD", "1"))
        if not ceiling.is_finite() or ceiling <= 0:
            raise ValueError
    except (ValueError, ArithmeticError):
        raise HTTPException(503, "Visitor cost ceiling is not configured safely.") from None
    if cost > ceiling:
        raise HTTPException(422, "This analysis exceeds the server cost ceiling.")
    identifier = secrets.token_hex(32)
    quote = {"analysis_id": identifier, "nct_id": source.nct_id, "snapshot_sha256": source.sha256,
             "model": DEFAULT_MODEL, "request_count": len(units), "max_output_tokens_per_request": OUTPUT_LIMIT,
             "max_input_tokens": [unit["input_limit"] for unit in units], "maximum_cost_usd": str(cost),
             "expires_in_seconds": TTL}
    with lock:
        plans[identifier] = {"owner": owner, "expires": now + TTL, "quote": quote, "source": source, "units": units, "snapshot": body.snapshot}
    return quote


async def provider(messages, key, disconnected):
    from backend.app.nebius import build_chat_payload, error_code
    config = NebiusConfig(key, DEFAULT_MODEL, BASE_URL)
    payload = build_chat_payload(messages, model=config.model, max_tokens=OUTPUT_LIMIT, non_reasoning=True)
    payload.update(store=False, n=1)
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.post(f"{BASE_URL}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=payload)
        if not response.is_success:
            raise NebiusError(error_code(response))
        data = response.json()
        choice = data["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise NebiusError("incomplete_response")
        if data.get("model") != DEFAULT_MODEL:
            raise NebiusError("returned_model_mismatch")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise NebiusError("invalid_response")
        if key in content or key in json.dumps(json.loads(content), ensure_ascii=False):
            raise NebiusError("credential_echo_redacted")
        return content
    except httpx.TimeoutException:
        raise NebiusError("timeout") from None
    except httpx.HTTPError:
        raise NebiusError("connection_error") from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
        raise NebiusError("invalid_response") from None


async def extract(plan, key, disconnected):
    results = []
    requests_sent = 0
    timestamp = datetime.now(timezone.utc).isoformat()
    for index, unit in enumerate(plan["units"]):
        if disconnected.is_set():
            break
        try:
            requests_sent += 1
            content = await provider(unit["messages"], key, disconnected)
            model, errors = validate_extraction(content, unit["source"], method="visitor-section-v1", timestamp=timestamp, allow_unresolved_logic=True)
            if model is None or errors:
                raise NebiusError("source_validation_failed")
            evidence = json.loads(content)["evidence"]
            offset = unit["source_start"] - unit["body_offset"]
            for entry in evidence:
                for span in [entry["original_span"], *entry["fields"].values()]:
                    span["start"] += offset
                    span["end"] += offset
                entry["polarity_span"] = {"start": unit["heading_start"], "end": unit["heading_end"]}
                entry["criterion_id"] = f"section-{index + 1}:{entry['criterion_id']}"
            criteria = [n.model_dump(mode="json") for n in model.criteria]
            def identify(nodes):
                for node in nodes:
                    node["criterion_id"] = f"section-{index + 1}:{node['criterion_id']}"
                    identify(node["dependencies"] or [])
            identify(criteria)
            results.append({"section": index + 1, "status": "validated", "source_start": unit["source_start"],
                            "source_end": unit["source_end"], "source_evidence": evidence,
                            "criteria": criteria})
        except NebiusError as error:
            results.append({"section": index + 1, "status": "failed", "error": error.code, "criteria": []})
            break
    results.extend({"section": i + 1, "status": "not_requested", "criteria": []} for i in range(len(results), len(plan["units"])))
    complete = bool(results) and all(r["status"] == "validated" for r in results)
    merged = None
    if complete:
        def clinical(node):
            value = {name: node[name] for name in CLINICAL_FIELDS}
            if value["dependencies"] is not None:
                value["dependencies"] = [clinical(child) for child in value["dependencies"]]
            return value
        combined = {"criteria": [clinical(node) for section in results for node in section["criteria"]],
                    "evidence": [entry for section in results for entry in section["source_evidence"]]}
        merged, errors = validate_extraction(json.dumps(combined), plan["source"], method="visitor-merged-v1",
                                            timestamp=timestamp, allow_unresolved_logic=True)
        complete = merged is not None and not errors
    return {"status": "complete" if complete else "incomplete",
            "sections": results, "human_review_required": True, "executable_mapping": False,
            "merged_criteria": merged.model_dump(mode="json")["criteria"] if complete else [],
            "full_source_coverage_validated": complete,
            "maximum_cost_usd": plan["quote"]["maximum_cost_usd"], "planned_requests": len(plan["units"]),
            "requests_sent": requests_sent}


@router.post("/run")
async def run(body: Approval, request: Request):
    owner = boundary(request)
    key = body.api_key.get_secret_value().strip()
    body.api_key = SecretStr("")
    if not body.confirmed or not 8 <= len(key) <= 512 or any(c.isspace() for c in key) or not key.isascii():
        raise HTTPException(422, "A valid API key and explicit cost approval are required.")
    with lock:
        plan = plans.get(body.analysis_id)
        if not plan or plan["owner"] != owner or plan["expires"] < time.monotonic():
            raise HTTPException(409, "Analysis approval expired or was already used. Prepare again.")
        if body.maximum_cost_usd != Decimal(plan["quote"]["maximum_cost_usd"]):
            raise HTTPException(409, "Approve the exact prepared cost ceiling.")
        if owner in active or len(active) >= 2:
            raise HTTPException(429, "Visitor analysis already running. Please wait.")
        del plans[body.analysis_id]
        active.add(owner)
    disconnected = asyncio.Event()
    task = None
    try:
        source = select_source(plan["source"].nct_id, plan["snapshot"])
        if source.sha256 != plan["source"].sha256:
            raise HTTPException(409, "Source changed. Prepare a new analysis.")
        task = asyncio.create_task(extract(plan, key, disconnected))
        key = ""
        while not task.done():
            if await request.is_disconnected():
                disconnected.set()
                task.cancel()
                raise HTTPException(499, "Visitor disconnected; no additional requests will be sent.")
            await asyncio.sleep(.1)
        return await task
    finally:
        key = ""
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        with lock:
            active.discard(owner)
