"""U2 (conclave#111): Board-Modus in Personal (``[ui] mode = "board"``, Plan board-ui.md 3.3).

- ``/`` leitet auf ``/ui/board`` weiter, das Studio (Seite, Skripte, Stile) gibt 404 mit Hinweis.
- Die API bleibt gleich: Board, Agent, Reviewer-Herzschlag, Consultations (die Routen-Matrix und die
  MCP-Tests laufen zusaetzlich in beiden Modi).
- ``mode = "studio"`` (Standard) verhaelt sich wie v0.8.0, ``/ui/board`` ist zusaetzlich erreichbar.
- Ein ungueltiger Wert ergibt beim Start eine klare Meldung; ``conclave desktop`` und ``conclave web``
  oeffnen im Board-Modus die Board-Seite.
"""

from types import SimpleNamespace

import pytest

from conclave.cli.config import BOARD_PAGE_PATH, ConclaveConfig, ConfigError, UiSettings

HUMAN, AGENT, REVIEWER = "cvh_modus-mensch", "cva_modus-agent", "cvr_modus-reviewer"
STUDIO_FILES = ("/static/js/main.js", "/static/js/features/conversations.js", "/static/css/theme.css",
                "/static/css/components.css")


def _client(tmp_path, monkeypatch, mode):
    from conclave.api.server import _build_app

    for name, file in (("CONCLAVE_SECRET_KEY_FILE", "secret.key"), ("CONCLAVE_API_TOKEN_FILE", "api.token"),
                       ("CONCLAVE_AGENT_TOKEN_FILE", "agent.token"),
                       ("CONCLAVE_REVIEWER_TOKEN_FILE", "reviewer.token")):
        monkeypatch.setenv(name, str(tmp_path / file))
    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("CONCLAVE_BACKUP_DIR", str(tmp_path / "backups"))
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT,
                                       reviewer_api_key=REVIEWER, ui=UiSettings(mode)))
    app.config["TESTING"] = True
    return app.test_client()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def board_mode(tmp_path, monkeypatch):
    return _client(tmp_path, monkeypatch, "board")


@pytest.fixture
def studio_mode(tmp_path, monkeypatch):
    return _client(tmp_path, monkeypatch, "studio")


# ── Oberflaeche ──────────────────────────────────────────────────────────

def test_root_redirects_to_the_board_page(board_mode):
    resp = board_mode.get("/")
    assert resp.status_code == 302 and resp.headers["Location"] == BOARD_PAGE_PATH
    page = board_mode.get(BOARD_PAGE_PATH)
    assert page.status_code == 200 and page.content_type.startswith("text/html")
    assert "Content-Security-Policy" in page.headers
    assert b"/ui/board/static/board.js" in page.data
    assert board_mode.get("/ui/board/static/board.js").status_code == 200


@pytest.mark.parametrize("path", STUDIO_FILES)
def test_studio_is_not_delivered(board_mode, path):
    resp = board_mode.get(path)
    assert resp.status_code == 404
    assert "Board-Modus" in resp.get_data(as_text=True) and BOARD_PAGE_PATH in resp.get_data(as_text=True)
    assert board_mode.get("/", follow_redirects=True).data.count(b"conclave-ui") == 0


def test_api_docs_and_shared_files_stay(board_mode):
    for path in ("/api-docs", "/static/js/swagger-init.js", "/static/vendor/purify.min.js", "/health",
                 "/openapi.json"):
        assert board_mode.get(path).status_code == 200, path


def test_studio_mode_is_unchanged_and_also_offers_the_board_page(studio_mode):
    resp = studio_mode.get("/")
    assert resp.status_code == 200 and b"/ui/board/static/board.js" in resp.data       # Studio wie bisher
    for path in STUDIO_FILES:
        assert studio_mode.get(path).status_code == 200, path
    assert studio_mode.get(BOARD_PAGE_PATH).status_code == 200


# ── API bleibt gleich ────────────────────────────────────────────────────

def test_board_agent_reviewer_and_consultations_keep_working(board_mode):
    assert board_mode.post("/board/v1/projects", json={"slug": "api", "name": "API"},
                           headers=_h(HUMAN)).status_code == 201
    created = board_mode.post("/board/v1/tasks", json={"project": "api", "title": "T"}, headers=_h(AGENT))
    assert created.status_code == 201
    taken = board_mode.post("/board/v1/next", json={"project": "api"}, headers=_h(AGENT)).get_json()
    assert taken["task"]["ref"] == "api#1"
    assert board_mode.post("/board/v1/reviewer/heartbeat", json={"version": "test"},
                           headers=_h(REVIEWER)).status_code in (200, 204)
    assert board_mode.get("/board/v1/reviewer", headers=_h(HUMAN)).get_json()["state"] == "active"
    assert board_mode.get("/consultations?source_ref=api%231", headers=_h(HUMAN)).status_code == 200  # Anfrage: MCP-Test
    assert board_mode.get("/auth/whoami", headers=_h(AGENT)).get_json() == {"role": "agent"}
    assert board_mode.get("/static/js/main.js", headers=_h(HUMAN)).status_code == 404    # auch mit Token


