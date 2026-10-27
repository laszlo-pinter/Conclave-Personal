"""ContextReport — welcher Kontext tatsaechlich an den Provider ging.

Gespeichert werden nur Metadaten (Anzahlen, Sequenznummern, Pfade, Groessen),
nie der Prompt selbst.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from conclave.domain.message import Message, MessageAuthorType

# Deutscher Text: grob 3,5 Zeichen pro Token (bewusst nur eine Schaetzung).
CHARS_PER_TOKEN = 3.5

# Marker, mit dem @workspace/ und @read() Dateiinhalte einsetzen
# (conversation_flow._expand_workspace_refs / _process_agent_directives_for_context).
_FILE_BLOCK = re.compile(r"--- Datei: (?P<path>[^\n]+?) ---\n```\n(?P<body>.*?)\n```", re.DOTALL)


@dataclass(frozen=True)
class ContextReport:
    """Metadaten eines Modellaufrufs. Zaehlt Conclave-Nachrichten, nicht Provider-Nachrichten."""
    messages_total: int
    messages_sent: int
    omitted_sequences: tuple[int, int] | None = None
    anchor_sequence: int | None = None
    truncation_limit: int | None = None
    system_parts: tuple[str, ...] = ()
    context_files: tuple[dict, ...] = ()
    skipped_context_files: tuple[dict, ...] = ()
    inline_files: tuple[dict, ...] = ()
    read_results: tuple[dict, ...] = ()
    estimated_tokens: int = 0
    adapter: str = ""
    attempts: int = 1

    @property
    def truncated(self) -> bool:
        return self.messages_sent < self.messages_total

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["omitted_sequences"] = list(self.omitted_sequences) if self.omitted_sequences else None
        for key in ("system_parts", "context_files", "skipped_context_files", "inline_files", "read_results"):
            data[key] = list(data[key])
        return data


def requested_context_files(rules: str) -> list[str]:
    """Pfade aus 'context_files: a.md, b.md'-Zeilen der Chat-Regeln."""
    paths = []
    for line in (rules or "").split("\n"):
        line = line.strip()
        if not line.lower().startswith("context_files:"):
            continue
        paths.extend(p.strip() for p in line[len("context_files:"):].split(",") if p.strip())
    return paths


def native_context_report(conversation, *, agent_prompt: str | None, system_text: str | None,
                          adapter: str) -> ContextReport:
    """Report fuer native Adapter: voller Verlauf, System-Prompt = Agent-Prompt + Regeln.

    Native Adapter laden keine context_files; die Eintraege landen roh in den
    Regeln und werden hier als abgewiesen ausgewiesen.
    """
    rules = getattr(conversation, "rules", "") or ""
    parts = [name for name, present in (("agent_prompt", agent_prompt), ("rules", rules)) if present]
    messages = list(conversation.messages)
    return build_context_report(
        all_messages=messages,
        sent_messages=messages,
        adapter=adapter,
        system_parts=parts,
        system_text=system_text,
        skipped_context_files=[{"path": p, "reason": "adapter_unsupported"}
                               for p in requested_context_files(rules)],
    )


def estimate_tokens(*texts: str | None) -> int:
    chars = sum(len(text) for text in texts if text)
    return int(round(chars / CHARS_PER_TOKEN))


def _file_blocks(messages: list[Message], author: MessageAuthorType) -> tuple[dict, ...]:
    found = []
    for message in messages:
        if message.author_type != author:
            continue
        for match in _FILE_BLOCK.finditer(message.content):
            found.append({
                "path": match.group("path").strip(),
                "bytes": len(match.group("body").encode("utf-8")),
                "message_seq": message.sequence,
            })
    return tuple(found)


def build_context_report(
    *,
    all_messages: list[Message],
    sent_messages: list[Message],
    adapter: str,
    truncation_limit: int | None = None,
    system_parts: list[str] | tuple[str, ...] = (),
    system_text: str | None = None,
    context_files: list[dict] | tuple[dict, ...] = (),
    skipped_context_files: list[dict] | tuple[dict, ...] = (),
) -> ContextReport:
    """Reine Funktion: leitet den Report aus den tatsaechlich gesendeten Nachrichten ab.

    Per @workspace/ eingefuegte Dateien stehen in User-Nachrichten, fruehere
    @read()-Ergebnisse in gespeicherten Agent-Antworten.
    """
    sent_ids = {message.id for message in sent_messages}
    omitted = [message for message in all_messages if message.id not in sent_ids]
    omitted_range = (omitted[0].sequence, omitted[-1].sequence) if omitted else None
    anchor = None
    if omitted and len(sent_messages) >= 2:
        # Anker = erste gesendete Nachricht, wenn zwischen ihr und dem Rest ausgelassen wurde
        first, second = sent_messages[0].sequence, sent_messages[1].sequence
        if any(first < m.sequence < second for m in omitted):
            anchor = first
    return ContextReport(
        messages_total=len(all_messages),
        messages_sent=len(sent_messages),
        omitted_sequences=omitted_range,
        anchor_sequence=anchor,
        truncation_limit=truncation_limit,
        system_parts=tuple(system_parts),
        context_files=tuple(context_files),
        skipped_context_files=tuple(skipped_context_files),
        inline_files=_file_blocks(sent_messages, MessageAuthorType.USER),
        read_results=_file_blocks(sent_messages, MessageAuthorType.MODEL),
        estimated_tokens=estimate_tokens(system_text, *(m.content for m in sent_messages)),
        adapter=adapter,
    )

