import json

import aiohttp
import pytest

from app.commands import GATEWAY_UNAVAILABLE_MESSAGE, _gateway_url, call_ai_gateway, run_gateway_command


class FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, response=None, exc=None, recorder=None, timeout=None):
        self._response = response
        self._exc = exc
        self._recorder = recorder
        self._timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json=None, headers=None):
        if self._recorder is not None:
            self._recorder["url"] = url
            self._recorder["json"] = json
            self._recorder["headers"] = headers
            self._recorder["timeout_total"] = getattr(self._timeout, "total", None)
        if self._exc is not None:
            raise self._exc
        return self._response


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_URL", "http://gateway:8080/process-command")
    monkeypatch.setenv("AI_GATEWAY_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("AI_GATEWAY_RETRY_ATTEMPTS", "0")
    monkeypatch.setenv("AI_GATEWAY_RETRY_BACKOFF_SECONDS", "0")


@pytest.mark.asyncio
async def test_successful_ask_flow(monkeypatch, env):
    recorded = {}

    def fake_session_factory(*args, **kwargs):
        return FakeSession(
            response=FakeResponse(200, '{"response": "hello"}'),
            recorder=recorded,
            timeout=kwargs.get("timeout"),
        )

    monkeypatch.setattr(aiohttp, "ClientSession", fake_session_factory)

    out = await run_gateway_command(
        user_id="123",
        command_text="ask/hello",
        request_id="req-1",
        discord_channel_id="chan-1",
    )

    assert out == "hello"
    assert recorded["url"].endswith("/process-command")
    assert recorded["json"]["user_id"] == "123"
    assert recorded["json"]["command_text"] == "ask/hello"
    assert "image_url" not in recorded["json"]
    assert recorded["headers"]["X-Request-ID"] == "req-1"


@pytest.mark.asyncio
async def test_gateway_timeout(monkeypatch, env):
    timeout_exc = aiohttp.ServerTimeoutError("timeout")

    def fake_session_factory(*args, **kwargs):
        return FakeSession(exc=timeout_exc, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(aiohttp, "ClientSession", fake_session_factory)

    out = await run_gateway_command(user_id="1", command_text="ask/slow")
    assert out == GATEWAY_UNAVAILABLE_MESSAGE


@pytest.mark.asyncio
async def test_gateway_4xx_5xx(monkeypatch, env):
    def bad_request_factory(*args, **kwargs):
        return FakeSession(response=FakeResponse(400, '{"error": "bad input"}'), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(aiohttp, "ClientSession", bad_request_factory)
    out_400 = await run_gateway_command(user_id="1", command_text="ask/hi")
    assert out_400 == "❌ bad input"

    def server_error_factory(*args, **kwargs):
        return FakeSession(response=FakeResponse(503, '{"error": "downstream"}'), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(aiohttp, "ClientSession", server_error_factory)
    out_503 = await run_gateway_command(user_id="1", command_text="ask/hi")
    assert out_503 == "❌ AI gateway failed while processing your command."


@pytest.mark.asyncio
async def test_malformed_payload_response(monkeypatch, env):
    def malformed_json_factory(*args, **kwargs):
        return FakeSession(response=FakeResponse(200, "not-json"), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(aiohttp, "ClientSession", malformed_json_factory)

    out = await run_gateway_command(user_id="1", command_text="ask/hello")
    assert out == "❌ Gateway returned invalid JSON."


@pytest.mark.asyncio
async def test_network_failure(monkeypatch, env):
    err = aiohttp.ClientConnectionError("network down")

    def failing_factory(*args, **kwargs):
        return FakeSession(exc=err, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(aiohttp, "ClientSession", failing_factory)

    out = await run_gateway_command(user_id="1", command_text="ask/hello")
    assert out == GATEWAY_UNAVAILABLE_MESSAGE


@pytest.mark.asyncio
async def test_analyze_detect_payload_schema(monkeypatch, env):
    records = []

    def session_factory(*args, **kwargs):
        rec = {}
        records.append(rec)
        return FakeSession(
            response=FakeResponse(200, json.dumps({"response": "ok"})),
            recorder=rec,
            timeout=kwargs.get("timeout"),
        )

    monkeypatch.setattr(aiohttp, "ClientSession", session_factory)

    await call_ai_gateway(user_id=99, command_text="analyze/some text", request_id="a")
    await call_ai_gateway(
        user_id=99,
        command_text="detect/image",
        image_url="https://img/x.png",
        request_id="b",
    )

    analyze_payload = records[0]["json"]
    detect_payload = records[1]["json"]

    assert analyze_payload["user_id"] == "99"
    assert isinstance(analyze_payload["user_id"], str)
    assert analyze_payload["command_text"] == "analyze/some text"
    assert "image_url" not in analyze_payload

    assert detect_payload["command_text"] == "detect/image"
    assert detect_payload["image_url"] == "https://img/x.png"


def test_gateway_url_normalizes_base_path(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_URL", "http://gateway:8080")
    monkeypatch.setattr("app.commands.os.path.exists", lambda *_: False)
    assert _gateway_url() == "http://gateway:8080/process-command"


def test_gateway_url_rewrites_loopback_in_container(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_URL", "http://127.0.0.1:8080/process-command")
    monkeypatch.setattr("app.commands.os.path.exists", lambda *_: True)
    assert _gateway_url() == "http://host.docker.internal:8080/process-command"
