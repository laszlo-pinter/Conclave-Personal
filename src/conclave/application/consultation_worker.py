"""Hintergrund-Worker fuer Consultations.

Ein eigener Thread mit Warteschlange; die waitress-Threads bleiben frei.
Gestartet wird er ausdruecklich in ``runtime.serve.serve()``, nicht in
``create_app`` (Tests und der Reloader im Debug-Modus rufen ``create_app``
mehrfach auf).

- Uebernahme atomar (``ConsultationRepository.claim``: queued -> running nur
  fuer genau einen Worker).
- Nach einem Neustart: ``running`` -> ``interrupted``. Sind Antworten
  gespeichert, aber nicht zugestellt, wird automatisch zugestellt (kostet
  nichts). Ohne Antworten werden die Modelle **nicht** automatisch erneut
  aufgerufen - das geht nur ausdruecklich (Retry mit ``rerun``).
"""

from __future__ import annotations

import queue
import threading
from datetime import UTC, datetime
from typing import Protocol

from conclave.application.ports import ConsultationRepository
from conclave.domain.consultation import FAILED, INTERRUPTED, PENDING, QUEUED, RUNNING, Consultation
from conclave.infrastructure.log import get_logger

logger = get_logger("application.consultation_worker")

RUN, DELIVER = "run", "deliver"


class ConsultationProcessor(Protocol):
    def run(self, consultation: Consultation) -> None:
        """Reviewer befragen und Antworten zustellen (Status selbst setzen)."""
        ...

    def deliver_pending(self, consultation: Consultation) -> None:
        """Nur offene Zustellungen bereits gespeicherter Antworten nachholen."""
        ...


class ConsultationWorker:
    def __init__(self, repository: ConsultationRepository, processor: ConsultationProcessor, *,
                 threads: int = 1) -> None:
        self._repo = repository
        self._processor = processor
        self._threads = max(1, threads)
        self._queue: queue.Queue = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._stop = threading.Event()

    # ── Steuerung ────────────────────────────────────────────────────────

    def submit(self, consultation_id: str) -> None:
        """Neue Consultation (Status queued) zur Bearbeitung einreihen."""
        self._queue.put((RUN, consultation_id))

    def submit_delivery(self, consultation_id: str) -> None:
        """Offene Zustellungen einer Consultation nachholen (ohne Modellaufrufe)."""
        self._queue.put((DELIVER, consultation_id))

    def start(self) -> None:
        if self._workers:
            return
        self.recover()
        for index in range(self._threads):
            thread = threading.Thread(target=self._loop, name=f"consultations-{index}", daemon=True)
            thread.start()
            self._workers.append(thread)
        logger.info("Consultation-Worker gestartet (%d Thread(s))", self._threads)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for _ in self._workers:
            self._queue.put(None)
        for thread in self._workers:
            thread.join(timeout)
        self._workers.clear()

    def join(self, timeout: float = 10.0) -> bool:
        """Wartet, bis die Warteschlange leer ist (fuer Tests). True bei Erfolg."""
        done = threading.Event()

        def wait():
            self._queue.join()
            done.set()

        threading.Thread(target=wait, daemon=True).start()
        return done.wait(timeout)

    # ── Neustart ─────────────────────────────────────────────────────────

    def recover(self) -> None:
        """Stand nach einem Neustart aufraeumen und offene Arbeit einreihen."""
        for consultation in self._repo.list_by_status(RUNNING):
            consultation.status = INTERRUPTED
            consultation.error = "Server wurde waehrend der Bearbeitung beendet."
            consultation.finished_at = datetime.now(UTC)
            self._repo.save(consultation)
            logger.warning("Consultation %s unterbrochen (Neustart)", consultation.id)
        for consultation in self._repo.list_by_status(QUEUED):
            self.submit(consultation.id)
        for consultation in self._repo.list_by_status(INTERRUPTED):
            deliveries = self._repo.list_deliveries(consultation.id)
            if any(d.status == PENDING and d.message_id for d in deliveries):
                self.submit_delivery(consultation.id)

    # ── Bearbeitung ──────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            try:
                if item is None:
                    return
                kind, consultation_id = item
                if kind == RUN:
                    self._run(consultation_id)
                else:
                    self._deliver(consultation_id)
            except Exception:  # noqa: BLE001 - z. B. Datenbankfehler beim claim: Worker darf nie sterben
                logger.exception("Consultation-Worker: Auftrag %r fehlgeschlagen", item)
            finally:
                self._queue.task_done()

    def _run(self, consultation_id: str) -> None:
        if not self._repo.claim(consultation_id):
            return                                  # schon von einem anderen Worker uebernommen
        consultation = self._repo.get(consultation_id)
        try:
            self._processor.run(consultation)
        except Exception as exc:  # noqa: BLE001 - Worker darf nie sterben
            logger.exception("Consultation %s fehlgeschlagen", consultation_id)
            self._fail(consultation_id, exc)

    def _deliver(self, consultation_id: str) -> None:
        consultation = self._repo.get(consultation_id)
        if consultation is None:
            return
        try:
            self._processor.deliver_pending(consultation)
        except Exception:  # noqa: BLE001
            logger.exception("Zustellung fuer Consultation %s fehlgeschlagen", consultation_id)

    def _fail(self, consultation_id: str, exc: Exception) -> None:
        consultation = self._repo.get(consultation_id)
        if consultation is None:
            return
        consultation.status = FAILED
        consultation.error = f"{type(exc).__name__}: {exc}"[:500]
        consultation.finished_at = datetime.now(UTC)
        self._repo.save(consultation)


def should_start_workers(debug: bool, environ) -> bool:
    """Im Debug-Modus startet der Werkzeug-Reloader einen zweiten Prozess:
    Worker nur im Kindprozess (WERKZEUG_RUN_MAIN), sonst liefen zwei."""
    return not debug or environ.get("WERKZEUG_RUN_MAIN") == "true"
