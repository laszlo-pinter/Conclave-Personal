"""Korrekturen aus der Doku-Pruefung vor v0.2.0.

- context_files in den Chat-Regeln bleibt im Workspace (Sicherheitsbefund)
- Workspace-Default ist ueberall der Plattform-Default, nicht "/workspace"
- Provider-Fehler liefern 429/504/502 statt 500; unbekannte Conversation beim Invoke 404
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from conclave.application.workspace_security import workspace_root
from conclave.domain.conversation import Conversation
from conclave.infrastructure.universal.adapter import _load_context_files


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "docs").mkdir(parents=True)
    (ws / "docs" / "ziel.md").write_text("ZIEL", encoding="utf-8")
    (ws / ".private").mkdir()
    (ws / ".private" / "geheim.md").write_text("GEHEIM", encoding="utf-8")
    (ws / "gross.md").write_text("x" * 2000, encoding="utf-8")
    (tmp_path / "ausserhalb.md").write_text("AUSSERHALB", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(ws))
    monkeypatch.setenv("CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES", "1000")
    return ws


def _conv(rules):
    conv = Conversation(id="c", topic="t")
    conv.rules = rules
    return conv


def test_context_files_loads_workspace_file(workspace):
    assert "ZIEL" in _load_context_files(_conv("context_files: docs/ziel.md"))


@pytest.mark.parametrize("path_fn", [
    lambda ws: str(ws.parent / "ausserhalb.md"),          # absoluter Pfad
    lambda ws: "../ausserhalb.md",                         # Ausbruch
    lambda ws: "docs/../../ausserhalb.md",
    lambda ws: ".private/geheim.md",                       # versteckt
    lambda ws: "gross.md",                                 # ueber dem Agent-Leselimit
])
def test_context_files_rejects_paths_outside_limits(workspace, path_fn):
    loaded = _load_context_files(_conv(f"context_files: {path_fn(workspace)}"))
    assert loaded == ""


def test_workspace_root_defaults_to_platform_path(monkeypatch, tmp_path):
    monkeypatch.delenv("CONCLAVE_WORKSPACE", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    from conclave.runtime.paths import get_runtime_paths
    root = workspace_root()
    assert root == get_runtime_paths().workspace_dir.resolve()
    assert root != Path("/workspace").resolve()


def test_workspace_root_uses_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "eigen"))
    assert workspace_root() == (tmp_path / "eigen").resolve()


# ── HTTP-Codes ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("error,status", [
    ("ProviderRateLimit", 429),
    ("ProviderTimeout", 504),
    ("ProviderUnavailable", 502),
])
def test_provider_errors_map_to_http_status(error, status):
    pytest.importorskip("flask")
    import conclave.domain.errors as errors
    from conclave.api.app import create_app

    exc_cls = getattr(errors, error)
    try:
        exc = exc_cls("anthropic")
    except TypeError:
        exc = exc_cls("anthropic", "msg")
    handler = MagicMock()
    handler.invoke_participant.side_effect = exc
    client = create_app(handler).test_client()
    resp = client.post("/conversations/c1/participants/p1/invoke", json={})
    assert resp.status_code == status
    assert resp.get_json()["type"] == error


def test_invoke_unknown_conversation_returns_404(service):
    pytest.importorskip("flask")
    from conclave.api.app import create_app
    from conclave.cli.handler import CLIHandler

    client = create_app(CLIHandler(service)).test_client()
    resp = client.post("/conversations/does-not-exist/participants/p1/invoke", json={})
    assert resp.status_code == 404


# ── Kleinere Korrekturen ──────────────────────────────────────────────────

def test_swagger_does_not_contact_external_validator():
    from conclave.runtime.assets import get_asset_root
    js = (get_asset_root() / "static" / "js" / "swagger-init.js").read_text(encoding="utf-8")
    assert "validatorUrl:null" in js.replace(" ", "")


def test_openapi_version_matches_project_version():
    import json
    import tomllib
    from conclave.runtime.assets import get_asset_root
    root = Path(__file__).resolve().parents[2]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    spec = json.loads((get_asset_root() / "static" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == version


def test_audit_and_run_repository_ports_are_separate():
    from conclave.application.ports import AuditRepository, RunRepository
    from conclave.infrastructure.sqlite.audit_repository import SQLiteAuditRepository
    from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository
    import inspect
    sig = inspect.signature(RunRepository.list_by_conversation)
    assert "limit" in sig.parameters
    assert hasattr(AuditRepository, "list_by_date_range")
    assert not hasattr(RunRepository, "list_by_date_range")
    assert isinstance(SQLiteAuditRepository(MagicMock()), AuditRepository)
    assert isinstance(SQLiteRunRepository(MagicMock()), RunRepository)


def test_mcp_server_reads_token_per_request():
    source = (Path(__file__).resolve().parents[2] / "src/conclave/mcp_server.py").read_text(encoding="utf-8")
    headers_fn = source.split("def _headers()", 1)[1].split("\ndef ", 1)[0]
    assert "read_token()" in headers_fn
    assert "API_KEY = read_token()" not in source
