import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pytest

from backend import nebius_check
from backend.app import nebius


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.delenv("NEBIUS_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "synthetic-secret")
    monkeypatch.setenv("NEBIUS_MODEL", nebius.DEFAULT_MODEL)
    monkeypatch.setenv("NEBIUS_LIVE_EXTRACTION", "1")
    monkeypatch.setenv("NEBIUS_BASE_URL", nebius.BASE_URL)
    original_client = httpx.Client

    def install(handler):
        monkeypatch.setattr(
            nebius.httpx, "Client",
            lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
        )

    with TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "cache") as directory:
        monkeypatch.setattr(nebius, "LIVE_CLAIM", Path(directory) / "live.claim")
        yield install


@pytest.fixture
def report_directory(monkeypatch):
    cache = Path(__file__).resolve().parents[2] / "cache"
    cache.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=cache) as directory:
        path = Path(directory) / "nebius"
        monkeypatch.setattr(nebius_check, "RESULTS_DIR", path)
        yield path


def test_mock_needs_no_configuration_or_network(monkeypatch):
    for name in ("NEBIUS_API_KEY", "NEBIUS_MODEL", "NEBIUS_BASE_URL"):
        monkeypatch.delenv(name, raising=False)

    def fail(**kwargs):
        pytest.fail("Unexpected network access")

    monkeypatch.setattr(nebius.httpx, "Client", fail)
    assert nebius.check_connectivity() == {
        "mode": "mock", "synthetic": True, "response_matches": True,
    }


@pytest.mark.parametrize("content, matches", [("SYNTHETIC_OK", True), ("Other synthetic text", False)])
def test_success(transport, content, matches):
    def handler(request):
        assert str(request.url) == nebius.BASE_URL + "/chat/completions"
        assert request.headers["Authorization"] == "Bearer synthetic-secret"
        payload = json.loads(request.content)
        assert payload["model"] == nebius.DEFAULT_MODEL
        assert payload["messages"] == [{"role": "user", "content": nebius.SYNTHETIC_PROMPT}]
        assert payload["max_tokens"] == 32
        assert payload["stream"] is False
        assert request.extensions["timeout"]["read"] == 120.0
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    transport(handler)
    assert nebius.check_connectivity(mock=False, live_approved=True) == {
        "mode": "live", "synthetic": True, "response_matches": matches,
    }
    assert "synthetic-secret" not in repr(nebius.NebiusConfig.from_environment())


@pytest.mark.parametrize("status, body, code", [
    (401, {"error": {"message": "synthetic-secret"}}, "authentication_error"),
    (403, {}, "permission_denied"),
    (402, {}, "insufficient_credits"),
    (429, {"error": {"code": "insufficient_quota"}}, "insufficient_credits"),
    (403, {"detail": "Insufficient balance"}, "insufficient_credits"),
    (429, {}, "rate_limited"),
    (404, {}, "invalid_model"),
    (400, {"error": {"code": "model_not_found"}}, "invalid_model"),
    (422, {"detail": "Invalid model"}, "invalid_model"),
    (400, {}, "http_error"),
    (500, {}, "http_error"),
    (302, {}, "http_error"),
])
def test_http_errors(transport, status, body, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body, headers={"Location": "https://example.invalid"})

    transport(handler)
    with pytest.raises(nebius.NebiusError) as error:
        nebius.check_connectivity(mock=False, live_approved=True)
    assert error.value.code == code
    assert str(error.value) == code
    assert len(calls) == 1


@pytest.mark.parametrize("exception, code", [
    (httpx.ReadTimeout, "timeout"),
    (httpx.ConnectError, "connection_error"),
])
def test_transport_errors(transport, exception, code):
    def handler(request):
        raise exception("synthetic-secret", request=request)

    transport(handler)
    with pytest.raises(nebius.NebiusError) as error:
        nebius.check_connectivity(mock=False, live_approved=True)
    assert error.value.code == code
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("body", [
    b"invalid", b"{}", b'{"choices": []}', b'{"choices": null}',
    b'{"choices": [{"message": {"content": null}}]}',
    b'{"choices": [{"message": {"content": ""}}]}',
])
def test_invalid_response(transport, body):
    transport(lambda request: httpx.Response(200, content=body))
    with pytest.raises(nebius.NebiusError, match="^invalid_response$"):
        nebius.check_connectivity(mock=False, live_approved=True)


