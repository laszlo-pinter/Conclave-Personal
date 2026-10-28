"""Consultations anlegen, abfragen, wiederholen - die Logik hinter API und MCP-Tools.

- Die Obergrenze pro Ticket und Stunde wird beim Anlegen gezaehlt, nicht erst im Worker.
- Reviewer nur aus ``[kanzo] reviewers``; ohne Liste ist die Funktion aus.
- Der Kanal (``human``/``agent``) kommt aus dem Principal, also aus dem Token,
  nie aus dem Body; ``channel`` im Body ergibt 400 (Z3).
- Das Ticket wird schon beim Anlegen geprueft: unbekannt -> 404, nur fuer
  Menschen und Kanal nicht ``human`` -> 403. Der Worker prueft erneut.
- Retry: offene oder fehlgeschlagene Zustellungen erneut zustellen (ohne
  Modellaufrufe); ``rerun`` legt eine neue Consultation an und zaehlt zur Grenze.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conclave.application.consultation_worker import ConsultationWorker
from conclave.application.ports import ConsultationRepository, TaskSource
from conclave.domain.consultation import (
    CHANNELS,
    DELIVERED,
    FAILED,
    INTERRUPTED,
    PENDING,
    QUEUED,
    RUNNING,
    Consultation,
)
from conclave.domain.errors import ConclaveError
from conclave.domain.principal import HUMAN, Principal
from conclave.domain.ticket import TASK_REF

MAX_QUESTION = 4000
MAX_CONTEXT = 8000


class ConsultationRequestError(ConclaveError):
    """Ungueltige Anfrage; ``status`` ist der HTTP-Status, ``type`` der Fehlertyp fuer Clients."""

    def __init__(self, message: str, status: int, error_type: str):
        self.status, self.type = status, error_type
        super().__init__(message)


class ConsultationRequests:
    def __init__(self, repository: ConsultationRepository, worker: ConsultationWorker, task_source: TaskSource,
                 *, allowed_reviewers, max_per_hour: int, provider_label=lambda pid: "",
                 source: str = "kanzo") -> None:
        self._repo = repository
        self._worker = worker
        self._source = task_source
        self._allowed = tuple(allowed_reviewers)
        self._max_per_hour = max_per_hour
        self._label = provider_label
        self._source_name = source

    # ── Anlegen ──────────────────────────────────────────────────────────

    def create(self, body: dict, principal: Principal) -> dict:
        if not self._allowed:
            raise ConsultationRequestError(
                "Consultations sind nicht eingerichtet: [kanzo] reviewers in config.toml fehlt.",
                503, "ConsultationsDisabled")
        task = body.get("task")
        question = body.get("question")
        context = body.get("context") or ""
        if "channel" in body:
            raise ConsultationRequestError(
                "channel wird nicht mehr angenommen: der Kanal ergibt sich aus dem Token (seit v0.5.0).",
                400, "ChannelNotAllowed")
        channel = principal.role
        include_previous = body.get("include_previous", False)
        reviewers = body.get("reviewers") or list(self._allowed)

        if not isinstance(task, str) or not TASK_REF.match(task):
            raise ConsultationRequestError("task muss eine Ticket-Referenz wie 'api#12' sein.", 400, "ValidationError")
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
            raise ConsultationRequestError(f"question muss Text mit 1 bis {MAX_QUESTION} Zeichen sein.",
                                           400, "ValidationError")
        if not isinstance(context, str) or len(context) > MAX_CONTEXT:
            raise ConsultationRequestError(f"context darf hoechstens {MAX_CONTEXT} Zeichen haben.",
                                           400, "ValidationError")
        if channel not in CHANNELS:                       # kann nur ein Programmierfehler sein
            raise ConsultationRequestError(f"Unbekannte Rolle: {channel!r}.", 403, "Forbidden")
        if not isinstance(include_previous, bool):
            raise ConsultationRequestError("include_previous muss true oder false sein.", 400, "ValidationError")
        if (not isinstance(reviewers, list) or not reviewers
                or not all(isinstance(r, str) for r in reviewers) or len(set(reviewers)) != len(reviewers)):
            raise ConsultationRequestError("reviewers muss eine Liste verschiedener Agent-IDs sein.",
                                           400, "ValidationError")
        not_allowed = [r for r in reviewers if r not in self._allowed]
        if not_allowed:
            raise ConsultationRequestError(
                f"Nicht erlaubte Reviewer: {', '.join(not_allowed)} (erlaubt: {', '.join(self._allowed)}).",
                400, "ReviewerNotAllowed")

        since = datetime.now(UTC) - timedelta(hours=1)
        if self._repo.count_since(self._source_name, task, since) >= self._max_per_hour:
            raise ConsultationRequestError(
                f"Obergrenze erreicht: hoechstens {self._max_per_hour} Consultations pro Ticket und Stunde.",
                429, "ConsultationLimit")

        ticket = self._source.get_task(task)              # TaskNotFound / TaskSourceError -> Fehlerbehandlung
        if ticket.human and channel != HUMAN:
            raise ConsultationRequestError("Ticket ist nur fuer Menschen (human) - Anfragen von Agenten "
                                           "werden abgelehnt.", 403, "HumanOnlyTicket")

        consultation = Consultation.create(
            source=self._source_name, source_ref=task, question=question, reviewers=reviewers,
            channel=channel, context=context, requested_by=str(body.get("requested_by") or "")[:100],
            include_previous=include_previous)
        self._repo.save(consultation)
        self._worker.submit(consultation.id)
        return self._to_dict(consultation)

    # ── Abfragen ─────────────────────────────────────────────────────────

    def get(self, consultation_id: str) -> dict:
        return self._to_dict(self._require(consultation_id), with_deliveries=True)

    def list_for(self, source_ref: str) -> dict:
        if not isinstance(source_ref, str) or not TASK_REF.match(source_ref):
            raise ConsultationRequestError("source_ref muss eine Ticket-Referenz wie 'api#12' sein.",
                                           400, "ValidationError")
        return {"consultations": [self._to_dict(c) for c in self._repo.list_by_source_ref(self._source_name,
                                                                                          source_ref)]}

    # ── Wiederholen ──────────────────────────────────────────────────────

    def retry(self, consultation_id: str, principal: Principal, *, rerun: bool = False) -> dict:
        c = self._require(consultation_id)
        if c.status in (QUEUED, RUNNING):
            raise ConsultationRequestError("Consultation laeuft noch.", 409, "ConsultationBusy")
        if rerun:
            # Der Kanal folgt dem, der wiederholt - nicht der urspruenglichen Anfrage.
            return self.create({"task": c.source_ref, "question": c.question, "context": c.context,
                                "include_previous": c.include_previous,
                                "reviewers": list(c.reviewers), "requested_by": c.requested_by}, principal)
        open_deliveries = [d for d in self._repo.list_deliveries(c.id) if d.status != DELIVERED and d.message_id]
        if not open_deliveries:
            raise ConsultationRequestError(
                "Nichts zuzustellen. Ohne gespeicherte Antworten hilft nur rerun: true (ruft die Modelle erneut auf).",
                409, "NothingToDeliver")
        for d in open_deliveries:
            d.status, d.error = PENDING, None
            self._repo.save_delivery(d)
        self._worker.submit_delivery(c.id)
        return self._to_dict(c, with_deliveries=True)

    # ── Hilfen ───────────────────────────────────────────────────────────

    def _require(self, consultation_id: str) -> Consultation:
        c = self._repo.get(consultation_id)
        if c is None:
            raise ConsultationRequestError(f"Consultation '{consultation_id}' nicht gefunden.", 404,
                                           "ConsultationNotFound")
        return c

    def _to_dict(self, c: Consultation, with_deliveries: bool = False) -> dict:
        data = {
            "id": c.id, "source": c.source, "task": c.source_ref, "question": c.question, "context": c.context,
            "channel": c.channel, "mode": c.mode, "include_previous": c.include_previous,
            "requested_by": c.requested_by, "status": c.status, "error": c.error,
            "conversation_id": c.conversation_id, "created_at": c.created_at.isoformat(),
            "finished_at": c.finished_at.isoformat() if c.finished_at else None,
            # Offenlegung: an wen der Ticket-Inhalt geht (Plan 4.5)
            "reviewers": [{"id": r, "provider": self._label(r)} for r in c.reviewers],
        }
        if with_deliveries:
            data["deliveries"] = [
                {"reviewer": d.participant_id, "status": d.status, "attempts": d.attempts, "error": d.error,
                 "marker": d.marker, "message_id": d.message_id,
                 "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None}
                for d in self._repo.list_deliveries(c.id)]
            data["retry_possible"] = c.status in (FAILED, INTERRUPTED) or any(
                d["status"] != DELIVERED for d in data["deliveries"])
        return data
