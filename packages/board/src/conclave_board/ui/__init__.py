# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter
"""Board-Oberflaeche als Paket-Ressource (U1).

Der Kern liefert die Seite nie von selbst aus: ``create_board_app`` ruft
``register_board_ui`` nicht auf, der Server des Kerns bleibt ohne Oberflaeche. Nur eine Host-App,
die das ausdruecklich will (heute Conclave Personal), bindet sie ein.

Die Seite selbst enthaelt keine Daten und ist deshalb ohne Token erreichbar; alle Daten kommen ueber
``/board/v1`` mit dem Token des Browsers. Sicherheitsheader und CSP setzt die Host-App.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Flask, Response

UI_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = UI_ROOT / "static"
DEFAULT_PREFIX = "/ui/board"


def board_page_html(url_prefix: str = DEFAULT_PREFIX) -> str:
    """board.html mit absoluten Pfaden zu den statischen Dateien (relativ ginge unter /ui/board fehl;
    ``<base>`` verbietet die CSP mit ``base-uri 'none'``)."""
    html = (UI_ROOT / "board.html").read_text(encoding="utf-8")
    static = f"{url_prefix}/static/"
    return html.replace('href="static/', f'href="{static}').replace('src="static/', f'src="{static}')


def register_board_ui(app: Flask, url_prefix: str = DEFAULT_PREFIX) -> str:
    """Haengt die Board-Seite unter ``url_prefix`` an ``app`` (Seite und ``<prefix>/static/…``).

    Gibt den Praefix zurueck; die Host-App laesst ``GET <prefix>`` und ``GET <prefix>/static/…``
    ohne Token zu."""
    url_prefix = "/" + url_prefix.strip("/")
    page = board_page_html(url_prefix)
    blueprint = Blueprint("board_ui", __name__, static_folder=str(STATIC_ROOT),
                          static_url_path="/static", url_prefix=url_prefix)

    @blueprint.get("")
    def board_page():
        """Board-Seite (HTML, ohne Daten; die Daten laedt sie ueber /board/v1)."""
        return Response(page, mimetype="text/html")

    app.register_blueprint(blueprint)
    return url_prefix
