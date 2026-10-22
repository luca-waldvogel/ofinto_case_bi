import logging
from typing import Generic, cast

from openai import APIError, OpenAI
from pydantic import BaseModel

from ..config import PromptClientConfig
from ..programs import InputT, OutputT, PromptProgram

logger = logging.getLogger(__name__)


class PromptError(RuntimeError):
    """Fehler bei der Ausführung eines Prompt-Programms."""


class PromptClient(Generic[InputT, OutputT]):
    """Eine Programmklasse konfigurieren und mit run(input) ausführen.

    Die SDK-Verbindung wird zwischen Aufrufen wiederverwendet und mit close()
    oder beim Verlassen des with-Blocks geschlossen.
    """

    def __init__(
        self,
        program: type[PromptProgram[InputT, OutputT]],
        config: PromptClientConfig | None = None,
    ) -> None:
        self.program = program()
        self.config = config if config is not None else PromptClientConfig.from_env()
        result_type = self.program.return_type
        if result_type is not str and not (
            isinstance(result_type, type) and issubclass(result_type, BaseModel)
        ):
            raise TypeError("return_type muss str oder ein Pydantic-Modell sein")
        if not self.config.api_key:
            raise ValueError("OPENAI_API_KEY fehlt")
        self._transport = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            max_retries=self.config.max_retries,
        )

    def __enter__(self) -> "PromptClient[InputT, OutputT]":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        """Die SDK-Verbindung schließen."""
        self._transport.close()

    def run(self, value: InputT) -> OutputT:
        """Prompt ausführen und die nachbereitete Antwort zurückgeben."""
        program_name = type(self.program).__name__
        try:
            prepared = self.program.prepare(value)
            user_prompt = self.program.render_user_prompt(prepared)
            kwargs = {
                "model": self.config.model,
                "input": [
                    {"role": "system", "content": self.program.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "store": self.config.store,
            }
            logger.info(f"{program_name}: sende Modellanfrage (Modell={self.config.model})")
            if self.program.return_type is str:
                response = self._transport.responses.create(**kwargs)
            else:
                response = self._transport.responses.parse(
                    **kwargs, text_format=self.program.return_type,
                )
            logger.info(f"{program_name}: API-Antwort erhalten (Status={response.status})")
            if response.status != "completed":
                raise ValueError(f"Unvollständige Antwort (Status: {response.status})")
            result = (
                response.output_text if self.program.return_type is str
                else response.output_parsed
            )
            if result is None or result == "":
                raise ValueError("Keine verwertbare Modellantwort (leer oder abgelehnt)")
            return self.program.postprocess(cast(OutputT, result))
        except Exception as error:
            detail = str(error)
            if isinstance(error, APIError):
                message = error.body.get("message", "API-Aufruf fehlgeschlagen") if isinstance(error.body, dict) else "API-Aufruf fehlgeschlagen"
                detail = f"{type(error).__name__}: {message}"
            logger.error(f"{program_name}: {detail}")
            raise PromptError(f"{program_name}: {detail}") from None
