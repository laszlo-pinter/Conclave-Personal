"""ContextReport — welcher Kontext tatsaechlich an den Provider ging.

Gespeichert werden nur Metadaten (Anzahlen, Sequenznummern, Pfade, Groessen),
nie der Prompt selbst.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextReport":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        omitted = known.get("omitted_sequences")
        known["omitted_sequences"] = tuple(omitted) if omitted else None
        for key in ("system_parts", "context_files", "skipped_context_files", "inline_files", "read_results"):
            if key in known:
                known[key] = tuple(known[key] or ())
        return cls(**known)


@dataclass
class ContextReportRecord:
    """Gespeicherter Report eines Modellaufrufs, verknuepft mit Run und (bei Erfolg) Nachricht."""
    id: str
    conversation_id: str
    participant_id: str
    report: ContextReport
    run_id: str | None = None
    message_id: str | None = None
    input_tokens: int | None = None    # vom Provider abgerechnet
    output_tokens: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def create(*, conversation_id: str, participant_id: str, report: ContextReport,
               run_id: str | None = None, message_id: str | None = None,
               input_tokens: int | None = None, output_tokens: int | None = None) -> "ContextReportRecord":
        return ContextReportRecord(
            id=str(uuid.uuid4()), conversation_id=conversation_id, participant_id=participant_id,
            report=report, run_id=run_id, message_id=message_id,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )

    def payload(self) -> dict[str, Any]:
        """Inhalt der Spalte report_json."""
        return {"report": self.report.to_dict(),
                "usage": {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}}

    def compact(self) -> dict[str, Any]:
        """Kurzform fuer Nachrichtenlisten und SSE-Events (Kontext-Chip)."""
        r = self.report
        return {
            "messages_sent": r.messages_sent,
            "messages_total": r.messages_total,
            "truncated": r.truncated,
            "omitted_sequences": list(r.omitted_sequences) if r.omitted_sequences else None,
            "files": len(r.context_files) + len(r.inline_files),
            "read_results": len(r.read_results),
            "skipped_files": len(r.skipped_context_files),
            "estimated_tokens": r.estimated_tokens,
            "billed_input_tokens": self.input_tokens,
            "billed_output_tokens": self.output_tokens,
            "adapter": r.adapter,
            "attempts": r.attempts,
        }

    def to_dict(self) -> dict[str, Any]:
        """Vollstaendige Form fuer GET .../messages/<id>/context."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "participant_id": self.participant_id,
            "run_id": self.run_id,
            "message_id": self.message_id,
            "created_at": self.created_at.isoformat(),
            "usage": {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens},
            "report": self.report.to_dict(),
        }


def attach_context_report(exc: BaseException, report: ContextReport | None) -> None:
    """Haengt den Report an eine Exception, damit auch fehlgeschlagene Aufrufe ihn speichern."""
    if report is None or getattr(exc, "context_report", None) is not None:
        return
    try:
        exc.context_report = report  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        pass


def requested_context_files(rules: str) -> list[str]:
    """Pfade aus 'context_files: a.md, b.md'-Zeilen der Chat-Regeln."""
    paths = []
    for line in (rules or "").split("\n"):
        line = line.strip()
        if not line.lower().startswith("context_files:"):
            continue
        paths.extend(p.strip() for p in line[len("context_files:"):].split(",") if p.strip())
    return paths


def native_context_report(conversation, system, *, adapter: str) -> ContextReport:
    """Report fuer native Adapter: voller Verlauf, keine Kuerzung.

    ``system`` ist der gebaute System-Prompt (text, parts, context_files,
    skipped_context_files) - derselbe wie beim UniversalAdapter.
    """
    messages = list(conversation.messages)
    return build_context_report(
        all_messages=messages,
        sent_messages=messages,
        adapter=adapter,
        system_parts=system.parts,
        system_text=system.text,
        context_files=system.context_files,
        skipped_context_files=system.skipped_context_files,
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

