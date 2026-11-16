"""Startet das installierte Board-Paket in einer frischen Umgebung und prueft es (T1, CI).

- ``conclave`` (Personal), ``anthropic``, ``openai``, ``httpx`` und ``mcp`` sind nicht installiert
- ``conclave-board serve`` startet, ``/health`` antwortet ohne Token
- mit dem Mensch-Token laesst sich ein Projekt anlegen, ohne Token nicht
- ein Agent-Token sieht die Uebersicht nicht (403)

Aufruf mit dem Python der frischen Umgebung: python scripts/release/smoke_board.py
"""

import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _request(url, method="GET", token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310 - nur 127.0.0.1
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


def main() -> int:
    present = [name for name in ("conclave", "anthropic", "openai", "httpx", "mcp")
               if importlib.util.find_spec(name) is not None]
    if present:
        print(f"FEHLER: in der Umgebung installiert: {present}", file=sys.stderr)
        return 1
    executable = shutil.which("conclave-board", path=str(Path(sys.executable).parent))
    if not executable:
        print("FEHLER: conclave-board nicht neben diesem Python installiert", file=sys.stderr)
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="conclave-board-smoke-"))
    port = _free_port()
    process = subprocess.Popen([executable, "serve", "--port", str(port), "--db", str(tmp / "board.db"),
                                "--config-dir", str(tmp / "config")])
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                status, health = _request(f"{base}/health")
                break
            except OSError:
                time.sleep(0.2)
        else:
            print("FEHLER: Server antwortet nicht", file=sys.stderr)
            return 1
        human = (tmp / "config" / "api.token").read_text(encoding="utf-8").strip()
        agent = (tmp / "config" / "agent.token").read_text(encoding="utf-8").strip()
        checks = {
            "health": status == 200 and health["product"] == "conclave-board",
            "ohne Token": _request(f"{base}/board")[0] == 401,
            "Projekt anlegen": _request(f"{base}/board/projects", "POST", human, {"slug": "smoke", "name": "S"})[0] == 201,
            "Agent sieht Uebersicht nicht": _request(f"{base}/board", token=agent)[0] == 403,
            "Agent legt Ticket an": _request(f"{base}/board/tasks", "POST", agent,
                                             {"project": "smoke", "title": "T"})[0] == 201,
            "keine Personal-Route": _request(f"{base}/conversations", token=human)[0] == 404,
        }
        failed = [name for name, ok in checks.items() if not ok]
        for name, ok in checks.items():
            print(f"{'ok    ' if ok else 'FEHLER'} {name}")
        return 1 if failed else 0
    finally:
        process.terminate()
        process.wait(timeout=30)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
