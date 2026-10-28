# src/conclave/mcp_server.py
"""
Conclave MCP-Server — macht Conclave als Tool fuer Claude Code / Desktop verfuegbar.

Starten:
    conclave-mcp            (oder: python -m conclave.mcp_server)

Benoetigt das Extra ``mcp`` (MCP Python SDK 2.x): pip install "conclave-personal[mcp]"

Der MCP-Server nutzt den Agent-Zugang (seit v0.5.0): das Token aus
CONCLAVE_AGENT_KEY oder, falls leer, aus agent.token im Konfigurationsverzeichnis.
api.token (Mensch-Token) liest er nie. CONCLAVE_API_KEY gilt nur noch als
Rueckfall fuer alte Einrichtungen; liefert der Server dafuer die Rolle "human",
steht eine Warnung auf stderr. Den passenden Befehl zeigt `conclave token show --agent`.

In Claude Code:
    claude mcp add Conclave -s user -e CONCLAVE_API_URL=http://localhost:8000 -- conclave-mcp
"""

import os
import sys
import threading
from importlib.metadata import PackageNotFoundError, version

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from conclave.runtime.api_token import read_agent_token
from conclave.runtime.env import env_secret

# ── Config ────────────────────────────────────────────────────────────────

API_URL = os.environ.get("CONCLAVE_API_URL", "http://localhost:8000")
# Token: CONCLAVE_AGENT_KEY, sonst agent.token, sonst (alt) CONCLAVE_API_KEY - nie api.token.
# Wird pro Anfrage gelesen, damit der MCP-Client auch vor dem ersten Serverstart laufen darf.


def read_token() -> str:
    """Token fuer den MCP-Server: der Agent-Zugang, nie die Datei api.token."""
    return read_agent_token() or env_secret("CONCLAVE_API_KEY")


def _package_version() -> str:
    try:
        return version("conclave-personal")
    except PackageNotFoundError:  # Quellbaum ohne Installation
        return "0.0.0"


mcp = MCPServer(
    "Conclave",
    version=_package_version(),
    instructions=(
        "Conclave ist ein host-gesteuertes Multi-Model-Konversationssystem. "
        "Du kannst damit mehrere KI-Modelle (Claude, GPT) in strukturierten "
        "Diskussionen orchestrieren. Der typische Ablauf ist: "
        "1) Conversation erstellen, 2) Participants hinzufuegen, "
        "3) Nachricht senden, 4) Modelle aufrufen oder orchestrieren, "
        "5) Ergebnisse lesen. Workspace und Usage helfen beim lokalen Arbeiten."
    ),
)


# ── HTTP Client ───────────────────────────────────────────────────────────

def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    token = read_token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _result(r: httpx.Response) -> dict:
    """Antwort der Conclave-API; Fehler als ToolError mit Conclaves eigener Meldung."""
    if r.is_error:
        try:
            body = r.json()
        except ValueError:
            body = None
        detail = (body.get("error") if isinstance(body, dict) else None) or r.text
        hint = " (Token pruefen: CONCLAVE_AGENT_KEY oder agent.token)" if r.status_code == 401 else ""
        raise ToolError(f"Conclave-API {r.status_code}: {detail}{hint}")
    return r.json() if r.text else {}


_role_lock = threading.Lock()
_role_checked = False

HUMAN_TOKEN_WARNING = (
    "WARNUNG: conclave-mcp nutzt das Mensch-Token. Agenten haben damit vollen Zugang zu Conclave "
    "(Einstellungen, Loeschen, Backups). Bitte CONCLAVE_AGENT_KEY setzen bzw. CONCLAVE_API_KEY aus der "
    "MCP-Konfiguration entfernen - der Befehl steht in `conclave token show --agent`."
)


def _check_role() -> None:
    """Einmal pro Prozess: GET /auth/whoami. Bei Rolle human eine deutliche Warnung auf stderr (4.2)."""
    global _role_checked
    with _role_lock:
        if _role_checked:
            return
        _role_checked = True
    try:
        r = httpx.get(f"{API_URL}/auth/whoami", headers=_headers(), timeout=10)
    except httpx.HTTPError:
        r = None
    if r is None or r.status_code not in (200, 404):
        # Server noch nicht da oder Token falsch: beim naechsten Aufruf erneut pruefen
        with _role_lock:
            _role_checked = False
        return
    if r.status_code == 404:
        print("WARNUNG: Der Conclave-Server kennt keine getrennten Zugaenge (aelter als v0.5.0).",
              file=sys.stderr, flush=True)
    elif r.status_code == 200:
        try:
            role = r.json().get("role")
        except (ValueError, AttributeError):
            return
        if role == "human":
            print(HUMAN_TOKEN_WARNING, file=sys.stderr, flush=True)


