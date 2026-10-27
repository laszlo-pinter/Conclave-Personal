"""KanzoMcpAdapter - liest Tickets und schreibt Kommentare ueber Kanzos MCP-Endpunkt.

Conclave spricht Kanzo ausschliesslich ueber MCP an (Kanzo steht unter
AGPL-3.0; es wird kein Code uebernommen). Die einzige schreibende Aktion ist
``add_comment``.
"""

from __future__ import annotations

import asyncio
import re

from conclave.domain.errors import TaskNotFound, TaskSourceError
from conclave.domain.ticket import Ticket
from conclave.infrastructure.kanzo.parser import TASK_REF, parse_kanzo_task
from conclave.infrastructure.log import get_logger

logger = get_logger("infrastructure.kanzo")

# Kanzo meldet "no task ..." / "no project ..."; manche MCP-Server stellen "Error executing tool x: " voran
_NOT_FOUND = re.compile(r"(?:^|: )no (?:task|project) ")


def _mcp_client():
    try:
        from mcp import Client
    except ImportError as exc:  # pragma: no cover - abhaengig von der Installation
        raise TaskSourceError(
            "Fuer Kanzo braucht Conclave das MCP-SDK: pip install \"conclave-personal[mcp]\""
        ) from exc
    return Client


class KanzoMcpAdapter:
    """``TaskSource`` und ``CommentSink`` fuer Kanzo.

    Args:
        server: URL von Kanzos MCP-Endpunkt (aus ``[kanzo] url``) - in Tests
            auch ein ``MCPServer``-Objekt fuer eine Verbindung ohne Netzwerk.
        timeout: Sekunden pro Tool-Aufruf.
    """

    def __init__(self, server, *, timeout: float = 30.0) -> None:
        self._server = server
        self._timeout = timeout

    @staticmethod
    def _check_ref(task_ref: str) -> None:
        if not isinstance(task_ref, str) or not TASK_REF.match(task_ref):
            raise ValueError(f"Ungueltige Ticket-Referenz {task_ref!r} (erwartet z. B. 'api#12')")

    def get_task(self, task_ref: str) -> Ticket:
        self._check_ref(task_ref)
        return parse_kanzo_task(self._call("get_task", {"id": task_ref}, task_ref))

    def add_comment(self, task_ref: str, body: str, author: str) -> None:
        self._check_ref(task_ref)
        self._call("add_comment", {"id": task_ref, "body": body, "author": author}, task_ref)

    def _call(self, tool: str, arguments: dict, task_ref: str) -> str:
        Client = _mcp_client()

        async def run() -> str:
            async with Client(self._server, read_timeout_seconds=self._timeout) as client:
                result = await client.call_tool(tool, arguments)
            text = " ".join(getattr(block, "text", "") for block in result.content).strip()
            if result.is_error:
                if _NOT_FOUND.search(text):
                    raise TaskNotFound(task_ref, text)
                raise TaskSourceError(f"Kanzo {tool}: {text[:300]}")
            return text

        try:
            return asyncio.run(asyncio.wait_for(run(), self._timeout + 5))
        except (TaskSourceError, ValueError):
            raise
        except Exception as exc:  # Verbindung, HTTP-Fehler, abgeschaltetes /mcp
            logger.warning("Kanzo nicht erreichbar (%s): %s", tool, exc)
            raise TaskSourceError(
                "Kanzo ist unter der konfigurierten Adresse nicht erreichbar. Laeuft das Board, "
                "und ist MCP ueber HTTP aktiv (mcp_http = true in Kanzos config.toml)?"
            ) from exc
