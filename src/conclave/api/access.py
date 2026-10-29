"""Rechte des Agent-Zugangs (Z2): Allowlist aus (Methode, Routen-Muster).

Fuer Agenten gilt Default deny: Erlaubt ist nur, was die MCP-Tools brauchen,
ohne Loeschen (E2). Jede Route steht in genau einer der drei Mengen; ein Test
prueft das gegen die registrierten Routen, eine neue Route muss also bewusst
zugeordnet werden.
"""

# Was die MCP-Tools (mcp_server.py) aufrufen, dazu /auth/whoami fuer den Rollen-Check (Z5).
AGENT_ALLOWED = frozenset({
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
}) | frozenset({
    # Board: genau was die Tools conclave_board_* brauchen (B4). Die feineren Regeln
    # (letzte Spalte, Markierung, Tickets "nur fuer Menschen") prueft der BoardService.
    ("GET", "/board/tasks"),
    ("POST", "/board/tasks"),
    ("GET", "/board/search"),
    ("POST", "/board/next"),
    ("GET", "/board/projects/<slug>/tasks/<int:number>"),
    ("PATCH", "/board/projects/<slug>/tasks/<int:number>"),
    ("POST", "/board/projects/<slug>/tasks/<int:number>/comments"),
    ("GET", "/board/projects/<slug>/tasks/<int:number>/history"),
})

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
    ("GET", "/conversations/<conversation_id>/rules"),
    ("POST", "/conversations/<conversation_id>/rules"),
    ("GET", "/conversations/<conversation_id>/tool-events"),
    ("GET", "/conversations/<conversation_id>/messages/<message_id>/context"),
    ("GET", "/conversations/<conversation_id>/participants/<participant_id>/context-preview"),
    ("GET", "/conversations/<conversation_id>/participants/<participant_id>/stream"),
    # Board: UI-Uebersicht, Projekte verwalten, loeschen, Kommentare aendern, Import
    ("GET", "/board"),
    ("GET", "/board/changes"),
    ("GET", "/board/projects/<slug>/tasks/<int:number>/comments"),
    ("POST", "/board/projects"),
    ("PUT", "/board/projects/<slug>"),
    ("DELETE", "/board/projects/<slug>"),
    ("DELETE", "/board/projects/<slug>/tasks/<int:number>"),
    ("PUT", "/board/comments/<comment_id>"),
    ("DELETE", "/board/comments/<comment_id>"),
    ("POST", "/board/import"),
})

# Ohne Token erreichbar (PUBLIC_GET_PATHS und statische Dateien in app.py).
PUBLIC = frozenset({
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/api-docs"),
    ("GET", "/openapi.json"),
    ("GET", "/static/<path:filename>"),
})

HUMAN_ONLY_ERROR = {"type": "HumanOnly", "error": "Nur für den Menschen-Zugang."}


def agent_may(method: str, rule: str) -> bool:
    """Darf ein Agent diese Route aufrufen? HEAD zaehlt wie GET."""
    method = "GET" if method == "HEAD" else method
    return (method, rule) in AGENT_ALLOWED
