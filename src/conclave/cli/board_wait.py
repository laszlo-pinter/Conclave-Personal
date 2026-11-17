"""``conclave board wait`` (P8): warten, bis ein Review entschieden ist oder der Mensch steuert.

Gedacht fuer Agenten, die nach "-> review" weiterarbeiten: Der Befehl laeuft im Hintergrund
und endet mit genau einer JSON-Zeile, sobald etwas passiert. Der Agent wird dadurch geweckt,
statt nachzusehen.

- ``wait <ref>`` endet, wenn das Review des Tickets entschieden ist (``passed``, ``rework``,
  ``failed``). War es beim Start schon entschieden, zaehlt erst ein neues Ergebnis.
- ``wait --project <slug>`` endet beim ersten neuen Review-Ergebnis im Projekt oder bei einem
  neuen Steuerticket (Pause, Hinweis).
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

BOARD_API = "/board/v1"
DECIDED = ("passed", "rework", "failed")
VERDICT = {"passed": "gruen", "rework": "gelb", "failed": "rot"}
EXIT_OK, EXIT_ERROR, EXIT_TIMEOUT = 0, 1, 2


class WaitError(Exception):
    """Fehler fuer die Kommandozeile (ohne Token, ohne Stacktrace)."""


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


def task_path(ref: str) -> str:
    slug, sep, number = ref.rpartition("#")
    if not sep or not slug or not number.isdigit():
        raise WaitError(f"Ticket-Referenz wie conclave#12 erwartet, nicht {ref!r}.")
    return f"{BOARD_API}/projects/{urllib.parse.quote(slug, safe='')}/tasks/{int(number)}"


def _review_key(task: dict) -> tuple[str, str | None]:
    review = task.get("review") or {}
    return review.get("state") or "none", review.get("at")


def review_event(task: dict) -> dict:
    review = task.get("review") or {}
    state = review.get("state")
    return {"event": "review", "task": task["ref"], "title": task.get("title", ""), "state": state,
            "verdict": VERDICT.get(state, state), "blocking": review.get("blocking"),
            "suggestions": review.get("suggestions"), "checked": review.get("checked"),
            "status": task.get("status")}


def _controls(data: dict) -> dict[str, dict]:
    state = data.get("control") or {}
    return {e["task"]: e for e in (state.get("pauses") or []) + (state.get("hints") or [])}


def control_event(entry: dict) -> dict:
    return {"event": "control", "task": entry["task"], "type": entry.get("type"), "scope": entry.get("scope"),
            "reason": entry.get("reason", "")}


def _decided_since(task: dict, before: tuple[str, str | None] | None) -> bool:
    state, at = _review_key(task)
    if state not in DECIDED:
        return False
    return before is None or before[0] not in DECIDED or before[1] != at


class Waiter:
    def __init__(self, reader: BoardReader, *, interval: float, timeout: float,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        self._reader = reader
        self._interval = interval
        self._timeout = timeout
        self._sleep = sleep
        self._clock = clock

    def _changes(self) -> object:
        return self._reader.get(BOARD_API + "/changes").get("changes")

    def _poll(self, check: Callable[[], dict | None]) -> dict:
        """Ruft ``check`` am Anfang und bei jeder Aenderung des Zaehlers; Netzfehler zaehlen als "nichts"."""
        deadline = self._clock() + self._timeout
        last = self._changes()
        found = check()
        while found is None:
            if self._clock() >= deadline:
                return {"event": "timeout", "minutes": round(self._timeout / 60, 1)}
            self._sleep(self._interval)
            try:
                current = self._changes()
                if current == last:
                    continue
                last = current
                found = check()
            except httpx.HTTPError:
                continue
        return found

    def wait_task(self, ref: str) -> dict:
        path = task_path(ref)
        start = self._reader.get(path)
        before = _review_key(start)

        def check() -> dict | None:
            task = self._reader.get(path)
            return review_event(task) if _decided_since(task, before) else None

        # Beim Start schon entschieden: _decided_since wartet auf ein neues Ergebnis (anderes "at")
        return self._poll(check)

    def wait_project(self, slug: str) -> dict:
        params = {"project": slug, "include_done": "true"}
        start = self._reader.get(BOARD_API + "/tasks", params)
        reviews = {t["ref"]: _review_key(t) for t in start.get("tasks", [])}
        controls = set(_controls(start))

        def check() -> dict | None:
            data = self._reader.get(BOARD_API + "/tasks", params)
            new_controls = [e for ref, e in _controls(data).items() if ref not in controls]
            if new_controls:
                return control_event(new_controls[0])
            decided = [t for t in data.get("tasks", []) if _decided_since(t, reviews.get(t["ref"]))]
            if decided:
                return review_event(max(decided, key=lambda t: (t.get("review") or {}).get("at") or ""))
            return None

        return self._poll(check)


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
    if args.timeout <= 0 or args.interval <= 0:
        print("FEHLER: --timeout und --interval muessen positiv sein.", file=sys.stderr)
        return EXIT_ERROR
    try:
        if reader is None:
            url = args.url or os.environ.get("CONCLAVE_API_URL", "").strip() or "http://localhost:8000"
            reader = BoardReader(url, _token(args.human))
        waiter = Waiter(reader, interval=args.interval, timeout=args.timeout * 60, sleep=sleep, clock=clock)
        result = waiter.wait_task(args.ref) if args.ref else waiter.wait_project(args.project)
    except WaitError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except httpx.HTTPError as exc:
        print(f"FEHLER: Board nicht erreichbar ({exc.__class__.__name__}).", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False), file=out, flush=True)
    if result["event"] == "timeout":
        print(f"Zeit abgelaufen ({args.timeout:g} Minuten).", file=sys.stderr)
        return EXIT_TIMEOUT
    return EXIT_OK


def add_parser(board_sub) -> None:
    wait = board_sub.add_parser(
        "wait", help="Warten, bis ein Review entschieden ist oder der Mensch steuert (P8; eine JSON-Zeile)")
    wait.add_argument("ref", nargs="?", default="", help="Ticket, z. B. conclave#12")
    wait.add_argument("--project", default="", help="Erstes Review-Ergebnis oder Steuerticket im Projekt")
    wait.add_argument("--timeout", type=float, default=60, help="Minuten bis Exit-Code 2 (Standard 60)")
    wait.add_argument("--interval", type=float, default=5, help="Sekunden zwischen zwei Abfragen (Standard 5)")
    wait.add_argument("--url", default="", help="Server, Standard CONCLAVE_API_URL bzw. http://localhost:8000")
    wait.add_argument("--human", action="store_true", help="Mit dem Mensch-Token statt dem Agent-Token")
