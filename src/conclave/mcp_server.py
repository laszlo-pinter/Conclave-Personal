# src/conclave/mcp_server.py
"""
Conclave MCP-Server — macht Conclave als Tool fuer Claude Code / Desktop verfuegbar.

Starten:
    python -m conclave.mcp_server

Oder in Claude Code settings.json:
    {
      "mcpServers": {
        "conclave": {
          "command": "python",
          "args": ["-m", "conclave.mcp_server"],
          "env": {
            "CONCLAVE_API_URL": "http://localhost:8000",
            "CONCLAVE_API_KEY": ""
          }
        }
      }
    }
"""

import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

# ── Config ────────────────────────────────────────────────────────────────

API_URL = os.environ.get("CONCLAVE_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("CONCLAVE_API_KEY", "")

mcp = FastMCP(
    "Conclave",
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
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _get(path: str, params: dict | None = None) -> dict:
    r = httpx.get(f"{API_URL}{path}", headers=_headers(), params=params, timeout=60)
    r.raise_for_status()
    return r.json() if r.text else {}


def _post(path: str, body: dict | None = None) -> dict:
    r = httpx.post(f"{API_URL}{path}", headers=_headers(), json=body or {}, timeout=120)
    r.raise_for_status()
    return r.json() if r.text else {}


def _delete(path: str, body: dict | None = None) -> dict:
    r = httpx.request("DELETE", f"{API_URL}{path}", headers=_headers(), json=body, timeout=60)
    r.raise_for_status()
    return r.json() if r.text else {}


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


@mcp.tool()
def conclave_delete_conversation(conversation_id: str) -> dict:
    """Loescht eine Conversation inkl. aller Messages.

    Args:
        conversation_id: Die ID der Conversation
    """
    _delete(f"/conversations/{conversation_id}")
    return {"deleted": conversation_id}


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


@mcp.tool()
def conclave_delete_file(filepath: str) -> dict:
    """Loescht eine Datei aus dem Conclave-Workspace.

    Args:
        filepath: Relativer Pfad im Workspace
    """
    _delete(f"/workspace/{filepath}")
    return {"deleted": filepath}


# ── Entrypoint ────────────────────────────────────────────────────────────

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
