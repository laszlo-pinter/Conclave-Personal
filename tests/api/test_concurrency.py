"""AP 5 / B6: Parallele Anfragen gegen einen echten Server mit SQLite bleiben konsistent."""

import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest
pytest.importorskip("flask")

from conclave.cli.config import ConclaveConfig

WRITERS = 20
MESSAGES_PER_WRITER = 5


@pytest.fixture(params=["waitress", "werkzeug"])
def server(request, tmp_path, monkeypatch):
    """Produktivserver (waitress, Thread-Pool) und Entwicklungsserver (ein Thread je Anfrage)."""
    from conclave.api.server import _build_app

    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    app, config = _build_app(ConclaveConfig(db_path=tmp_path / "conclave.db", api_key=""))
    if request.param == "waitress":
        waitress = pytest.importorskip("waitress")
        from conclave.runtime.serve import waitress_options
        srv = waitress.create_server(app, host="127.0.0.1", port=0, **waitress_options())
        thread = threading.Thread(target=srv.run, daemon=True)
        port, stop = srv.effective_port, srv.close
    else:
        from werkzeug.serving import make_server
        srv = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        port, stop = srv.server_port, srv.shutdown
    thread.start()
    yield f"http://127.0.0.1:{port}", config.api_key, config.db_path
    stop()
    thread.join(timeout=5)


def _call(base, token, method, path, body=None):
    data = json.dumps(body if body is not None else {}).encode() if method != "GET" else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def test_parallel_messages_and_reads_stay_consistent(server):
    base, token, db_path = server
    status, conv = _call(base, token, "POST", "/conversations")
    assert status == 201
    conv_id = conv["conversation_id"]

    def writer(n):
        results = []
        for i in range(MESSAGES_PER_WRITER):
            results.append(_call(base, token, "POST", f"/conversations/{conv_id}/messages",
                                 {"content": f"writer {n} message {i}"})[0])
            results.append(_call(base, token, "GET", f"/conversations/{conv_id}")[0])
            results.append(_call(base, token, "POST", "/conversations")[0])
        return results

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        statuses = [s for result in pool.map(writer, range(WRITERS)) for s in result]

    errors = [s for s in statuses if s not in (200, 201)]
    assert errors == []

    status, data = _call(base, token, "GET", f"/conversations/{conv_id}")
    assert status == 200
    sequences = [m["sequence"] for m in data["messages"]]
    assert len(sequences) == WRITERS * MESSAGES_PER_WRITER
    assert sorted(sequences) == list(range(1, WRITERS * MESSAGES_PER_WRITER + 1))

    status, listing = _call(base, token, "GET", "/conversations")
    assert len(listing["conversations"]) == 1 + WRITERS * MESSAGES_PER_WRITER

    # Alles ist wirklich committet: eine frische Verbindung sieht dieselben Daten
    import sqlite3
    with sqlite3.connect(db_path) as fresh:
        assert fresh.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv_id,)).fetchone()[0] \
            == WRITERS * MESSAGES_PER_WRITER
