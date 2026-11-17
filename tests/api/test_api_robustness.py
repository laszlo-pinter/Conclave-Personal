"""#95: Robustheit der API.

- Workspace-Liste: kaputte Symlinks und verschwundene Eintraege ergeben kein 500; Symlinks nach
  draussen fehlen in der Liste (gleiche Regel wie beim Lesen).
- JSON-Body: Array, Skalar oder kaputtes JSON ergeben auf jeder Route 400 statt 500.
- ``Retry-After``: nur endliche Werte ab 0, hoechstens ``MAX_RETRY_AFTER_SECONDS``.
"""

import math
import os

import httpx
import pytest

pytest.importorskip("flask")

from conclave.cli.config import ConclaveConfig  # noqa: E402
from conclave.infrastructure.universal.resilient import MAX_RETRY_AFTER_SECONDS, _parse_retry_after  # noqa: E402

HUMAN, AGENT = "cvh_mensch", "cva_agent"


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "notiz.md").write_text("hallo", encoding="utf-8")
    return root


@pytest.fixture
def client(tmp_path, ws, monkeypatch):
    from conclave.api.server import _build_app
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(ws))
    monkeypatch.setenv("CONCLAVE_BACKUP_DIR", str(tmp_path / "backups"))
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT))
    app.config["TESTING"] = True
    c = app.test_client()
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {HUMAN}"
    return c


def _symlink(link, target):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:          # Windows ohne Entwicklermodus/Recht
        pytest.skip(f"Symlinks hier nicht moeglich: {exc}")


# ── Workspace-Liste ──────────────────────────────────────────────────────

def test_broken_symlink_does_not_break_the_list(client, ws):
    _symlink(ws / "kaputt.md", ws / "gibt-es-nicht.md")
    resp = client.get("/workspace")
    assert resp.status_code == 200
    assert [f["path"] for f in resp.get_json()["files"]] == ["notiz.md"]


def test_symlink_out_of_the_workspace_is_not_listed(client, ws, tmp_path):
    outside = tmp_path / "draussen.md"
    outside.write_text("geheim", encoding="utf-8")
    _symlink(ws / "raus.md", outside)
    _symlink(ws / "drin.md", ws / "notiz.md")
    paths = [f["path"] for f in client.get("/workspace").get_json()["files"]]
    assert paths == ["drin.md", "notiz.md"]                      # innerhalb ja, nach draussen nein
    assert client.get("/workspace/raus.md").status_code == 403   # Lesen hat dieselbe Regel


def test_entry_that_vanishes_during_the_listing_is_skipped(client, ws, monkeypatch):
    (ws / "weg.md").write_text("x", encoding="utf-8")
    real_stat = os.stat

    def flaky_stat(path, *args, **kwargs):
        if str(path).endswith("weg.md"):
            raise FileNotFoundError(path)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", flaky_stat)
    resp = client.get("/workspace")
    assert resp.status_code == 200 and [f["path"] for f in resp.get_json()["files"]] == ["notiz.md"]


def test_list_entries_carry_size_and_time(client):
    entry = client.get("/workspace").get_json()["files"][0]
    assert entry["size"] == 5 and entry["modified"] > 0


# ── JSON-Body ────────────────────────────────────────────────────────────

ROUTES = [
    ("POST", "/agents"), ("PUT", "/agents/a1"),
    ("POST", "/conversations/c1/topic"), ("POST", "/conversations/c1/rules"),
    ("POST", "/conversations/c1/floor/grant"), ("POST", "/conversations/c1/participants"),
    ("POST", "/conversations/c1/messages"), ("POST", "/conversations/c1/orchestrate"),
    ("POST", "/conversations/c1/orchestrate-parallel"), ("POST", "/conversations/c1/orchestrate-parallel-stream"),
    ("POST", "/conversations/c1/auto-loop"), ("POST", "/consultations/x/retry"),
    ("PUT", "/settings"), ("POST", "/restore"),
    ("POST", "/board/v1/next"), ("POST", "/board/next"),
]


@pytest.mark.parametrize("raw", ["[1, 2]", '"text"', "42", "null", "{kaputt"], ids=["array", "string", "number",
                                                                                      "null", "invalid"])
@pytest.mark.parametrize("method, path", ROUTES)
def test_non_object_json_body_is_400(client, method, path, raw):
    resp = client.open(path, method=method, data=raw, content_type="application/json")
    assert resp.status_code == 400, (method, path, raw, resp.status_code, resp.get_json())
    assert resp.get_json()["type"] == "ValidationError"


def test_empty_body_still_means_no_fields(client):
    assert client.post("/board/v1/next", data="", content_type="application/json").status_code == 200


# ── Retry-After ──────────────────────────────────────────────────────────

def _response(header=None, body=""):
    headers = {"retry-after": header} if header is not None else {}
    return httpx.Response(429, headers=headers, text=body)


@pytest.mark.parametrize("header, expected", [
    ("7", 7.0), ("0", 0.0), ("2.5", 2.5),
    ("-1", None), ("nan", None), ("inf", None), ("-inf", None), ("abc", None),
    ("1e100", MAX_RETRY_AFTER_SECONDS), ("3600", MAX_RETRY_AFTER_SECONDS),
])
def test_retry_after_header_bounds(header, expected):
    assert _parse_retry_after(_response(header)) == expected


def test_retry_after_in_the_body_has_the_same_bounds():
    assert _parse_retry_after(_response(body="Please retry in 7.371630858s.")) == pytest.approx(7.371630858)
    assert _parse_retry_after(_response(body="Please retry in 99999s.")) == MAX_RETRY_AFTER_SECONDS
    assert _parse_retry_after(_response(header="nan", body="Please retry in 3s.")) == 3.0
    assert _parse_retry_after(_response(body="nichts")) is None


def test_max_retry_after_is_finite_and_positive():
    assert math.isfinite(MAX_RETRY_AFTER_SECONDS) and MAX_RETRY_AFTER_SECONDS > 0
