import os
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True)
class PromptClientConfig:
    model: str = "gpt-5-mini"
    timeout: float = 60.0
    max_retries: int = 2
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    store: bool = False

    @classmethod
    def from_env(cls) -> "PromptClientConfig":
        values = {**dotenv_values(Path.cwd() / ".env"), **os.environ}
        defaults = cls()
        return cls(
            model=values.get("OPENAI_MODEL") or defaults.model,
            timeout=float(values.get("OPENAI_TIMEOUT") or defaults.timeout),
            max_retries=int(values.get("OPENAI_MAX_RETRIES") or defaults.max_retries),
            api_key=values.get("OPENAI_API_KEY"),
            base_url=values.get("OPENAI_BASE_URL") or None,
        )
