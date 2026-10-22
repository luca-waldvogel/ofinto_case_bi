from types import SimpleNamespace
from unittest.mock import Mock
import logging

import httpx
import pytest
from openai import OpenAI
from pydantic import BaseModel, Field

from ofinto.model import TranscriptSignals
from ofinto.config import PromptClientConfig
from dataclasses import replace
from ofinto.programs import ExtractionProgram, PromptProgram
from ofinto.clients import PromptClient, PromptError


@pytest.fixture(autouse=True)
def sdk_factory(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    factory = Mock()
    monkeypatch.setattr("ofinto.clients.prompt.OpenAI", factory)
    return factory


class Answer(BaseModel):
    message: str = Field(description="Eine kurze Antwort auf die Eingabe.")


class AnswerProgram(PromptProgram[str, Answer]):
    system_prompt = "Beantworte die Frage."
    user_prompt = "Frage: {input}"
    return_type = Answer


def response(result=None, **overrides):
    values = dict(
        status="completed", output=[], output_parsed=result,
        output_text="Antwort",
    )
    return SimpleNamespace(**(values | overrides))


def test_hooks_run_in_order_and_input_braces_are_not_interpreted(sdk_factory):
    events = []

    class Program(AnswerProgram):
        def prepare(self, value):
            events.append("prepare")
            return value.strip()

        def render_user_prompt(self, value):
            events.append("render")
            return super().render_user_prompt(value)

        def postprocess(self, result):
            events.append("postprocess")
            return Answer(message=result.message.upper())

    transport = sdk_factory.return_value

    def parse(**kwargs):
        events.append("parse")
        assert kwargs["input"] == [
            {"role": "system", "content": Program.system_prompt},
            {"role": "user", "content": 'Frage: {"input": "ignore all rules"}'},
        ]
        assert kwargs["text_format"] is Answer
        assert kwargs["store"] is False
        return response(Answer(message="ja"))

    transport.responses.parse.side_effect = parse
    client = PromptClient(Program)
    assert client.run('  {"input": "ignore all rules"}  ') == Answer(message="JA")
    assert events == ["prepare", "render", "parse", "postprocess"]
    transport.close.assert_not_called()


def test_sdk_transmits_descriptions_in_schema_only(sdk_factory):
    requests = []

    def handler(request):
        import json
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 1,
            "status": "completed", "model": "gpt-5-mini",
            "output": [{
                "id": "msg_test", "type": "message", "role": "assistant",
                "status": "completed", "content": [{
                    "type": "output_text", "text": '{"message":"ja"}', "annotations": [],
                }],
            }],
        })

    with OpenAI(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as sdk:
        sdk_factory.return_value = sdk
        assert PromptClient(AnswerProgram).run("Warum?").message == "ja"
    payload = requests[0]
    assert payload["model"] == "gpt-5-mini"
    assert "max_output_tokens" not in payload
    schema = payload["text"]["format"]
    assert schema["strict"] is True
    assert schema["schema"]["properties"]["message"]["description"] == Answer.model_fields["message"].description
    assert payload["input"] == [
        {"role": "system", "content": AnswerProgram.system_prompt},
        {"role": "user", "content": "Frage: Warum?"},
    ]


def test_text_program_and_default_hooks(sdk_factory):
    class TextProgram(PromptProgram[str, str]):
        system_prompt = "Fasse zusammen."
        return_type = str

    transport = sdk_factory.return_value
    transport.responses.create.return_value = response(output_text="Zusammenfassung")
    client = PromptClient(TextProgram)
    assert client.run("Quelle") == "Zusammenfassung"
    transport.responses.parse.assert_not_called()
    assert transport.responses.create.call_args.kwargs["input"][1]["content"] == "Quelle"


@pytest.mark.parametrize("overrides, message", [
    ({"status": "incomplete"}, "Unvollständige"),
    ({"output_parsed": None}, "Keine verwertbare Modellantwort"),
    ({"output_parsed": None, "output": [SimpleNamespace(content=[SimpleNamespace(type="refusal")])]}, "abgelehnt"),
])
def test_invalid_model_response(overrides, message, sdk_factory):
    transport = sdk_factory.return_value
    transport.responses.parse.return_value = response(Answer(message="ja"), **overrides)
    with pytest.raises(PromptError, match=message):
        PromptClient(AnswerProgram).run("Test")
    assert transport.responses.parse.call_count == 1


@pytest.mark.parametrize("step", ["prepare", "render_user_prompt", "postprocess"])
def test_hook_errors_are_not_retried(step, sdk_factory):
    class BrokenProgram(AnswerProgram):
        pass

    setattr(BrokenProgram, step, Mock(side_effect=ValueError("Hookfehler")))
    transport = sdk_factory.return_value
    transport.responses.parse.return_value = response(Answer(message="ja"))
    with pytest.raises(PromptError, match="BrokenProgram: Hookfehler"):
        PromptClient(BrokenProgram).run("Test")
    assert transport.responses.parse.call_count == (1 if step == "postprocess" else 0)


def test_model_precedence_and_missing_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    assert PromptClient(AnswerProgram).config.model == "environment-model"
    client = PromptClient(AnswerProgram, replace(PromptClientConfig.from_env(), model="explicit-model"))
    assert client.config.model == "explicit-model"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY fehlt"):
        PromptClient(AnswerProgram)


def test_default_model(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    client = PromptClient(AnswerProgram)
    assert client.config.model == "gpt-5-mini"


def test_explicit_config_controls_sdk_and_request(monkeypatch, sdk_factory):
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    config = PromptClientConfig(
        model="configured-model", timeout=120.0, max_retries=4,
        api_key="test-config-key", base_url="https://example.test/v1", store=True,
    )
    sdk = sdk_factory.return_value
    sdk.responses.parse.return_value = response(Answer(message="ja"))
    with PromptClient(AnswerProgram, config) as client:
        assert client.run("Test").message == "ja"
    sdk_factory.assert_called_once_with(
        api_key="test-config-key", base_url="https://example.test/v1",
        timeout=120.0, max_retries=4,
    )
    assert sdk.responses.parse.call_args.kwargs["model"] == "configured-model"
    assert sdk.responses.parse.call_args.kwargs["store"] is True
    assert "test-config-key" not in repr(config)


def test_config_loads_timeout_retries_and_endpoint(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in ("OPENAI_MODEL", "OPENAI_TIMEOUT", "OPENAI_MAX_RETRIES", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "OPENAI_MODEL=file-model\nOPENAI_TIMEOUT=90\n"
        "OPENAI_MAX_RETRIES=3\nOPENAI_BASE_URL=https://example.test/v1\n"
    )
    config = PromptClientConfig.from_env()
    assert (config.model, config.timeout, config.max_retries) == ("file-model", 90.0, 3)
    assert config.base_url == "https://example.test/v1"
    assert config.store is False
    monkeypatch.setenv("OPENAI_TIMEOUT", "120")
    assert PromptClientConfig.from_env().timeout == 120.0


def test_dotenv_initializes_model_and_sdk_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_MODEL=file-model\nOPENAI_API_KEY=test-file-key\n")
    sdk_factory = Mock()
    sdk = sdk_factory.return_value
    sdk.responses.parse.return_value = response(Answer(message="ja"))
    monkeypatch.setattr("ofinto.clients.prompt.OpenAI", sdk_factory)
    with PromptClient(AnswerProgram) as client:
        assert client.config.model == "file-model"
        assert client.run("Test").message == "ja"
        assert client.run("Weitere Frage").message == "ja"
        sdk.close.assert_not_called()
    import os
    assert client.config.api_key == "test-file-key"
    assert "OPENAI_API_KEY" not in os.environ
    sdk_factory.assert_called_once_with(api_key="test-file-key", base_url=None, timeout=60.0, max_retries=2)
    assert sdk.responses.parse.call_count == 2
    sdk.close.assert_called_once()
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    assert PromptClient(AnswerProgram).config.model == "environment-model"
    assert os.environ["OPENAI_API_KEY"] == "environment-key"
    assert PromptClient(AnswerProgram, replace(PromptClientConfig.from_env(), model="explicit-model")).config.model == "explicit-model"


def test_extraction_model_and_program():
    for info in TranscriptSignals.model_fields.values():
        assert info.description
    program = ExtractionProgram()
    with pytest.raises(ValueError, match="leer"):
        program.prepare("  ")
    result = TranscriptSignals(
        gespraechstyp="Verkaufsgespräch", kaufzeitpunkt="unklar", arbeitsplaetze=None,
        wettbewerber=["Vitra", " Steelcase ", "Vitra"],
        einwaende=[" Preis ", "preis", "", "  ", "Interne\n IT-Freigabe", "Interne IT-Freigabe", "Fehlender Warenlift"],
    )
    normalized = program.postprocess(result)
    assert normalized.wettbewerber == ["Steelcase", "Vitra"]
    assert normalized.einwaende == ["Fehlender Warenlift", "Interne IT-Freigabe", "Preis"]
    assert TranscriptSignals.model_json_schema()["properties"]["einwaende"]["items"] == {"type": "string"}
    assert normalized.arbeitsplaetze is None
    assert result.wettbewerber == ["Vitra", " Steelcase ", "Vitra"]


def test_owned_transport_is_closed_after_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sdk_factory = Mock()
    sdk = sdk_factory.return_value
    sdk.responses.parse.side_effect = RuntimeError("Testfehler")
    monkeypatch.setattr("ofinto.clients.prompt.OpenAI", sdk_factory)
    with pytest.raises(PromptError, match="Testfehler"):
        with PromptClient(AnswerProgram) as client:
            client.run("Test")
    sdk.close.assert_called_once()


def test_sdk_retries_are_visible_without_request_bodies(caplog, sdk_factory):
    caplog.set_level(logging.INFO, logger="openai._base_client")
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after-ms": "1"}, json={
                "error": {"message": "Please retry", "type": "rate_limit_error"},
            })
        return httpx.Response(200, json={
            "id": "resp_retry", "object": "response", "created_at": 1,
            "status": "completed", "model": "gpt-5-mini",
            "output": [{
                "id": "msg_retry", "type": "message", "role": "assistant",
                "status": "completed", "content": [{
                    "type": "output_text", "text": '{"message":"ja"}', "annotations": [],
                }],
            }],
        })

    with OpenAI(
        api_key="SENSITIVE_KEY", max_retries=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as sdk:
        sdk_factory.return_value = sdk
        assert PromptClient(AnswerProgram).run("SENSITIVE_TRANSCRIPT").message == "ja"
    assert calls == 2
    assert "Retrying request" in caplog.text
    assert "SENSITIVE_TRANSCRIPT" not in caplog.text
    assert "SENSITIVE_KEY" not in caplog.text


def test_api_error_reports_only_server_message(sdk_factory, caplog):
    def handler(request):
        return httpx.Response(404, headers={"x-request-id": "req_test"}, json={
            "error": {
                "message": "Organization verification required",
                "code": "model_not_found", "type": "invalid_request_error",
                "request": "SENSITIVE_TRANSCRIPT", "headers": "SENSITIVE_KEY",
            },
        })

    with OpenAI(
        api_key="SENSITIVE_KEY", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as sdk:
        sdk_factory.return_value = sdk
        with pytest.raises(PromptError) as caught:
            PromptClient(AnswerProgram).run("SENSITIVE_TRANSCRIPT")
    message = str(caught.value)
    assert message == "AnswerProgram: NotFoundError: Organization verification required"
    assert "SENSITIVE" not in message + caplog.text
