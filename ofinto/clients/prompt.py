"""Einheitliche Ausführung typisierter Prompt-Programme über die Responses API."""

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from typing import Generic, cast

from dotenv import load_dotenv
from openai import APIError, APIStatusError, OpenAI
from pydantic import BaseModel

from ..programs.base import InputT, OutputT, PromptProgram

DEFAULT_MODEL = "gpt-5-mini"
logger = logging.getLogger(__name__)
_WAIT_LOG_INTERVAL = 15.0


@contextmanager
def _request_progress(program: str):
    """Regelmäßige Wartemeldung; der Thread führt keine API-Aufrufe aus."""
    stopped = Event()

    def heartbeat() -> None:
        while not stopped.wait(_WAIT_LOG_INTERVAL):
            logger.info(
                "%s: warte auf Modellantwort (einschließlich eventueller SDK-Retries)",
                program,
            )

    thread = None
    if logger.isEnabledFor(logging.INFO):
        thread = Thread(target=heartbeat, name="prompt-progress", daemon=True)
        thread.start()
    try:
        yield
    finally:
        stopped.set()
        if thread is not None:
            thread.join()


class PromptError(RuntimeError):
    """Fehler eines Programms mit dem betroffenen Ausführungsschritt."""


class PromptClient(Generic[InputT, OutputT]):
    """Eine Programmklasse konfigurieren und mit run(input) ausführen.

    Ein injizierter OpenAI-Transport kann zwischen Instanzen geteilt werden und
    wird vom Aufrufer geschlossen. Ein eigener Transport wird zwischen Aufrufen
    wiederverwendet und mit close() oder beim Verlassen des with-Blocks geschlossen.
    """

    def __init__(
        self,
        program: type[PromptProgram[InputT, OutputT]],
        *,
        model: str | None = None,
        transport: OpenAI | None = None,
    ) -> None:
        load_dotenv(Path.cwd() / ".env", override=False)
        self.program = program()
        self.model = model or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
        # GPT-5 zählt auch interne Reasoning-Tokens zum Ausgabelimit.
        self.max_output_tokens = 25_000 if self.model.startswith("gpt-5") else 4096
        self._transport = transport
        self._owns_transport = transport is None
        result_type = self.program.return_type
        if result_type is not str and not (
            isinstance(result_type, type) and issubclass(result_type, BaseModel)
        ):
            raise TypeError("return_type muss str oder ein Pydantic-Modell sein")
        self.response_model: str | None = None
        self.usage: dict | None = None

    def __enter__(self) -> "PromptClient[InputT, OutputT]":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        """Nur selbst erstellte SDK-Verbindungen schließen."""
        if self._owns_transport and self._transport is not None:
            self._transport.close()
            self._transport = None

    def _validate(self, result: object) -> OutputT:
        result_type = self.program.return_type
        if not isinstance(result, result_type):
            raise ValueError(f"Antwort entspricht nicht {result_type.__name__}")
        if isinstance(result, BaseModel):
            # Auch nachträglich veränderte Modellinstanzen erneut validieren.
            result = result_type.model_validate(result.model_dump(warnings=False), strict=True)
        return cast(OutputT, result)

    def run(self, value: InputT) -> OutputT:
        """Vorbereiten, darstellen, aufrufen, validieren und nachbereiten."""
        stage = "prepare"
        program_name = type(self.program).__name__
        self.response_model = None
        self.usage = None
        try:
            prepared = self.program.prepare(value)
            stage = "render_user_prompt"
            user_prompt = self.program.render_user_prompt(prepared)
            stage = "Konfiguration"
            if self._transport is None:
                if not os.environ.get("OPENAI_API_KEY"):
                    raise ValueError("OPENAI_API_KEY fehlt")
                self._transport = OpenAI(timeout=60.0, max_retries=2)
            stage = "Modellaufruf"
            kwargs = {
                "model": self.model,
                "input": [
                    {"role": "system", "content": self.program.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "store": False,
                "max_output_tokens": self.max_output_tokens,
            }
            logger.info(
                "%s: sende Modellanfrage (Modell=%s; Ausgabelimit=%d Tokens)",
                program_name, self.model, self.max_output_tokens,
            )
            with _request_progress(program_name):
                if self.program.return_type is str:
                    response = self._transport.responses.create(**kwargs)
                else:
                    response = self._transport.responses.parse(
                        **kwargs, text_format=self.program.return_type,
                    )
            logger.info(
                "%s: API-Antwort erhalten (Status=%s)",
                program_name, response.status,
            )
            stage = "Antwortvalidierung"
            if response.status != "completed":
                raise ValueError(f"Unvollständige Antwort (Status: {response.status})")
            if any(
                getattr(part, "type", None) == "refusal"
                for item in response.output
                for part in getattr(item, "content", [])
            ):
                raise ValueError("Das Modell hat die Anfrage abgelehnt")
            result = (
                response.output_text if self.program.return_type is str
                else response.output_parsed
            )
            if result is None or result == "":
                raise ValueError("Leere Modellantwort")
            self.response_model = response.model
            self.usage = response.usage.model_dump() if response.usage else None
            stage = "postprocess"
            return self._validate(self.program.postprocess(cast(OutputT, result)))
        except Exception as error:
            # API-Fehler können Requestdetails enthalten; diese nicht protokollieren.
            detail = type(error).__name__ if isinstance(error, APIError) else str(error)
            if isinstance(error, APIStatusError):
                detail += f" (HTTP {error.status_code}, Code={error.code or 'unbekannt'}, Modell={self.model})"
                if error.status_code == 404:
                    detail += ": Modell nicht verfügbar, fehlende Modellberechtigung oder falscher API-Endpunkt"
                if error.request_id:
                    detail += f"; Request-ID={error.request_id}"
            logger.error(
                "%s: Fehler in %s (%s)",
                program_name, stage, type(error).__name__,
            )
            raise PromptError(f"{type(self.program).__name__} / {stage}: {detail}") from error