@pytest.mark.parametrize("name, value", [
    ("NEBIUS_API_KEY", ""), ("NEBIUS_MODEL", ""),
    ("NEBIUS_BASE_URL", "https://example.invalid/v1"),
])
def test_configuration_errors(transport, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    transport(lambda request: pytest.fail("Unexpected request"))
    with pytest.raises(nebius.NebiusError, match="^configuration_error$"):
        nebius.check_connectivity(mock=False, live_approved=True)


@pytest.mark.parametrize("args", [[], ["--mock"]])
def test_cli_defaults_offline(report_directory, monkeypatch, args):
    def fail(**kwargs):
        pytest.fail("Unexpected network access")

    monkeypatch.setattr(nebius.httpx, "Client", fail)
    assert nebius_check.main(args) == 0
    assert nebius_check.main(args) == 0
    reports = list(report_directory.glob("*.json"))
    assert len(reports) == 2
    result = json.loads(reports[0].read_text())
    assert result["mode"] == "mock"
    assert result["synthetic"] is True
    assert result["status"] == "ok"


def test_cli_explicit_live_with_mock_transport(transport, report_directory, capsys):
    transport(lambda request: httpx.Response(401, text="synthetic-secret"))
    assert nebius_check.main(["--live", "--approve-one-live-request"]) == 1
    report, = report_directory.glob("*.json")
    text = report.read_text()
    assert "synthetic-secret" not in text + capsys.readouterr().out
    result = json.loads(text)
    assert result["error_code"] == "authentication_error"
    assert result["mode"] == "live"


def test_cli_modes_mutually_exclusive(report_directory):
    with pytest.raises(SystemExit) as error:
        nebius_check.main(["--mock", "--live"])
    assert error.value.code == 2
    assert not report_directory.exists()


def test_cli_storage_failure(report_directory):
    report_directory.write_text("Synthetic obstruction", encoding="utf-8")
    assert nebius_check.main(["--mock"]) == 1


def test_truncated_completion_rejected(transport):
    transport(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": "SYNTHETIC_OK"}, "finish_reason": "length"}],
    }))
    with pytest.raises(nebius.NebiusError, match="^incomplete_response$") as error:
        nebius.check_connectivity(mock=False, live_approved=True)
    assert error.value.raw_response is not None


def test_input_bound_prevents_network(transport):
    transport(lambda request: pytest.fail("Unexpected request"))
    with pytest.raises(nebius.NebiusError, match="input_limit_exceeded"):
        nebius.chat_completion([{"role": "user", "content": "x" * nebius.MAX_INPUT_TOKENS}], config=nebius.NebiusConfig.from_environment())


def test_claim_is_exclusive(transport, monkeypatch, report_directory):
    monkeypatch.setenv("NEBIUS_MODEL", nebius.DEFAULT_MODEL)
    monkeypatch.setenv("NEBIUS_LIVE_EXTRACTION", "1")
    monkeypatch.setattr(nebius, "LIVE_CLAIM", report_directory / "live.claim")
    nebius.reserve_live_request()
    with pytest.raises(nebius.NebiusError):
        nebius.reserve_live_request()


def test_connectivity_requires_approval_and_shares_extraction_reservation(transport):
    calls = []
    transport(lambda request: (calls.append(request) or httpx.Response(200, json={
        "model": nebius.DEFAULT_MODEL, "choices": [{"message": {"content": "SYNTHETIC_OK"}}]})))
    with pytest.raises(nebius.NebiusError, match="manual_approval_required"):
        nebius.check_connectivity(mock=False)
    assert not nebius.LIVE_CLAIM.exists()
    nebius.check_connectivity(mock=False, live_approved=True)
    with pytest.raises(nebius.NebiusError, match="live_extraction_unavailable"):
        nebius.check_connectivity(mock=False, live_approved=True)
    assert len(calls) == 1