def _request(method: str, path: str, *, timeout: float, **kwargs) -> dict:
    _check_role()
    try:
        r = httpx.request(method, f"{API_URL}{path}", headers=_headers(), timeout=timeout, **kwargs)
    except httpx.HTTPError as exc:
        raise ToolError(f"Conclave-Server unter {API_URL} nicht erreichbar: {exc}") from exc
    return _result(r)


def _get(path: str, params: dict | None = None) -> dict:
    return _request("GET", path, params=params, timeout=60)


def _post(path: str, body: dict | None = None) -> dict:
    return _request("POST", path, json=body or {}, timeout=120)


# ── Tools: Conversations ──────────────────────────────────────────────────

@mcp.tool()
def conclave_create_conversation(topic: str = "") -> dict:
    """Erstellt eine neue Conversation, optional mit Thema.

    Args:
        topic: Optionales Thema fuer die Conversation (z.B. "Microservices vs Monolith")
    """
    result = _post("/conversations")
    conv_id = result.get("conversation_id")
    if topic and conv_id:
        _post(f"/conversations/{conv_id}/topic", {"topic": topic})
    return {"conversation_id": conv_id, "topic": topic}


@mcp.tool()
def conclave_list_conversations() -> dict:
    """Listet alle Conversations auf."""
    return _get("/conversations")


@mcp.tool()
def conclave_get_conversation(conversation_id: str) -> dict:
    """Ruft eine Conversation mit allen Messages und Participants ab.

    Args:
        conversation_id: Die ID der Conversation
    """
    return _get(f"/conversations/{conversation_id}")


# Loeschen (Conversations, Workspace-Dateien) darf nur der Mensch (E2), daher kein Tool dafuer.


# ── Tools: Participants ───────────────────────────────────────────────────

@mcp.tool()
def conclave_add_participant(
    conversation_id: str,
    agent_id: str,
    name: str = "",
) -> dict:
    """Fuegt einen Agenten als Participant zu einer Conversation hinzu.

    Args:
        conversation_id: Die ID der Conversation
        agent_id: Die ID des Agenten (z.B. "Claude", "ChatGPT")
        name: Optionaler Anzeigename (Default: gleich wie agent_id)
    """
    return _post(f"/conversations/{conversation_id}/participants", {
        "participant_id": agent_id,
        "name": name or agent_id,
        "type": "model",
    })


@mcp.tool()
def conclave_list_agents() -> dict:
    """Listet alle verfuegbaren Agenten auf (vorkonfigurierte KI-Modelle)."""
    return _get("/agents")


# ── Tools: Messages ───────────────────────────────────────────────────────

@mcp.tool()
def conclave_send_message(conversation_id: str, content: str) -> dict:
    """Sendet eine User-Nachricht in eine Conversation.

    Args:
        conversation_id: Die ID der Conversation
        content: Der Nachrichtentext
    """
    return _post(f"/conversations/{conversation_id}/messages", {"content": content})


@mcp.tool()
def conclave_get_messages(conversation_id: str) -> list[dict]:
    """Gibt alle Nachrichten einer Conversation zurueck.

    Args:
        conversation_id: Die ID der Conversation
    """
    data = _get(f"/conversations/{conversation_id}")
    return data.get("messages", [])


# ── Tools: Invoke + Orchestrate ───────────────────────────────────────────

@mcp.tool()
def conclave_invoke(conversation_id: str, participant_id: str) -> dict:
    """Ruft einen einzelnen Participant auf und wartet auf seine Antwort.

    Args:
        conversation_id: Die ID der Conversation
        participant_id: Die ID des Participants (z.B. "Claude")
    """
    return _post(f"/conversations/{conversation_id}/participants/{participant_id}/invoke")


