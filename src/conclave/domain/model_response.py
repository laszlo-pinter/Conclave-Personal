# src/conclave/domain/model_response.py

from dataclasses import dataclass

from conclave.domain.context_report import ContextReport


@dataclass(frozen=True)
class TokenUsage:
    """Token-Verbrauch eines Provider-Aufrufs."""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class Completion:
    """Ergebnis eines Modellaufrufs: Text, abgerechnete Token und Kontext-Report.

    Bei Streams liefert der Adapter zum Abschluss ein Completion ohne Text.
    """
    text: str = ""
    usage: TokenUsage | None = None
    report: ContextReport | None = None


def completion_text(result) -> str:
    """Text eines Adapter-Ergebnisses (Completion oder – bei aelteren Adaptern – str)."""
    return result if isinstance(result, str) else getattr(result, "text", "")
