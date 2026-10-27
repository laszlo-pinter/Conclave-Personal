# src/conclave/domain/agent.py

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class Agent:
    """LLM-Agent-Konfiguration (Provider, Model, API-Key, Presets).

    Agents werden in der DB gespeichert. Beim Start oder bei CRUD wird
    ein Adapter (via ProviderProfile + ResilientAdapter) fuer den Agent gebaut.
    """
    id: str
    name: str
    provider: str
    model: str
    api_key: str = ""
    role: str = ""
    topic: str = ""
    system_prompt: str = ""
    # UniversalAdapter-Felder
    preset: str = ""                  # z.B. "ollama", "gemini", "custom"
    api_url: str = ""                 # Provider-URL
    response_path: str = ""           # JSONPath zur Antwort
    message_format: str = "standard"  # "standard" | "gemini" | "anthropic"
    created_at: datetime = None
    # Kuerzungslimit: None = globaler Default (CONCLAVE_MAX_MESSAGES, nur Preset-Agenten),
    # 0 = keine Kuerzung, sonst hoechstens so viele Nachrichten
    max_messages: int | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("id must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.provider.strip():
            raise ValueError("provider must not be empty")
        if self.max_messages is not None and (
            isinstance(self.max_messages, bool) or not isinstance(self.max_messages, int) or self.max_messages < 0
        ):
            raise ValueError("max_messages must be empty or a whole number >= 0")
        if self.created_at is None:
            object.__setattr__(self, "created_at", datetime.now(UTC))
