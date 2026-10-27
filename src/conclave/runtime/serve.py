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


def start_background_workers(app, debug: bool, environ=None) -> list:
    """Startet die in ``app.extensions["conclave_workers"]`` registrierten Worker.

    Bewusst hier und nicht in ``create_app``: Tests bauen viele Apps, und der
    Reloader im Debug-Modus fuehrt den Start zweimal aus.
    """
    from conclave.application.consultation_worker import should_start_workers

    workers = list(getattr(app, "extensions", {}).get("conclave_workers", []))
    if not should_start_workers(debug, os.environ if environ is None else environ):
        return []
    for worker in workers:
        worker.start()
    return workers


def serve(app, host: str, port: int, debug: bool = False) -> None:
    if debug:
        start_background_workers(app, debug)
        app.run(host=host, port=port, debug=True)
        return
    from waitress import serve as waitress_serve

    # waitress bindet selbst mit SO_REUSEADDR - unter Windows liefe eine zweite
    # Instanz dann stillschweigend auf demselben Port. Daher vorgebundener Socket.
    try:
        sock = bind_server_socket(host, port)
    except OSError as exc:
        raise SystemExit(f"FEHLER: {host}:{port} ist belegt oder nicht verfuegbar ({exc}).") from exc
    # Erst nach dem Binden: eine zweite Instanz auf belegtem Port darf die laufenden
    # Consultations der ersten nicht als unterbrochen markieren.
    start_background_workers(app, debug)
    waitress_serve(app, sockets=[sock], **waitress_options())
