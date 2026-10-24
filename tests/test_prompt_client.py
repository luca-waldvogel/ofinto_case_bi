from types import SimpleNamespace
from unittest.mock import Mock

from pydantic import BaseModel

from ofinto.clients import PromptClient
from ofinto.config import PromptClientConfig
from ofinto.programs import PromptProgram


class Answer(BaseModel):
    message: str


class AnswerProgram(PromptProgram[str, Answer]):
    system_prompt = "Beantworte die Frage."
    user_prompt = "Frage: {input}"
    return_type = Answer


def test_structured_prompt_uses_config_and_closes_client(monkeypatch):
    factory = Mock()
    monkeypatch.setattr("ofinto.clients.prompt.OpenAI", factory)
    factory.return_value.responses.parse.return_value = SimpleNamespace(
        status="completed", output_parsed=Answer(message="ja"),
    )

    with PromptClient(AnswerProgram, PromptClientConfig(api_key="test-key")) as client:
        assert client.run("Warum?").message == "ja"

    factory.return_value.responses.parse.assert_called_once()
    factory.return_value.close.assert_called_once()
