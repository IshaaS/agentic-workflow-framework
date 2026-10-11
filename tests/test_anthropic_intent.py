"""Sprint 06 Anthropic intent provider tests. Fully offline: the SDK client is replaced.

Tests that construct real SDK exception objects need the optional ``anthropic``
package (installed in CI via the ``[llm]`` extra) and are skipped without it.
"""

import json
import logging
import subprocess
import sys
from types import SimpleNamespace

import pytest

from agentctl_core import (
    AgentManifest,
    AgentRegistry,
    BaseAgent,
    Capability,
    GoalSpec,
    InputSpec,
    IntentProviderConfigError,
    IntentProviderError,
    ResolvedIntent,
    build_intent_catalog,
)
from agentctl_core.providers import anthropic as provider_module
from agentctl_core.providers.anthropic import (
    DEFAULT_MODEL,
    FALLBACK_BETA,
    MISSING_KEY_MESSAGE,
    SYSTEM_PROMPT,
    AnthropicIntentProvider,
    response_schema,
)

SECRET = "sk-ant-api03-TEST-SECRET-do-not-print"


class MetaAgent(BaseAgent):
    def __init__(self, name, capability):
        self._manifest = AgentManifest(name, "1.0", name, [capability])

    @property
    def manifest(self):
        return self._manifest

    def run(self, inputs, context):
        raise AssertionError("never run")


@pytest.fixture(scope="module")
def catalog():
    registry = AgentRegistry()
    registry.register(MetaAgent("extractor", Capability(
        "document.extract", ["document_path"], ["extracted_text"],
        input_specs=[InputSpec("document_path", "Path of the document")],
    )))
    registry.register(MetaAgent("summarizer", Capability(
        "document.summarize", ["extracted_text"], ["summary"],
        optional_inputs=["tone"],
        input_specs=[InputSpec("tone", "Tone", allowed_values=["brief", "detailed"])],
        goals=[GoalSpec("summary", "Summarize a document")],
    )))
    return build_intent_catalog(registry)


def text_response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="test-model",
        _request_id="req_test",
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
    )


class FakeMessages:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeClient:
    """Mimics ``anthropic.Anthropic`` for messages.create and beta.messages.create."""

    def __init__(self, outcome):
        self.messages = FakeMessages(outcome)
        self.beta = SimpleNamespace(messages=FakeMessages(outcome))

    @property
    def calls(self):
        return self.messages.calls + self.beta.messages.calls


def provider_with(outcome, model=DEFAULT_MODEL):
    client = FakeClient(outcome)
    return AnthropicIntentProvider(api_key=SECRET, model=model, client=client), client


GOOD = json.dumps({"goal": "summary", "parameters": {"document_path": "report.pdf"}})


# Configuration --------------------------------------------------------------------


@pytest.mark.parametrize("environ", [{}, {"ANTHROPIC_API_KEY": ""}, {"ANTHROPIC_API_KEY": "  \t"}])
def test_missing_key(environ):
    with pytest.raises(IntentProviderConfigError) as excinfo:
        AnthropicIntentProvider.from_environment(environ)

    assert str(excinfo.value) == MISSING_KEY_MESSAGE
    assert "agentctl run workflow --goal OUTPUT_KEY --input KEY=VALUE" in str(excinfo.value)


def test_environment_configuration():
    pytest.importorskip("anthropic")  # from_environment also checks the SDK is installed
    default = AnthropicIntentProvider.from_environment({"ANTHROPIC_API_KEY": SECRET})
    custom = AnthropicIntentProvider.from_environment(
        {"ANTHROPIC_API_KEY": SECRET, "ANTHROPIC_MODEL": " claude-sonnet-5-5 "}
    )

    assert default.model == DEFAULT_MODEL == "claude-opus-5-5"
    assert custom.model == "claude-sonnet-5-5"


def test_missing_sdk_is_a_configuration_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes `import anthropic` fail

    with pytest.raises(IntentProviderConfigError, match=r"pip install -e './framework\[llm\]'"):
        AnthropicIntentProvider.from_environment({"ANTHROPIC_API_KEY": SECRET})
    with pytest.raises(IntentProviderConfigError, match="need the Anthropic SDK"):
        AnthropicIntentProvider(api_key=SECRET, client=FakeClient(text_response(GOOD))).resolve("x", None)


