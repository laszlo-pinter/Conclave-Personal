# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Rechte von Agent und Reviewer auf den Board-Routen (Z2, P3, B4): Allowlists aus (Methode, Routen-Muster).

Fuer Agenten gilt Default deny. Jede Board-Route steht in genau einer der Mengen
BOARD_AGENT_ALLOWED, BOARD_HUMAN_ONLY und BOARD_REVIEWER_ONLY. Die Board-App
(``conclave_board.api.app``) nutzt diese Mengen allein, Personal (``conclave.api.access``)
ergaenzt sie um seine eigenen Routen. Die feineren Regeln (letzte Spalte, Markierung,
Tickets "nur fuer Menschen") prueft der BoardService.
"""

from conclave_board.api.versions import PREFIXES, VERSIONS_PATH

# Pfade relativ zum Praefix ("" = /board/v1 bzw. /board selbst); ausgerollt unten (_both).

# Rolle des Tokens abfragen (MCP prueft damit, ob es das richtige Token hat, Z5)
WHOAMI = frozenset({("GET", "/auth/whoami")})

# Genau was die Tools conclave_board_* brauchen (B4)
_BOARD_AGENT_ALLOWED_RELATIVE = frozenset({
    ("GET", "/tasks"),
    ("POST", "/tasks"),
    ("GET", "/search"),
    ("POST", "/next"),
    ("GET", "/projects/<slug>/tasks/<int:number>"),
    ("PATCH", "/projects/<slug>/tasks/<int:number>"),
    ("POST", "/projects/<slug>/tasks/<int:number>/comments"),
    ("GET", "/projects/<slug>/tasks/<int:number>/history"),
    # Vorhaben (P2): lesen und Tickets ueber projekt/vorhaben-n aufrufen
    ("GET", "/projects/<slug>/initiatives"),
    ("GET", "/projects/<slug>/initiatives/<initiative>/tasks/<int:number>"),
    # Aenderungszaehler (P8): "conclave board wait" fragt ihn ab, statt das Board zu laden
    ("GET", "/changes"),
})

# Nur Mensch: Uebersicht, Projekte verwalten, loeschen, Kommentare aendern, Import, Vorhaben pflegen
_BOARD_HUMAN_ONLY_RELATIVE = frozenset({
    ("GET", ""),
    ("GET", "/projects/<slug>/tasks/<int:number>/comments"),
    ("GET", "/projects/<slug>/history"),
    ("POST", "/projects"),
    ("PUT", "/projects/<slug>"),
    ("DELETE", "/projects/<slug>"),
    ("DELETE", "/projects/<slug>/tasks/<int:number>"),
    ("PUT", "/comments/<comment_id>"),
    ("DELETE", "/comments/<comment_id>"),
    ("POST", "/import"),
    ("POST", "/projects/<slug>/initiatives"),
    ("PUT", "/projects/<slug>/initiatives/<initiative>"),
    # Haengende Tickets (T5): anzeigen und freigeben
    ("GET", "/stuck"),
    # Laeuft der Reviewer? (W3, fuer die UI)
    ("GET", "/reviewer"),
    ("POST", "/projects/<slug>/tasks/<int:number>/release"),
    # Review neu anfordern (conclave#145)
    ("POST", "/projects/<slug>/tasks/<int:number>/review/request"),
})

# Nur der Reviewer-Zugang (P3, W3); Agent und Mensch lehnt der BoardService ab
_BOARD_REVIEWER_ONLY_RELATIVE = frozenset({
    ("POST", "/projects/<slug>/tasks/<int:number>/review"),
    ("POST", "/reviewer/heartbeat"),
})

# Was der Reviewer-MCP braucht: lesen, kommentieren, Review-Status
_BOARD_REVIEWER_ALLOWED_RELATIVE = _BOARD_REVIEWER_ONLY_RELATIVE | frozenset({
    ("GET", "/tasks"),
    ("GET", "/search"),
    ("GET", "/projects/<slug>/tasks/<int:number>"),
    ("GET", "/projects/<slug>/tasks/<int:number>/history"),
    ("POST", "/projects/<slug>/tasks/<int:number>/comments"),
    ("GET", "/projects/<slug>/initiatives/<initiative>/tasks/<int:number>"),
    # Aenderungszaehler (W3): erst nach einer Aenderung die Spalte review lesen
    ("GET", "/changes"),
})



def _both(routes: frozenset) -> frozenset:
    """Jede Board-Route gilt unter /board/v1 und unter dem Alias /board (T3)."""
    return frozenset((method, prefix + rule) for method, rule in routes for prefix in PREFIXES)


BOARD_AGENT_ALLOWED = _both(_BOARD_AGENT_ALLOWED_RELATIVE)
BOARD_HUMAN_ONLY = _both(_BOARD_HUMAN_ONLY_RELATIVE)
BOARD_REVIEWER_ONLY = _both(_BOARD_REVIEWER_ONLY_RELATIVE)
BOARD_REVIEWER_ALLOWED = _both(_BOARD_REVIEWER_ALLOWED_RELATIVE)

# Ohne Token: Versionen der Board-API (keine Daten)
BOARD_PUBLIC = frozenset({("GET", VERSIONS_PATH)})

HUMAN_ONLY_ERROR = {"type": "HumanOnly", "error": "Nur für den Menschen-Zugang."}


def may(allowed: frozenset, method: str, rule: str) -> bool:
    """Steht die Route auf der Liste? HEAD zaehlt wie GET."""
    method = "GET" if method == "HEAD" else method
    return (method, rule) in allowed