def test_both_modes_register_the_same_routes(tmp_path, monkeypatch):
    def rules(mode):
        client = _client(tmp_path / mode, monkeypatch, mode)
        return sorted((r.rule, tuple(sorted(r.methods))) for r in client.application.url_map.iter_rules())
    assert rules("board") == rules("studio")


# ── Konfiguration und Start ──────────────────────────────────────────────

def test_mode_is_read_from_config_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    path = tmp_path / "config.toml"
    assert ConclaveConfig.from_sources(config_path=path).ui.mode == "studio"           # ohne Datei
    path.write_text('[ui]\nmode = "board"\n', encoding="utf-8")
    assert ConclaveConfig.from_sources(config_path=path).ui.board_only


@pytest.mark.parametrize("value", ['"Board"', '"desk"', '""', "1", '["board"]'])
def test_invalid_mode_is_rejected_with_a_clear_message(tmp_path, value):
    path = tmp_path / "config.toml"
    path.write_text(f"[ui]\nmode = {value}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"\[ui\] mode muss einer von \['studio', 'board'\] sein"):
        ConclaveConfig.from_sources(config_path=path)


def test_start_reports_the_invalid_mode_without_traceback(monkeypatch, capsys):
    import conclave.cli.main as main

    def broken():
        raise ConfigError("[ui] mode muss einer von ['studio', 'board'] sein, nicht 'desk'")
    monkeypatch.setattr(main, "run", broken)
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("FEHLER in ") and "config.toml: [ui] mode muss einer von" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("mode, expected", [("studio", "http://127.0.0.1:8000#token=cvh_geheim"),
                                            ("board", "http://127.0.0.1:8000/ui/board#token=cvh_geheim")])
def test_web_opens_the_page_of_the_mode(monkeypatch, mode, expected):
    import conclave.cli.main as main
    import conclave.runtime.api_token as api_token

    urls = []
    monkeypatch.setattr(main, "open_browser", lambda url: urls.append(url) or True)
    monkeypatch.setattr(api_token, "read_token", lambda: "cvh_geheim")
    monkeypatch.setattr(ConclaveConfig, "from_sources",
                        classmethod(lambda cls, *a, **k: ConclaveConfig(port=8000, ui=UiSettings(mode))))
    main._run_web(SimpleNamespace(url=None))
    assert urls == [expected]


@pytest.mark.parametrize("mode, path", [("studio", ""), ("board", "/ui/board")])
def test_desktop_opens_the_page_of_the_mode(mode, path):
    from conclave.cli.main import _ui_url
    assert _ui_url(ConclaveConfig(ui=UiSettings(mode)), "http://127.0.0.1:8123") == "http://127.0.0.1:8123" + path


def _broken_mode():
    raise ConfigError("[ui] mode muss einer von ['studio', 'board'] sein, nicht 'desk'")


def test_conclave_api_reports_the_invalid_mode_without_traceback(monkeypatch, capsys):
    """U2-Review V1: auch der Einstieg conclave-api meldet den Fehler mit der Datei."""
    import conclave.api.server as server

    monkeypatch.setattr(server.ConclaveConfig, "from_sources", classmethod(lambda cls, *a, **k: _broken_mode()))
    with pytest.raises(SystemExit) as exit_info:
        server.main()
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("FEHLER in ") and "config.toml: [ui] mode muss einer von" in err


def test_wsgi_factory_names_the_config_file(monkeypatch):
    import conclave.api.server as server

    monkeypatch.setattr(server.ConclaveConfig, "from_sources", classmethod(lambda cls, *a, **k: _broken_mode()))
    with pytest.raises(ConfigError, match=r"^FEHLER in .*config\.toml: \[ui\] mode muss einer von"):
        server.create_wsgi_app()


def test_a_real_config_file_with_an_invalid_mode_stops_conclave_api(tmp_path, monkeypatch, capsys):
    """Ende zu Ende: config.toml mit mode = "desk" ueber den echten Ladepfad."""
    import conclave.api.server as server
    import conclave.cli.config as config_module

    path = tmp_path / "config.toml"
    path.write_text('[ui]\nmode = "desk"\n', encoding="utf-8")
    monkeypatch.setattr(config_module, "default_config_path", lambda: path)
    with pytest.raises(SystemExit):
        server.main()
    err = capsys.readouterr().err
    assert err == f"FEHLER in {path}: [ui] mode muss einer von ['studio', 'board'] sein, nicht 'desk'\n"