def test_importing_core_does_not_import_the_sdk():
    code = (
        "import sys, agentctl_core, agentctl_core.cli, agentctl_core.providers.anthropic; "
        "print('anthropic' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)

    assert result.stdout.strip() == "False"


# Request shape -------------------------------------------------------------------------


def test_successful_resolution(catalog):
    pytest.importorskip("anthropic")
    provider, _ = provider_with(text_response(GOOD))

    assert provider.resolve("Summarize report.pdf", catalog) == ResolvedIntent(
        "summary", {"document_path": "report.pdf"}
    )


def test_request_parameters(catalog):
    pytest.importorskip("anthropic")
    provider, client = provider_with(text_response(GOOD))
    provider.resolve("Summarize report.pdf briefly", catalog)

    (call,) = client.beta.messages.calls
    assert client.messages.calls == []
    assert call["model"] == "claude-opus-5-5"
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert call["system"] == SYSTEM_PROMPT
    assert call["max_tokens"] == 4096
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": response_schema(catalog)}
    (message,) = call["messages"]
    assert message["role"] == "user"
    assert "<request>\nSummarize report.pdf briefly\n</request>" in message["content"]
    assert json.dumps(catalog.to_dict(), indent=2) in message["content"]
    assert "thinking" not in call and "temperature" not in call


def test_model_without_server_fallback_uses_plain_messages_api(catalog):
    pytest.importorskip("anthropic")
    provider, client = provider_with(text_response(GOOD), model="claude-haiku-5-5")
    provider.resolve("Summarize report.pdf", catalog)

    (call,) = client.messages.calls
    assert client.beta.messages.calls == []
    assert call["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in call and "betas" not in call


def test_default_client_is_built_lazily_with_key_timeout_and_retries(catalog, monkeypatch):
    sdk = pytest.importorskip("anthropic")
    built = []

    def fake_anthropic(**kwargs):
        built.append(kwargs)
        return FakeClient(text_response(GOOD))

    monkeypatch.setattr(sdk, "Anthropic", fake_anthropic)
    provider = AnthropicIntentProvider.from_environment({"ANTHROPIC_API_KEY": SECRET})
    assert built == []  # nothing is constructed until a request is resolved

    provider.resolve("Summarize report.pdf", catalog)

    assert built == [{"api_key": SECRET, "timeout": 30.0, "max_retries": 1}]


def test_response_schema(catalog):
    schema = response_schema(catalog)

    assert schema["required"] == ["goal", "parameters"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["goal"] == {"type": "string"}
    parameters = schema["properties"]["parameters"]
    assert parameters["properties"] == {"document_path": {"type": "string"}, "tone": {"type": "string"}}
    # Every key required, in catalog order: structured outputs write keys in schema order with
    # optional keys last, which let the model skip a parameter it had not reached yet.
    assert parameters["required"] == ["document_path", "tone"]
    assert list(parameters["properties"]) == parameters["required"]
    assert parameters["additionalProperties"] is False
    # No enums: an unsupported value must reach validation instead of being forced onto an allowed one.
    assert "enum" not in json.dumps(schema)


def test_system_prompt_is_generic():
    lowered = SYSTEM_PROMPT.lower()
    for word in ("outfit", "city", "activity", "style", "weather", "cloth", "summary", "document"):
        assert word not in lowered


# Malformed answers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "response, message",
    [
        (text_response("not json"), "not valid JSON"),
        (text_response('["summary"]'), "exactly the fields"),
        (text_response('{"goal": "summary"}'), "exactly the fields"),
        (text_response('{"goal": "summary", "parameters": {}, "steps": []}'), "exactly the fields"),
        (SimpleNamespace(stop_reason="end_turn", content=[]), "no text answer"),
        (text_response(GOOD, stop_reason="refusal"), "declined"),
        (text_response('{"goal": "sum', stop_reason="max_tokens"), "cut off"),
    ],
)
def test_malformed_answers(catalog, response, message):
    pytest.importorskip("anthropic")
    provider, _ = provider_with(response)

    with pytest.raises(IntentProviderError, match=message) as excinfo:
        provider.resolve("Summarize report.pdf", catalog)
    assert not isinstance(excinfo.value, IntentProviderConfigError)


# SDK errors -------------------------------------------------------------------------------


def sdk_errors():
    sdk = pytest.importorskip("anthropic")
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    def status(cls, code, body=None):
        return cls(f"Error code: {code}", response=httpx2.Response(code, request=request), body=body)

    return [
        (status(sdk.AuthenticationError, 401), IntentProviderConfigError, "authentication failed"),
        (status(sdk.PermissionDeniedError, 403), IntentProviderConfigError, "not permitted"),
        (status(sdk.NotFoundError, 404), IntentProviderConfigError, "model 'claude-opus-5-5' was not found"),
        (status(sdk.RateLimitError, 429), IntentProviderError, "rate limit"),
        (sdk.APITimeoutError(request=request), IntentProviderError, "did not respond within 30 seconds"),
        (sdk.APIConnectionError(request=request), IntentProviderError, "could not connect"),
        (status(sdk.BadRequestError, 400), IntentProviderError, "rejected the request"),
        (status(sdk.InternalServerError, 500), IntentProviderError, r"HTTP 500"),
        (status(sdk.APIStatusError, 529), IntentProviderError, r"HTTP 529"),
    ]


@pytest.mark.parametrize("index", range(9))
def test_sdk_errors_are_translated(catalog, caplog, index):
    error, expected_type, message = sdk_errors()[index]
    provider, _ = provider_with(error)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(expected_type, match=message) as excinfo:
            provider.resolve("Summarize report.pdf", catalog)

    assert excinfo.value.__cause__ is error
    if expected_type is IntentProviderError:
        assert not isinstance(excinfo.value, IntentProviderConfigError)
    assert SECRET not in str(excinfo.value)
    assert SECRET not in caplog.text


def test_successful_call_logs_no_secret_or_request_text(catalog, caplog):
    pytest.importorskip("anthropic")
    provider, _ = provider_with(text_response(GOOD))

    with caplog.at_level(logging.DEBUG):
        provider.resolve("Summarize the confidential report.pdf", catalog)

    assert "req_test" in caplog.text
    assert SECRET not in caplog.text
    assert "confidential" not in caplog.text


def test_provider_module_has_no_application_names():
    source = open(provider_module.__file__).read().lower()
    for word in ("outfit", "city", "activity", "weather", "cloth", "wardrobe"):
        assert word not in source