@mcp.tool()
def conclave_orchestrate(
    conversation_id: str,
    sequence: list[str],
    parallel: bool = False,
) -> dict:
    """Ruft mehrere Participants nacheinander oder gleichzeitig auf.

    Bei sequentiell: Jeder sieht die Antworten der Vorgaenger.
    Bei parallel: Alle sehen nur die bisherigen Nachrichten, nicht die Antworten der anderen.

    Args:
        conversation_id: Die ID der Conversation
        sequence: Liste von Participant-IDs in der gewuenschten Reihenfolge
        parallel: True fuer gleichzeitige Ausfuehrung
    """
    # parallel=True: ALLE Participants in EINE Gruppe -> echte gleichzeitige Ausfuehrung.
    # Vorher war es [[A],[B],[C]] = drei sequenzielle Einzel-Gruppen, was nichts paralleles
    # ergibt. Wer feiner steuern will (z.B. [[A,B],[C]] = zwei Wellen), nimmt direkt
    # POST /conversations/<id>/orchestrate-parallel mit eigener groups-Struktur.
    endpoint = "/orchestrate-parallel" if parallel else "/orchestrate"
    body = {"groups": [list(sequence)]} if parallel else {"sequence": sequence}
    return _post(f"/conversations/{conversation_id}{endpoint}", body)


@mcp.tool()
def conclave_export_conversation(conversation_id: str) -> dict:
    """Exportiert eine Conversation als persoenliches Backup/Arbeitsartefakt.

    Args:
        conversation_id: Die ID der Conversation
    """
    return _get(f"/conversations/{conversation_id}/export")


@mcp.tool()
def conclave_get_usage() -> dict:
    """Gibt den Token-Verbrauch pro Provider und Modell zurueck."""
    return _get("/usage")


# ── Tools: Workspace (Dateisystem) ────────────────────────────────────────

@mcp.tool()
def conclave_list_files() -> dict:
    """Listet alle Dateien im Conclave-Workspace.

    Der Workspace ist ein geteilter Ordner zwischen dir und den Agenten.
    Du kannst Dateien ablegen die Agenten lesen sollen, oder Ergebnisse
    von Agenten abrufen.
    """
    return _get("/workspace")


@mcp.tool()
def conclave_read_file(filepath: str) -> dict:
    """Liest eine Datei aus dem Conclave-Workspace.

    Args:
        filepath: Relativer Pfad im Workspace (z.B. "analyse.md" oder "daten/input.csv")
    """
    return _get(f"/workspace/{filepath}")


@mcp.tool()
def conclave_upload_file(filepath: str, content: str) -> dict:
    """Legt eine Datei im Conclave-Workspace ab.

    Agenten und du koennen die Datei danach lesen. Unterordner werden
    automatisch erstellt.

    Args:
        filepath: Relativer Pfad im Workspace (z.B. "ergebnis.md" oder "reports/zusammenfassung.txt")
        content: Der Dateiinhalt als Text
    """
    return _post(f"/workspace/{filepath}", {"content": content})


# ── Tools: Consultations (Zweitmeinung zu Kanzo-Tickets) ──────────────────

@mcp.tool()
def conclave_consult(task: str, question: str, context: str = "", include_previous: bool = False,
                     reviewers: list[str] | None = None) -> dict:
    """Bittet Conclave um eine Zweitmeinung zu einem Kanzo-Ticket.

    Conclave liest das Ticket selbst, fragt die erlaubten Reviewer-Modelle und
    schreibt jede Antwort als gekennzeichneten Kommentar in das Ticket
    ("Zweitmeinung von ... ueber Conclave, nicht geprueft"). Die Bearbeitung
    laeuft im Hintergrund; den Stand liefert conclave_get_consultation.
    Tickets, die nur fuer Menschen gedacht sind, werden abgelehnt.

    Args:
        task: Ticket-Referenz, z.B. "api#12"
        question: Was die Reviewer beantworten sollen
        context: Optionaler Zusatzkontext
        include_previous: Fruehere Conclave-Kommentare des Tickets mitgeben (Standard: nein)
        reviewers: Optional eine Teilmenge der erlaubten Reviewer (Agent-IDs)
    """
    body = {"task": task, "question": question, "context": context,
            "include_previous": include_previous, "requested_by": "mcp"}
    if reviewers:
        body["reviewers"] = reviewers
    return _post("/consultations", body)


@mcp.tool()
def conclave_get_consultation(consultation_id: str) -> dict:
    """Stand einer Consultation: Status, Reviewer mit Provider, Zustellungen.

    Args:
        consultation_id: ID aus conclave_consult
    """
    return _get(f"/consultations/{consultation_id}")


# ── Entrypoint ────────────────────────────────────────────────────────────

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
