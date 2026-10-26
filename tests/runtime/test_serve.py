"""AP 5 / B6: produktiver WSGI-Server (waitress), Entwicklungsserver nur mit --debug."""

import socket
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from conclave.runtime import serve as serve_module

waitress = pytest.importorskip("waitress")


def test_serve_uses_waitress_by_default():
    app = MagicMock()
    with patch("waitress.serve") as waitress_serve:
        serve_module.serve(app, "127.0.0.1", 8123)
    waitress_serve.assert_called_once()
    args, kwargs = waitress_serve.call_args
    assert args == (app,)
    assert kwargs["host"] == "127.0.0.1" and kwargs["port"] == 8123
    assert kwargs["threads"] == serve_module.DEFAULT_THREADS
    app.run.assert_not_called()


def test_debug_uses_flask_development_server():
    app = MagicMock()
    with patch("waitress.serve") as waitress_serve:
        serve_module.serve(app, "127.0.0.1", 8123, debug=True)
    app.run.assert_called_once_with(host="127.0.0.1", port=8123, debug=True)
    waitress_serve.assert_not_called()


def test_thread_count_is_configurable(monkeypatch):
    monkeypatch.setenv("CONCLAVE_SERVER_THREADS", "32")
    assert serve_module.waitress_options()["threads"] == 32
    monkeypatch.setenv("CONCLAVE_SERVER_THREADS", "0")
    assert serve_module.waitress_options()["threads"] == 1


def test_server_main_uses_runtime_serve(monkeypatch):
    import conclave.api.server as server

    config = MagicMock(host="127.0.0.1", port=8123, debug=False)
    app = MagicMock()
    with patch.object(server, "_build_app", return_value=(app, config)), \
         patch("conclave.runtime.serve.serve") as serve:
        server.main()
    serve.assert_called_once_with(app, "127.0.0.1", 8123, debug=False)


def test_waitress_streams_server_sent_events_without_buffering():
    """SSE-Events muessen live ankommen, nicht erst am Ende des Streams."""
    from flask import Flask, Response

    app = Flask(__name__)

    @app.get("/stream")
    def stream():
        def generate():
            for i in range(3):
                yield f"data: {i}\n\n"
                time.sleep(0.5)
        return Response(generate(), mimetype="text/event-stream")

    server = waitress.create_server(app, host="127.0.0.1", port=0, **serve_module.waitress_options())
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        port = server.effective_port
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            start = time.monotonic()
            sock.sendall(b"GET /stream HTTP/1.1\r\nHost: localhost\r\n\r\n")
            received = b""
            while b"data: 0" not in received:
                chunk = sock.recv(4096)
                assert chunk, "Verbindung vorzeitig geschlossen"
                received += chunk
            first_event_after = time.monotonic() - start
        # Ohne Pufferung kommt das erste Event sofort, nicht erst nach ~1,5 s Stream-Dauer
        assert first_event_after < 0.4, f"erstes Event erst nach {first_event_after:.2f}s"
    finally:
        server.close()
