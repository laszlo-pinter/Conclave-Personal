# src/conclave/domain/model_response.py

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenUsage:
    """Token-Verbrauch eines Provider-Aufrufs."""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
