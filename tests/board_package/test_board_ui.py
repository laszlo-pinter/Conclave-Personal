"""U1 (conclave#110): Board-Oberflaeche im Kern.

- Der Kern liefert ohne ``register_board_ui`` keine Seite aus (Server des Kerns und Team-Server
  bleiben ohne Oberflaeche).
- Eine Host-App bindet Seite und statische Dateien ein.
- Die Seite haelt die Regeln von Personal ein: kein Inline-Skript oder -Style, HTML-Senken mit
  Begruendung, Farben nur aus theme.css, Markdown ueber DOMPurify mit derselben Konfiguration.
- ``board.js`` spricht nur ``/board/v1`` an, die Seite zusaetzlich ``/auth/whoami``.
- Studio und Board-Seite nutzen dieselbe Ansicht (gleiche IDs und Aktionen, gleiche Texte).
"""

import re
from pathlib import Path

import pytest
from conclave_board.api.app import create_board_app
from conclave_board.infrastructure.auth import StaticKeyAuthService
from conclave_board.server import open_board
from conclave_board.ui import STATIC_ROOT, UI_ROOT, board_page_html, register_board_ui
from flask import Flask

from tests.ui.test_html_sinks import MARKER, SINK
from tests.ui.test_theme_browser import HEX_OR_RGB

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src" / "conclave" / "assets"
STUDIO = ASSETS / "conclave-ui.html"
PAGE = UI_ROOT / "board.html"
OWN_JS = sorted(p for p in STATIC_ROOT.glob("*.js"))
OWN_CSS = sorted(p for p in STATIC_ROOT.glob("*.css") if p.name != "theme.css")
HUMAN, AGENT = "cvh_mensch", "cva_agent"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def core_app(tmp_path):
    board, _conn = open_board(db_path=tmp_path / "board.db", config_dir=tmp_path / "config")
    return create_board_app(board, StaticKeyAuthService(HUMAN, AGENT, "cvr_reviewer"))


# ── Auslieferung ─────────────────────────────────────────────────────────

def test_core_app_serves_no_page_without_registration(core_app):
    assert [r.rule for r in core_app.url_map.iter_rules() if r.rule.startswith("/ui")] == []
    client = core_app.test_client()
    for path in ("/", "/ui/board", "/ui/board/static/board.js", "/static/board.js"):
        resp = client.get(path, headers={"Authorization": f"Bearer {HUMAN}"})
        assert resp.status_code == 404, path
        assert not resp.content_type.startswith("text/html"), path
    assert "default-src 'none'" in client.get("/ui/board").headers["Content-Security-Policy"]


def test_core_package_never_calls_register_board_ui():
    """Nur eine Host-App bindet die Seite ein, nie der Kern selbst (auch nicht der Server)."""
    core = ROOT / "packages" / "board" / "src" / "conclave_board"
    callers = [p.relative_to(core).as_posix() for p in core.rglob("*.py")
               if p.parent != UI_ROOT and "register_board_ui" in _read(p)]
    assert callers == []


@pytest.mark.parametrize("prefix", ["/ui/board", "/andere/seite"])
def test_registered_page_and_static_files(prefix):
    app = Flask("host")
    assert register_board_ui(app, prefix) == prefix
    client = app.test_client()
    resp = client.get(prefix)
    assert resp.status_code == 200 and resp.content_type.startswith("text/html")
    html = resp.get_data(as_text=True)
    assert f'src="{prefix}/static/board.js"' in html and 'src="static/' not in html
    for name in ("board.js", "board-page.js", "board-i18n.js", "board-markdown.js", "board.css",
                 "board-page.css", "theme.css", "vendor/purify.min.js", "vendor/marked.min.js",
                 "vendor/fonts/fonts.css", "vendor/fonts/syne-latin-800-normal.woff2"):
        assert client.get(f"{prefix}/static/{name}").status_code == 200, name
    assert client.get(f"{prefix}/static/../__init__.py").status_code == 404


def test_page_paths_are_absolute():
    html = board_page_html("/ui/board")
    assert re.findall(r'(?:src|href)="(?!/ui/board/static/)[^"]*"', html) == []


# ── Regeln der Seite ─────────────────────────────────────────────────────

def test_page_has_no_inline_script_style_or_handlers():
    html = _read(PAGE)
    assert re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html) == []
    assert "<style" not in html and not re.search(r"\sstyle=", html)
    assert not re.search(r"\son\w+=", html)
    for path in OWN_JS:
        for handler in ("onclick=", "onchange=", "oninput=", "onkeydown="):
            assert handler not in _read(path), (path.name, handler)
        assert "eval(" not in _read(path) and "new Function" not in _read(path), path.name


def test_html_sinks_have_a_reason():
    missing = []
    for path in OWN_JS:
        lines = _read(path).splitlines()
        for i, line in enumerate(lines):
            if SINK.search(line) and MARKER not in line and not (i and lines[i - 1].strip().startswith(MARKER)):
                missing.append(f"{path.name}:{i + 1}")
    assert missing == []


@pytest.mark.parametrize("path", [PAGE, *OWN_JS, *OWN_CSS], ids=lambda p: p.name)
def test_no_fixed_colors_outside_the_theme(path):
    assert HEX_OR_RGB.findall(re.sub(r"&#\d+;", "", _read(path))) == []


def test_theme_is_the_one_from_personal():
    """theme.css ist eine Kopie; Personal und Board-Seite zeigen dieselben Farben."""
    assert _read(STATIC_ROOT / "theme.css") == _read(ASSETS / "static" / "css" / "theme.css")


