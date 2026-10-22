from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIError
from pydantic import BaseModel
from pydantic import Field

from ofinto.clients import PromptClient
from ofinto.clients import PromptError
from ofinto.config import PromptClientConfig
from ofinto.programs import PromptProgram


class Answer(BaseModel):
    message: str = Field(description="Eine kurze Antwort.")


class AnswerProgram(PromptProgram[str, Answer]):
    system_prompt = "Beantworte die Frage."
    user_prompt = "Frage: {input}"
    return_type = Answer

    def prepare(self, value):
        return value.strip()

    def postprocess(self, result):
        return Answer(message=result.message.upper())


class TextProgram(PromptProgram[str, str]):
    system_prompt = "Fasse zusammen."
    return_type = str


@pytest.fixture
def sdk_factory(monkeypatch):
    factory = Mock()
    monkeypatch.setattr("ofinto.clients.prompt.OpenAI", factory)
    return factory


def test_structured_prompt_uses_config_and_hooks(sdk_factory):
    sdk = sdk_factory.return_value
    config = PromptClientConfig(model="test-model", timeout=90, api_key="test-key")
    sdk.responses.parse.return_value = SimpleNamespace(
        status="completed", output_parsed=Answer(message="ja"),
    )

    with PromptClient(AnswerProgram, config) as client:
        result = client.run("  Warum?  ")

    assert result.message == "JA"
    sdk_factory.assert_called_once_with(api_key="test-key", base_url=None, timeout=90, max_retries=2)
    sdk.responses.parse.assert_called_once_with(
        model="test-model",
        input=[
            {"role": "system", "content": "Beantworte die Frage."},
            {"role": "user", "content": "Frage: Warum?"},
        ],
        store=False,
        text_format=Answer,
    )
    sdk.close.assert_called_once()


def test_text_prompt_returns_string(sdk_factory):
    sdk = sdk_factory.return_value
    sdk.responses.create.return_value = SimpleNamespace(
        status="completed", output_text="Zusammenfassung",
    )

    with PromptClient(TextProgram, PromptClientConfig(api_key="test-key")) as client:
        result = client.run("Gesprächstext")

    assert result == "Zusammenfassung"


def test_api_error_shows_only_server_message(sdk_factory):
    sdk = sdk_factory.return_value
    sdk.responses.parse.side_effect = APIError(
        "Vollständige Fehlerdetails",
        request=httpx.Request("POST", "https://example.test/v1/responses"),
        body={"message": "Modell nicht verfügbar", "request": "Vertrauliches Transkript"},
    )

    with pytest.raises(PromptError) as error:
        with PromptClient(AnswerProgram, PromptClientConfig(api_key="test-key")) as client:
            client.run("Gesprächstext")

    assert str(error.value) == "AnswerProgram: APIError: Modell nicht verfügbar"
    sdk.close.assert_called_once()
