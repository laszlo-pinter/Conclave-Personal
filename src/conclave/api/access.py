"""Rechte des Agent- und des Reviewer-Zugangs (Z2, P3): Allowlists aus (Methode, Routen-Muster).

Fuer Agenten gilt Default deny: Erlaubt ist nur, was die MCP-Tools brauchen,
ohne Loeschen (E2). Jede Route steht in genau einer der Mengen AGENT_ALLOWED,
HUMAN_ONLY, REVIEWER_ONLY und PUBLIC; ein Test prueft das gegen die registrierten
Routen, eine neue Route muss also bewusst zugeordnet werden.

Der Reviewer hat eine eigene, engere Liste (REVIEWER_ALLOWED): Board lesen,
kommentieren und den Review-Status setzen, sonst nichts.

Die Board-Routen und ihre Zuordnung kommen aus dem Board-Paket (T1).
"""

from conclave_board.api.access import (  # noqa: F401
    BOARD_AGENT_ALLOWED,
    BOARD_HUMAN_ONLY,
    BOARD_REVIEWER_ALLOWED,
    BOARD_REVIEWER_ONLY,
    HUMAN_ONLY_ERROR,
    WHOAMI,
)

# Lesbar fuer Agenten, ohne dass ein MCP-Tool sie braucht (E-S5 a, R15): dieselben Daten
# liefern GET /conversations/<id> und der Export; es sind keine Geheimnisse.
AGENT_CONTEXT_READ = frozenset({
    ("GET", "/conversations/<conversation_id>/rules"),
    ("GET", "/conversations/<conversation_id>/tool-events"),
    ("GET", "/conversations/<conversation_id>/messages/<message_id>/context"),
})

# Was die MCP-Tools (mcp_server.py) aufrufen, dazu /auth/whoami fuer den Rollen-Check (Z5).
AGENT_ALLOWED = AGENT_CONTEXT_READ | frozenset({
    ("GET", "/auth/whoami"),
    ("GET", "/conversations"),
    ("POST", "/conversations"),
    ("GET", "/conversations/<conversation_id>"),
    ("POST", "/conversations/<conversation_id>/topic"),
    ("POST", "/conversations/<conversation_id>/participants"),
    ("POST", "/conversations/<conversation_id>/messages"),
    ("POST", "/conversations/<conversation_id>/participants/<participant_id>/invoke"),
    ("POST", "/conversations/<conversation_id>/orchestrate"),
    ("POST", "/conversations/<conversation_id>/orchestrate-parallel"),
    ("GET", "/conversations/<conversation_id>/export"),
    ("GET", "/agents"),
    ("GET", "/usage"),
    ("GET", "/workspace"),
    ("GET", "/workspace/<path:filepath>"),
    ("POST", "/workspace/<path:filepath>"),
    ("POST", "/consultations"),
    ("GET", "/consultations/<consultation_id>"),
}) | BOARD_AGENT_ALLOWED

# Nur mit dem Mensch-Token: Einstellungen, Agents verwalten, Backup/Restore, Logs,
# Loeschen (E2), Floor und Auto-Loop, Wiederholen von Consultations (rerun kostet Geld)
# sowie UI-Routen, die kein MCP-Tool braucht.
HUMAN_ONLY = frozenset({
    ("GET", "/settings"),
    ("PUT", "/settings"),
    ("GET", "/logs"),
    ("POST", "/backup"),
    ("GET", "/backups"),
    ("POST", "/restore"),
    ("GET", "/agent-roles"),
    ("POST", "/agents"),
    ("GET", "/agents/<agent_id>"),
    ("PUT", "/agents/<agent_id>"),
    ("DELETE", "/agents/<agent_id>"),
    ("POST", "/agents/<agent_id>/test"),
    ("GET", "/presets"),
    ("GET", "/providers"),
    ("GET", "/runs"),
    ("GET", "/runs/<run_id>"),
    ("GET", "/usage/conversations"),
    ("GET", "/consultations"),
    ("POST", "/consultations/<consultation_id>/retry"),
    ("DELETE", "/conversations/<conversation_id>"),
    ("DELETE", "/conversations/<conversation_id>/participants/<participant_id>"),
    ("DELETE", "/workspace/<path:filepath>"),
    ("POST", "/conversations/<conversation_id>/auto-loop"),
    ("POST", "/conversations/<conversation_id>/floor/grant"),
    ("POST", "/conversations/<conversation_id>/floor/invoke"),
    ("POST", "/conversations/<conversation_id>/floor/revoke"),
    ("POST", "/conversations/<conversation_id>/orchestrate-parallel-stream"),
    ("POST", "/conversations/<conversation_id>/rules"),
    ("GET", "/conversations/<conversation_id>/participants/<participant_id>/context-preview"),
    ("GET", "/conversations/<conversation_id>/participants/<participant_id>/stream"),
}) | BOARD_HUMAN_ONLY

# Ohne Token erreichbar (PUBLIC_GET_PATHS und statische Dateien in app.py).
PUBLIC = frozenset({
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/api-docs"),
    ("GET", "/openapi.json"),
    ("GET", "/static/<path:filename>"),
})

# Nur der Reviewer-Zugang (P3); Agent und Mensch lehnt der BoardService ab
REVIEWER_ONLY = BOARD_REVIEWER_ONLY

# Was der Reviewer-MCP (conclave-mcp --reviewer) braucht: lesen, kommentieren, Review-Status
REVIEWER_ALLOWED = BOARD_REVIEWER_ALLOWED | WHOAMI



def agent_may(method: str, rule: str) -> bool:
    """Darf ein Agent diese Route aufrufen? HEAD zaehlt wie GET."""
    method = "GET" if method == "HEAD" else method
    return (method, rule) in AGENT_ALLOWED


def reviewer_may(method: str, rule: str) -> bool:
    """Darf der Reviewer diese Route aufrufen? HEAD zaehlt wie GET."""
    method = "GET" if method == "HEAD" else method
    return (method, rule) in REVIEWER_ALLOWED
