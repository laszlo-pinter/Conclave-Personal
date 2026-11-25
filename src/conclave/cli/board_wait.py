"""``conclave board wait`` (P8): warten, bis ein Review entschieden ist, der Mensch steuert oder ein Kommentar kommt.

Die Logik liegt im Kern (``conclave_board.wait``), gemeinsam mit dem Team-Paket (conclave#158).

Gedacht fuer Agenten, die nach "-> review" weiterarbeiten: Der Befehl laeuft im Hintergrund
und endet mit genau einer JSON-Zeile, sobald etwas passiert. Der Agent wird dadurch geweckt,
statt nachzusehen.

- ``wait <ref>`` endet, wenn das Review des Tickets entschieden ist (``passed``, ``rework``,
  ``failed``). War es beim Start schon entschieden, zaehlt erst ein neues Ergebnis.
- ``wait --project <slug>`` endet beim ersten neuen Review-Ergebnis im Projekt oder bei einem
  neuen Steuerticket (Pause, Hinweis).
- ``wait <ref> --comments`` endet beim ersten neuen Kommentar am Ticket, der nicht vom eigenen Zugang
  stammt, mit Kommentar-ID und Herkunft, ohne Text (conclave#158).
- Nach ``--timeout`` Minuten: Exit-Code 2 und ``{"event": "timeout"}``.

Der Befehl fragt ``/board/v1/changes`` ab (billig) und liest erst bei einer Aenderung nach. Er
geht ueber REST mit dem Agent-Token (``CONCLAVE_AGENT_KEY`` bzw. ``agent.token``), mit ``--human``
mit dem Mensch-Token. Ein Reviewer-Token wird abgelehnt, bevor etwas gesendet wird. Tokens
erscheinen nie in der Ausgabe.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
from collections.abc import Callable

import httpx

from conclave_board.wait import (  # noqa: F401 - gemeinsam mit dem Team (conclave#158); hier weiter erreichbar
    BOARD_API,
    DECIDED,
    VERDICT,
    Waiter,
    WaitError,
    comment_event,
    control_event,
    review_event,
    task_path,
)

EXIT_OK, EXIT_ERROR, EXIT_TIMEOUT = 0, 1, 2


class BoardReader:
    """Nur lesende REST-Aufrufe gegen das Board."""

    def __init__(self, url: str, token: str, client: httpx.Client | None = None) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._client = client or httpx.Client(timeout=30)

    def get(self, path: str, params: dict | None = None) -> dict:
        r = self._client.get(self._url + path, params=params, headers={"Authorization": f"Bearer {self._token}"})
        if r.status_code == 404:
            raise WaitError("Nicht gefunden: " + urllib.parse.unquote(path.removeprefix(BOARD_API)))
        if r.status_code in (401, 403):
            raise WaitError(f"Kein Zugang ({r.status_code}): Token pruefen (agent.token bzw. CONCLAVE_AGENT_KEY).")
        r.raise_for_status()
        return r.json()


def _token(human: bool) -> str:
    from conclave.runtime.api_token import read_agent_token, read_token
    token = read_token() if human else read_agent_token()
    if not token:
        raise WaitError("Kein Token gefunden: " + ("api.token bzw. CONCLAVE_API_KEY" if human
                                                   else "agent.token bzw. CONCLAVE_AGENT_KEY") + ".")
    if token.startswith("cvr_"):
        raise WaitError("Das ist ein Reviewer-Token; wait braucht das Agent-Token (oder --human).")
    return token


def run(args, *, reader: BoardReader | None = None, sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic, out=None) -> int:
    out = out or sys.stdout
    if bool(args.ref) == bool(args.project):
        print("FEHLER: Entweder ein Ticket (z. B. conclave#12) oder --project angeben.", file=sys.stderr)
        return EXIT_ERROR
    comments = bool(getattr(args, "comments", False))
    if comments and not args.ref:
        print("FEHLER: --comments gilt fuer ein Ticket (z. B. conclave#12), nicht fuer --project.", file=sys.stderr)
        return EXIT_ERROR
    if args.timeout <= 0 or args.interval <= 0:
        print("FEHLER: --timeout und --interval muessen positiv sein.", file=sys.stderr)
        return EXIT_ERROR
    try:
        if reader is None:
            url = args.url or os.environ.get("CONCLAVE_API_URL", "").strip() or "http://localhost:8000"
            reader = BoardReader(url, _token(args.human))
        waiter = Waiter(reader, interval=args.interval, timeout=args.timeout * 60, sleep=sleep, clock=clock,
                        transient=(httpx.HTTPError,))
        if comments:
            result = waiter.wait_comments(args.ref)
        else:
            result = waiter.wait_task(args.ref) if args.ref else waiter.wait_project(args.project)
    except WaitError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except httpx.HTTPError as exc:
        print(f"FEHLER: Board nicht erreichbar ({exc.__class__.__name__}).", file=sys.stderr)
        return EXIT_ERROR
    # ASCII-JSON (Umlaute als Escapes): die Zeile kommt in jeder Konsolen-Codierung heil an
    print(json.dumps(result), file=out, flush=True)
    if result["event"] == "timeout":
        print(f"Zeit abgelaufen ({args.timeout:g} Minuten).", file=sys.stderr)
        return EXIT_TIMEOUT
    return EXIT_OK


def add_parser(board_sub) -> None:
    wait = board_sub.add_parser(
        "wait", help="Warten, bis ein Review entschieden ist, der Mensch steuert oder ein Kommentar kommt (eine JSON-Zeile)")
    wait.add_argument("ref", nargs="?", default="", help="Ticket, z. B. conclave#12")
    wait.add_argument("--project", default="", help="Erstes Review-Ergebnis oder Steuerticket im Projekt")
    wait.add_argument("--comments", action="store_true",
                      help="Bis zum ersten neuen Kommentar eines anderen am Ticket (Chat-Tickets, auch in erledigt)")
    wait.add_argument("--timeout", type=float, default=60, help="Minuten bis Exit-Code 2 (Standard 60)")
    wait.add_argument("--interval", type=float, default=5, help="Sekunden zwischen zwei Abfragen (Standard 5)")
    wait.add_argument("--url", default="", help="Server, Standard CONCLAVE_API_URL bzw. http://localhost:8000")
    wait.add_argument("--human", action="store_true", help="Mit dem Mensch-Token statt dem Agent-Token")
