# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Rechte von Agent und Reviewer auf den Board-Routen (Z2, P3, B4): Allowlists aus (Methode, Routen-Muster).

Fuer Agenten gilt Default deny. Jede Board-Route steht in genau einer der Mengen
BOARD_AGENT_ALLOWED, BOARD_HUMAN_ONLY und BOARD_REVIEWER_ONLY. Die Board-App
(``conclave_board.api.app``) nutzt diese Mengen allein, Personal (``conclave.api.access``)
ergaenzt sie um seine eigenen Routen. Die feineren Regeln (letzte Spalte, Markierung,
Tickets "nur fuer Menschen") prueft der BoardService.
"""

# Rolle des Tokens abfragen (MCP prueft damit, ob es das richtige Token hat, Z5)
WHOAMI = frozenset({("GET", "/auth/whoami")})

# Genau was die Tools conclave_board_* brauchen (B4)
BOARD_AGENT_ALLOWED = frozenset({
    ("GET", "/board/tasks"),
    ("POST", "/board/tasks"),
    ("GET", "/board/search"),
    ("POST", "/board/next"),
    ("GET", "/board/projects/<slug>/tasks/<int:number>"),
    ("PATCH", "/board/projects/<slug>/tasks/<int:number>"),
    ("POST", "/board/projects/<slug>/tasks/<int:number>/comments"),
    ("GET", "/board/projects/<slug>/tasks/<int:number>/history"),
    # Vorhaben (P2): lesen und Tickets ueber projekt/vorhaben-n aufrufen
    ("GET", "/board/projects/<slug>/initiatives"),
    ("GET", "/board/projects/<slug>/initiatives/<initiative>/tasks/<int:number>"),
})

# Nur Mensch: Uebersicht, Projekte verwalten, loeschen, Kommentare aendern, Import, Vorhaben pflegen
BOARD_HUMAN_ONLY = frozenset({
    ("GET", "/board"),
    ("GET", "/board/changes"),
    ("GET", "/board/projects/<slug>/tasks/<int:number>/comments"),
    ("GET", "/board/projects/<slug>/history"),
    ("POST", "/board/projects"),
    ("PUT", "/board/projects/<slug>"),
    ("DELETE", "/board/projects/<slug>"),
    ("DELETE", "/board/projects/<slug>/tasks/<int:number>"),
    ("PUT", "/board/comments/<comment_id>"),
    ("DELETE", "/board/comments/<comment_id>"),
    ("POST", "/board/import"),
    ("POST", "/board/projects/<slug>/initiatives"),
    ("PUT", "/board/projects/<slug>/initiatives/<initiative>"),
})

# Nur der Reviewer-Zugang (P3); Agent und Mensch lehnt der BoardService ab
BOARD_REVIEWER_ONLY = frozenset({
    ("POST", "/board/projects/<slug>/tasks/<int:number>/review"),
})

# Was der Reviewer-MCP braucht: lesen, kommentieren, Review-Status
BOARD_REVIEWER_ALLOWED = BOARD_REVIEWER_ONLY | frozenset({
    ("GET", "/board/tasks"),
    ("GET", "/board/search"),
    ("GET", "/board/projects/<slug>/tasks/<int:number>"),
    ("GET", "/board/projects/<slug>/tasks/<int:number>/history"),
    ("POST", "/board/projects/<slug>/tasks/<int:number>/comments"),
    ("GET", "/board/projects/<slug>/initiatives/<initiative>/tasks/<int:number>"),
})

HUMAN_ONLY_ERROR = {"type": "HumanOnly", "error": "Nur für den Menschen-Zugang."}


def may(allowed: frozenset, method: str, rule: str) -> bool:
    """Steht die Route auf der Liste? HEAD zaehlt wie GET."""
    method = "GET" if method == "HEAD" else method
    return (method, rule) in allowed
