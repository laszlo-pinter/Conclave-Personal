# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Warten auf das Board (P8, conclave#158): gemeinsame Logik fuer ``conclave board wait`` (Personal),
``conclave-board wait`` und ``conclave-board-mcp wait`` (Team).

Fragt ``/board/v1/changes`` ab (billig) und liest erst bei einer Aenderung nach. Der Transport ist
austauschbar: ``reader.get(path, params)`` liefert JSON oder wirft; Fehler aus ``transient`` (z. B. Netz)
zaehlen als "nichts", alle anderen brechen ab.

- ``wait_task``: das Review des Tickets ist entschieden (``passed``, ``rework``, ``failed``); war es beim
  Start schon entschieden, zaehlt erst ein neues Ergebnis.
- ``wait_project``: erstes neues Review-Ergebnis im Projekt oder ein neues Steuerticket.
- ``wait_comments``: erster neuer Kommentar am Ticket, der nicht vom eigenen Zugang stammt (gleiche
  Herkunft und gleiche Person, laut ``/auth/whoami``). Die Zeile nennt Kommentar-ID und Herkunft, nie den
  Text: Den liest der Agent danach selbst, als Daten (Chat-Tickets, auch in "erledigt").
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol
from urllib.parse import quote

from conclave_board.tools import who

BOARD_API = "/board/v1"
DECIDED = ("passed", "rework", "failed")
VERDICT = {"passed": "gruen", "rework": "gelb", "failed": "rot"}


class Reader(Protocol):
    def get(self, path: str, params: dict | None = None) -> dict: ...


class WaitError(Exception):
    """Fehler fuer die Kommandozeile (ohne Token, ohne Stacktrace)."""


def task_path(ref: str) -> str:
    slug, sep, number = ref.rpartition("#")
    if not sep or not slug or not number.isdigit():
        raise WaitError(f"Ticket-Referenz wie conclave#12 erwartet, nicht {ref!r}.")
    return f"{BOARD_API}/projects/{quote(slug, safe='')}/tasks/{int(number)}"


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


def comment_event(task: dict, comment: dict) -> dict:
    """Ohne Text: ``from`` mit Herkunft und Person, wie in den MCP-Tools."""
    origin, actor_id = comment.get("origin"), comment.get("actor_id")
    return {"event": "comment", "task": task["ref"], "title": task.get("title", ""), "comment": comment.get("id"),
            "from": f"Kommentar von: {who(origin, actor_id, comment.get('actor_name'))}", "origin": origin,
            "person": comment.get("actor_name") or actor_id, "at": comment.get("created_at"),
            "status": task.get("status")}


class Waiter:
    def __init__(self, reader: Reader, *, interval: float, timeout: float,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 transient: tuple[type[BaseException], ...] = ()) -> None:
        self._reader = reader
        self._interval = interval
        self._timeout = timeout
        self._sleep = sleep
        self._clock = clock
        self._transient = transient

    def _changes(self) -> object:
        return self._reader.get(BOARD_API + "/changes").get("changes")

    def _poll(self, check: Callable[[], dict | None]) -> dict:
        """Ruft ``check`` am Anfang und bei jeder Aenderung des Zaehlers; Fehler aus ``transient`` zaehlen als
        "nichts"."""
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
                found = check()
                last = current                 # erst nach erfolgreichem Nachlesen: sonst beim naechsten Takt erneut
            except self._transient:
                continue
        return found

    def wait_task(self, ref: str) -> dict:
        path = task_path(ref)
        before = _review_key(self._reader.get(path))

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

    def me(self) -> tuple[str, str]:
        """(Herkunft, Person) des eigenen Zugangs; ohne ``actor_id`` (Personal) steht dort die Rolle wie an
        seinen Kommentaren."""
        me = self._reader.get("/auth/whoami")
        role = me.get("role")
        if not role:
            raise WaitError("Der Server nennt die eigene Rolle nicht (/auth/whoami).")
        return role, me.get("actor_id") or role

    def wait_comments(self, ref: str) -> dict:
        path = task_path(ref)
        own = self.me()
        seen = {c.get("id") for c in self._reader.get(path).get("comments") or []}

        def check() -> dict | None:
            task = self._reader.get(path)
            for comment in task.get("comments") or []:
                if comment.get("id") in seen:
                    continue
                seen.add(comment.get("id"))
                if (comment.get("origin"), comment.get("actor_id")) != own:
                    return comment_event(task, comment)
            return None

        return self._poll(check)
