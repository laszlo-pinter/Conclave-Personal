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
import uuid
from datetime import UTC, datetime, timedelta
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


LEASE_SECONDS = 120.0                  # ohne Lebenszeichen gilt ein Lauf danach als abgebrochen


class ConsultationWorker:
    def __init__(self, repository: ConsultationRepository, processor: ConsultationProcessor, *,
                 threads: int = 1, lease_seconds: float = LEASE_SECONDS,
                 heartbeat_seconds: float | None = None) -> None:
        self._repo = repository
        self._processor = processor
        self._threads = max(1, threads)
        self._queue: queue.Queue = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._stop = threading.Event()
        # Lease je Lauf (R10): verlaengert, solange der Lauf dauert; abgelaufen = Worker weg
        self.owner = f"worker-{uuid.uuid4()}"
        self._lease = timedelta(seconds=lease_seconds)
        self._heartbeat = heartbeat_seconds if heartbeat_seconds is not None else lease_seconds / 4

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
        """Stand nach einem Neustart aufraeumen und offene Arbeit einreihen.

        Unterbrochen werden nur Laeufe ohne gueltige Lease; ein anderer Worker, der seine Lease
        noch verlaengert, behaelt seinen Lauf (R10).
        """
        delivering = self.reap()
        for consultation in self._repo.list_by_status(QUEUED):
            self.submit(consultation.id)
        for consultation in self._repo.list_by_status(INTERRUPTED):
            if consultation.id in delivering:
                continue                            # schon von reap() eingereiht
            deliveries = self._repo.list_deliveries(consultation.id)
            if any(d.status == PENDING and d.message_id for d in deliveries):
                self.submit_delivery(consultation.id)

    def reap(self) -> set[str]:
        """Laeufe mit abgelaufener Lease als unterbrochen markieren; vorhandene Antworten zustellen.
        Liefert die IDs, deren Zustellung eingereiht wurde."""
        delivering: set[str] = set()
        for consultation in self._repo.list_expired_running(datetime.now(UTC)):
            if not self._repo.transition(consultation, RUNNING, INTERRUPTED,
                                         error="Bearbeitung abgebrochen (Server beendet oder Worker ohne Lebenszeichen)."):
                continue
            logger.warning("Consultation %s unterbrochen (Lease abgelaufen)", consultation.id)
            deliveries = self._repo.list_deliveries(consultation.id)
            if any(d.status == PENDING and d.message_id for d in deliveries):
                self.submit_delivery(consultation.id)
                delivering.add(consultation.id)
        return delivering

    # ── Bearbeitung ──────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=max(self._lease.total_seconds(), 1.0))
            except queue.Empty:
                try:
                    self.reap()                         # gelegentlich: Laeufe anderer, abgestuerzter Worker
                except Exception:  # noqa: BLE001 - Worker darf nie sterben
                    logger.exception("Consultation-Worker: Aufraeumen fehlgeschlagen")
                continue
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
        if not self._repo.claim(consultation_id, owner=self.owner, lease_until=datetime.now(UTC) + self._lease):
            return                                  # schon von einem anderen Worker uebernommen
        consultation = self._repo.get(consultation_id)
        done = threading.Event()
        beat = threading.Thread(target=self._keep_lease, args=(consultation_id, done), daemon=True,
                                name=f"lease-{consultation_id[:8]}")
        beat.start()
        try:
            self._processor.run(consultation)
        except Exception as exc:  # noqa: BLE001 - Worker darf nie sterben
            logger.exception("Consultation %s fehlgeschlagen", consultation_id)
            self._fail(consultation_id, exc)
        finally:
            done.set()
            beat.join(self._heartbeat * 2 + 1)

    def _keep_lease(self, consultation_id: str, done: threading.Event) -> None:
        while not done.wait(self._heartbeat):
            try:
                if not self._repo.renew_lease(consultation_id, self.owner, datetime.now(UTC) + self._lease):
                    return                          # nicht mehr unser Lauf (fertig oder unterbrochen)
            except Exception:  # noqa: BLE001
                logger.exception("Lease fuer Consultation %s nicht verlaengert", consultation_id)

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
        self._repo.transition(consultation, RUNNING, FAILED, error=f"{type(exc).__name__}: {exc}"[:500])


def should_start_workers(debug: bool, environ) -> bool:
    """Im Debug-Modus startet der Werkzeug-Reloader einen zweiten Prozess:
    Worker nur im Kindprozess (WERKZEUG_RUN_MAIN), sonst liefen zwei."""
    return not debug or environ.get("WERKZEUG_RUN_MAIN") == "true"
