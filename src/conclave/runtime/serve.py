"""WSGI-Server fuer conclave-api / conclave desktop (AP 5 / B6).

Standard ist waitress (reines Python, Windows und Linux). Der Flask-
Entwicklungsserver mit Werkzeug-Debugger laeuft nur noch mit ``--debug``
bzw. ``CONCLAVE_DEBUG``.
"""

import os

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


def serve(app, host: str, port: int, debug: bool = False) -> None:
    if debug:
        app.run(host=host, port=port, debug=True)
        return
    from waitress import serve as waitress_serve

    waitress_serve(app, host=host, port=port, **waitress_options())
