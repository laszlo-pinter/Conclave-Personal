"""Consultation - Zweitmeinung mehrerer Reviewer-Modelle zu einem externen Ticket (z. B. Kanzo).

Lebenszyklus: queued -> running -> done | failed; nach einem Server-Neustart
wird ``running`` zu ``interrupted``. Jede Reviewer-Antwort hat eine eigene
Zustellung (``ConsultationDelivery``) mit Kennung gegen Doppelte.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

QUEUED, RUNNING, DONE, FAILED, INTERRUPTED = "queued", "running", "done", "failed", "interrupted"
STATUSES = (QUEUED, RUNNING, DONE, FAILED, INTERRUPTED)

PENDING, DELIVERED = "pending", "delivered"
DELIVERY_STATUSES = (PENDING, DELIVERED, FAILED)

MODES = ("independent",)          # "debate" folgt spaeter
CHANNELS = ("rest", "mcp")        # Zugangsweg: Mensch (REST) oder Agent (MCP)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Consultation:
    id: str
    source: str                    # "kanzo"
    source_ref: str                # "api#12"
    question: str
    reviewers: tuple[str, ...]
    channel: str = "rest"
    mode: str = "independent"
    context: str = ""
    requested_by: str = ""
    include_previous: bool = False
    status: str = QUEUED
    error: str | None = None
    conversation_id: str | None = None
    created_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.source_ref.strip():
            raise ValueError("source_ref must not be empty")
        if not self.question.strip():
            raise ValueError("question must not be empty")
        if not self.reviewers:
            raise ValueError("at least one reviewer is required")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if self.channel not in CHANNELS:
            raise ValueError(f"channel must be one of {CHANNELS}")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")

    @staticmethod
    def create(*, source: str, source_ref: str, question: str, reviewers, channel: str = "rest",
               context: str = "", requested_by: str = "", include_previous: bool = False) -> "Consultation":
        return Consultation(id=str(uuid.uuid4()), source=source, source_ref=source_ref, question=question,
                            reviewers=tuple(reviewers), channel=channel, context=context,
                            requested_by=requested_by, include_previous=include_previous)


@dataclass
class ConsultationDelivery:
    """Zustellung einer Reviewer-Antwort als Kommentar.

    Reihenfolge: Antwort als Message speichern -> pending -> Kennung pruefen ->
    add_comment -> delivered. ``marker`` steht sichtbar in der Schlusszeile.
    """
    id: str
    consultation_id: str
    participant_id: str
    marker: str
    message_id: str | None = None
    status: str = PENDING
    attempts: int = 0
    error: str | None = None
    delivered_at: datetime | None = None

    @staticmethod
    def create(*, consultation_id: str, participant_id: str, message_id: str | None = None) -> "ConsultationDelivery":
        return ConsultationDelivery(
            id=str(uuid.uuid4()), consultation_id=consultation_id, participant_id=participant_id,
            marker=consultation_marker(consultation_id, participant_id), message_id=message_id)


def consultation_marker(consultation_id: str, participant_id: str) -> str:
    """Kennung, die in der Schlusszeile jedes Kommentars steht (Erkennung von Doppelten)."""
    return f"consultation {consultation_id}/{participant_id}"
