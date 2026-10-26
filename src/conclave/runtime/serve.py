"""WSGI-Server fuer conclave-api / conclave desktop (AP 5 / B6).

Standard ist waitress (reines Python, Windows und Linux). Der Flask-
Entwicklungsserver mit Werkzeug-Debugger laeuft nur noch mit ``--debug``
bzw. ``CONCLAVE_DEBUG``.
"""

import os
import socket

from conclave.runtime.process import set_exclusive_bind

DEFAULT_THREADS = 16


def waitress_options() -> dict:
    """Einstellungen fuer waitress.

    threads: Streams (Orchestrierung, Auto-Loop) belegen je einen Thread fuer
    die Dauer der Modellaufrufe; 4 (waitress-Default) reicht nicht. SSE-Events
    sendet waitress ohne Pufferung (siehe tests/runtime/test_serve.py).
    """
    threads = int(os.environ.get("CONCLAVE_SERVER_THREADS", DEFAULT_THREADS))
    return {
        "threads": max(1, threads),
        "ident": "conclave",
    }


def bind_server_socket(host: str, port: int) -> socket.socket:
    """Server-Socket exklusiv binden: ein belegter Port fuehrt zu OSError."""
    family, socktype, proto, _, address = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
    sock = socket.socket(family, socktype, proto)
    try:
        set_exclusive_bind(sock)
        sock.bind(address)
    except OSError:
        sock.close()
        raise
    return sock


def serve(app, host: str, port: int, debug: bool = False) -> None:
    if debug:
        app.run(host=host, port=port, debug=True)
        return
    from waitress import serve as waitress_serve

    # waitress bindet selbst mit SO_REUSEADDR - unter Windows liefe eine zweite
    # Instanz dann stillschweigend auf demselben Port. Daher vorgebundener Socket.
    try:
        sock = bind_server_socket(host, port)
    except OSError as exc:
        raise SystemExit(f"FEHLER: {host}:{port} ist belegt oder nicht verfuegbar ({exc}).") from exc
    waitress_serve(app, sockets=[sock], **waitress_options())
