import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from dotenv import dotenv_values


@dataclass(frozen=True)
class PotentialConfig:
    rule_version: str = "2"
    workplaces_per_employee_min: Decimal = Decimal("0.7")
    workplaces_per_employee_max: Decimal = Decimal("1.0")
    workplace_share_per_item: Decimal = Decimal("0.5")
    replacement_years: int = 10
    days_per_year: int = 365


@dataclass(frozen=True)
class PromptClientConfig:
    model: str = "gpt-5-mini"
    timeout: float = 60.0
    max_retries: int = 2
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    store: bool = False
    model_env: ClassVar[str] = "OPENAI_MODEL"

    @classmethod
    def from_env(cls) -> "PromptClientConfig":
        values = {**dotenv_values(Path.cwd() / ".env"), **os.environ}
        return cls(
            api_key=values.get("OPENAI_API_KEY"),
            base_url=values.get("OPENAI_BASE_URL") or None,
        )


@dataclass(frozen=True)
class ExtractionPromptConfig(PromptClientConfig):
    """Konfiguration für die Transkriptextraktion."""


@dataclass(frozen=True)
class AssistantPromptConfig(PromptClientConfig):
    """Konfiguration für SQL- und Antwortprompts des Assistenten."""
    model: str = "gpt-6.1-sol"