def test_live_connectivity_cli_requires_manual_approval(report_directory):
    with pytest.raises(SystemExit) as error:
        nebius_check.main(["--live"])
    assert error.value.code == 2
    assert not report_directory.exists()


def test_public_demo_blocks_claim_even_with_credentials_and_approval(transport, monkeypatch):
    monkeypatch.setenv("TRIALLENS_PUBLIC_DEMO", "1")
    transport(lambda request: pytest.fail("Unexpected request"))
    assert nebius.configuration_check()["ready"] is False
    with pytest.raises(nebius.NebiusError, match="live_extraction_unavailable"):
        nebius.check_connectivity(mock=False, live_approved=True)
    assert not nebius.LIVE_CLAIM.exists()


def test_returned_model_mismatch_is_never_silently_accepted(transport):
    transport(lambda request: httpx.Response(200, json={"model": "other-model",
        "choices": [{"message": {"content": "SYNTHETIC_OK"}}]}))
    with pytest.raises(nebius.NebiusError, match="returned_model_mismatch"):
        nebius.check_connectivity(mock=False, live_approved=True)
    assert nebius.LIVE_CLAIM.exists()


def test_claim_survives_independent_process_and_atomic_race(transport):
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor

    def reserve(_):
        try:
            nebius.reserve_live_request()
            return True
        except nebius.NebiusError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sum(executor.map(reserve, range(2))) == 1
    code = "from pathlib import Path; from backend.app import nebius; nebius.LIVE_CLAIM=Path(__import__('sys').argv[1]); print(nebius.configuration_check()['request_available'])"
    result = subprocess.run([sys.executable, "-B", "-c", code, str(nebius.LIVE_CLAIM)],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and result.stdout.strip() == "False"

@pytest.mark.parametrize('setting,expected', [(None, 120.0), ('240', 240.0), ('0.5', 0.5)])
def test_timeout_configuration(transport, monkeypatch, setting, expected):
    if setting is not None:
        monkeypatch.setenv('NEBIUS_TIMEOUT_SECONDS', setting)
    config = nebius.NebiusConfig.from_environment()
    assert config.timeout_seconds == expected
    assert nebius.configuration_check()['timeout_seconds'] == expected
    def handler(request):
        assert set(request.extensions['timeout'].values()) == {expected}
        return httpx.Response(200, json={'choices': [{'message': {'content': 'SYNTHETIC_OK'}}]})
    transport(handler)
    nebius.check_connectivity(mock=False, live_approved=True)


@pytest.mark.parametrize('setting', ['', 'invalid', '0', '-1', 'nan', 'inf', '-inf'])
def test_invalid_timeout_never_reserves_or_sends(transport, monkeypatch, setting):
    monkeypatch.setenv('NEBIUS_TIMEOUT_SECONDS', setting)
    transport(lambda request: pytest.fail('Unexpected request'))
    status = nebius.configuration_check()
    assert status['ready'] is False
    assert status['timeout_seconds'] is None
    assert 'invalid_timeout' in status['errors']
    with pytest.raises(nebius.NebiusError, match='invalid_timeout'):
        nebius.check_connectivity(mock=False, live_approved=True)
    assert not nebius.LIVE_CLAIM.exists()


@pytest.mark.parametrize('exception', [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_timeout_never_retries_or_releases_reservation(transport, exception):
    calls = []
    def handler(request):
        calls.append(request)
        raise exception('synthetic-secret', request=request)
    transport(handler)
    with pytest.raises(nebius.NebiusError) as caught:
        nebius.check_connectivity(mock=False, live_approved=True)
    assert caught.value.code == 'timeout'
    assert caught.value.raw_response is None
    assert 'No complete response received' in str(caught.value)
    assert 'processing and billing are unknown' in str(caught.value)
    assert 'does not mean the provider did not process' in str(caught.value)
    before = nebius.LIVE_CLAIM.read_bytes()
    with pytest.raises(nebius.NebiusError, match='live_extraction_unavailable'):
        nebius.check_connectivity(mock=False, live_approved=True)
    assert len(calls) == 1
    assert nebius.LIVE_CLAIM.read_bytes() == before


def test_cli_timeout_report_explains_uncertainty(transport, report_directory):
    def handler(request):
        raise httpx.ReadTimeout('synthetic-secret', request=request)
    transport(handler)
    assert nebius_check.main(['--live', '--approve-one-live-request']) == 1
    report, = report_directory.glob('*.json')
    result = json.loads(report.read_text())
    assert result['error_code'] == 'timeout'
    assert result['message'] == nebius.TIMEOUT_MESSAGE
    assert 'synthetic-secret' not in report.read_text()


@pytest.mark.parametrize("content", [None, "", "   ", '{"criteria":[],"evidence":[]}'])
@pytest.mark.parametrize("finish", ["length", "content_filter"])
def test_finish_reason_precedes_empty_content_check(transport, content, finish):
    calls = []
    payload = {"model": nebius.DEFAULT_MODEL, "choices": [{"finish_reason": finish,
        "message": {"content": content, "reasoning": "Software-only unfinished reasoning", "refusal": None}}],
        "usage": {"prompt_tokens": 939, "completion_tokens": 8192, "total_tokens": 9131,
                  "completion_tokens_details": {"reasoning_tokens": 8192}}}
    transport(lambda request: (calls.append(request) or httpx.Response(200, json=payload)))
    with pytest.raises(nebius.NebiusError, match="^incomplete_response$") as caught:
        nebius.check_connectivity(mock=False, live_approved=True)
    assert json.loads(caught.value.raw_response) == payload
    assert len(calls) == 1
    assert nebius.LIVE_CLAIM.exists()


def test_reasoning_json_is_never_promoted_to_final_content(transport):
    transport(lambda request: httpx.Response(200, json={"model": nebius.DEFAULT_MODEL,
        "choices": [{"finish_reason": "stop", "message": {"content": None,
            "reasoning": '{"criteria":[],"evidence":[]}',
            "reasoning_content": '{"criteria":[],"evidence":[]}'}}]}))
    with pytest.raises(nebius.NebiusError, match="^invalid_response$"):
        nebius.check_connectivity(mock=False, live_approved=True)

@pytest.mark.parametrize('base', [nebius.BASE_URL, nebius.REGIONAL_BASE_URL])
@pytest.mark.parametrize('finish,content,expected', [('stop', 'SYNTHETIC_OK', None), ('length', None, 'incomplete_response'), ('length', 'partial', 'incomplete_response')])
def test_non_reasoning_outbound_request_and_incomplete_rejection(transport, monkeypatch, base, finish, content, expected):
    monkeypatch.setenv('NEBIUS_BASE_URL', base)
    messages = [{'role': 'user', 'content': 'Software test only'}]
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == base + '/chat/completions'
        assert request.extensions['timeout']['read'] == 120
        assert json.loads(request.content) == {
            'model': nebius.DEFAULT_MODEL, 'messages': messages, 'max_tokens': 8192, 'stream': False,
            'extra_body': {'chat_template_kwargs': {'enable_thinking': False}},
        }
        return httpx.Response(200, json={'model': nebius.DEFAULT_MODEL,
            'choices': [{'finish_reason': finish, 'message': {'content': content}}]})
    transport(handler)
    config = nebius.NebiusConfig.from_environment()
    if expected:
        with pytest.raises(nebius.NebiusError, match=expected):
            nebius.chat_completion(messages, config=config, max_tokens=8192, non_reasoning=True)
    else:
        assert nebius.chat_completion(messages, config=config, max_tokens=8192, non_reasoning=True)['content'] == content
    assert len(calls) == 1


def test_unsupported_reasoning_control_never_falls_back_or_retries(transport):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={'error': {'message': 'Unsupported parameter chat_template_kwargs'}})
    transport(handler)
    with pytest.raises(nebius.NebiusError, match='http_error'):
        nebius.chat_completion([{'role': 'user', 'content': 'Software test'}],
            config=nebius.NebiusConfig.from_environment(), non_reasoning=True)
    assert len(calls) == 1