def test_markdown_filter_matches_personal():
    """board-markdown.js ist ab "Markdown" eine Kopie aus utils.js, esc() ebenso."""
    utils = _read(ASSETS / "static" / "js" / "utils.js")
    own = _read(STATIC_ROOT / "board-markdown.js")
    marker = "// ── Markdown"
    assert own[own.index(marker):] == utils[utils.index(marker):]
    esc = next(line for line in utils.splitlines() if line.startswith("function esc("))
    assert esc in own.splitlines()


def test_vendored_libraries_match_personal():
    """Gleiche Version wie in Personal; scripts/check_vendor.py prueft beide gegen npm."""
    vendor = ASSETS / "static" / "vendor"
    own = sorted(p.relative_to(STATIC_ROOT / "vendor").as_posix()
                 for p in (STATIC_ROOT / "vendor").rglob("*") if p.is_file())
    assert {"marked.min.js", "purify.min.js", "fonts/fonts.css", "licenses/dompurify-LICENSE.txt"} <= set(own)
    for name in own:
        assert (STATIC_ROOT / "vendor" / name).read_bytes() == (vendor / name).read_bytes(), name


def test_every_own_file_has_the_apache_header():
    for path in [*OWN_JS, *OWN_CSS]:
        assert "SPDX-License-Identifier: Apache-2.0" in _read(path).splitlines()[0], path.name
    assert "SPDX-License-Identifier: Apache-2.0" in _read(PAGE).splitlines()[1]


# ── Nur die Board-API ────────────────────────────────────────────────────

def test_board_js_talks_only_to_the_board_api():
    js = _read(STATIC_ROOT / "board.js")
    assert "const BOARD_API = '/board/v1';" in js
    for other in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "http://", "https://"):
        assert other not in js, other
    calls = re.findall(r"\breq\(\s*'[A-Z]+',\s*([^,)]+)", js)
    assert calls and [c for c in calls if not c.startswith(("BOARD_API", "_taskPath("))] == []
    assert "return `${BOARD_API}/projects/" in js
    # Pfade als Text nur unter /board/v1: keine anderen absoluten Pfade in Zeichenketten
    paths = re.findall(r"['`](/[\w/-]*)", js)
    assert [p for p in paths if not p.startswith("/board/v1")
            and p not in ("/search", "/tasks", "/changes", "/reviewer", "/comments", "/history", "/projects", "/projects/", "/initiatives",
                          "/review/request")] == []


def test_board_page_talks_only_to_board_api_and_whoami():
    js = _read(STATIC_ROOT / "board-page.js")
    fetches = re.findall(r"fetch\(([^,)]+)", js)
    assert sorted(fetches) == ["window.location.origin + '/auth/whoami'", "window.location.origin + path"]
    assert "http://" not in js and "https://" not in js
    assert "localStorage.setItem(BOARD_TOKEN_KEY" not in js        # Token nur im sessionStorage
    assert "_pageSet(sessionStorage, BOARD_TOKEN_KEY" in js


# ── Dieselbe Ansicht im Studio ───────────────────────────────────────────

def _board_markup(html: str):
    ids = set(re.findall(r'id="((?:board|overlayBoard)\w*)"', html))
    actions = set(re.findall(r'data-action="(board-[\w-]+)"', html))
    keys = set(re.findall(r'data-i18n(?:-\w+)?="(board\.[\w.]+)"', html))
    return ids, actions, keys


def test_studio_and_page_share_the_board_markup():
    studio, page = _board_markup(_read(STUDIO)), _board_markup(_read(PAGE))
    for shared, own in zip(studio, page):
        assert shared <= own, shared - own
    js = _read(STATIC_ROOT / "board.js")
    used_ids = set(re.findall(r"getElementById\('((?:board|overlayBoard)\w*)'\)", js))
    assert used_ids <= studio[0] and used_ids <= page[0]
    actions = set(re.findall(r"^  '(board-[\w-]+)':", js, re.M))
    assert studio[1] <= actions and page[1] - {"board-login", "board-login-submit"} <= actions


def test_studio_loads_the_board_view_from_the_core():
    html = _read(STUDIO)
    assert '<script src="/ui/board/static/board.js"></script>' in html
    assert '<link rel="stylesheet" href="/ui/board/static/board.css">' in html
    assert html.index("/ui/board/static/board-i18n.js") < html.index("static/js/i18n.js")
    assert not (ASSETS / "static" / "js" / "features" / "board.js").exists()
    assert "'board." not in _read(ASSETS / "static" / "js" / "i18n.js")
    assert ".board-" not in _read(ASSETS / "static" / "css" / "components.css")


def _i18n():
    text = _read(STATIC_ROOT / "board-i18n.js")
    blocks = dict(re.findall(r"^  (de|en): \{\n(.*?)^  \},", text, re.M | re.S))
    return {lang: set(re.findall(r"^    '([\w.]+)':", body, re.M)) for lang, body in blocks.items()}


def test_texts_exist_in_both_languages_and_cover_the_view():
    keys = _i18n()
    assert keys["de"] == keys["en"] and len(keys["de"]) > 90
    used = set()
    for path in OWN_JS:
        used |= set(re.findall(r"\bt\(\s*'([\w.]+)'", _read(path)))
        used |= set(re.findall(r"'(board\.[\w.]+)'", _read(path)))
    used |= _board_markup(_read(PAGE))[2] | _board_markup(_read(STUDIO))[2]
    assert {k for k in used if not k.endswith('.')} - keys["de"] == set()   # ohne Praefixe wie 'board.field.'
