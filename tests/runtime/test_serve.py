"""AP 5 / B6: produktiver WSGI-Server (waitress), Entwicklungsserver nur mit --debug."""

import socket
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from conclave.runtime import serve as serve_module

waitress = pytest.importorskip("waitress")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_serve_uses_waitress_by_default():
    app = MagicMock()
    port = _free_port()
    with patch("waitress.serve") as waitress_serve:
        serve_module.serve(app, "127.0.0.1", port)
    waitress_serve.assert_called_once()
    args, kwargs = waitress_serve.call_args
    assert args == (app,)
    (sock,) = kwargs["sockets"]
    try:
        assert sock.getsockname() == ("127.0.0.1", port)
    finally:
        sock.close()
    assert "host" not in kwargs and "port" not in kwargs
    assert kwargs["threads"] == serve_module.DEFAULT_THREADS
    app.run.assert_not_called()


def _occupy(port):
    """Lauschender Socket wie ein anderer Server (mit SO_REUSEADDR, wie waitress/werkzeug)."""
    other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    other.bind(("127.0.0.1", port))
    other.listen()
    return other


def test_second_instance_cannot_bind_a_port_in_use():
    """Regression: unter Windows liefen zwei Instanzen auf demselben Port."""
    port = _free_port()
    other = _occupy(port)
    try:
        with pytest.raises(OSError):
            serve_module.bind_server_socket("127.0.0.1", port)
        with patch("waitress.serve") as waitress_serve, pytest.raises(SystemExit, match="belegt"):
            serve_module.serve(MagicMock(), "127.0.0.1", port)
        waitress_serve.assert_not_called()
    finally:
        other.close()


def test_port_check_reports_port_in_use():
    from conclave.runtime.process import find_free_port, is_port_available

    port = _free_port()
    other = _occupy(port)
    try:
        assert is_port_available("127.0.0.1", port) is False
        assert find_free_port("127.0.0.1", preferred=port) != port
    finally:
        other.close()
    assert is_port_available("127.0.0.1", port) is True


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
         patch("conclave.infrastructure.log.configure_logging"), \
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
