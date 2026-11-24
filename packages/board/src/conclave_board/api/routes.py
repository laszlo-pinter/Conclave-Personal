# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""REST-Routen des Boards als Flask-Blueprint (Plan board.md, B3; T1, T3).

Versionierung (T3, E9):

- ``/board/v1/...`` ist die stabile API. Innerhalb von v1 gibt es nur Ergaenzungen
  (neue Routen, neue optionale Felder in Anfragen, neue Felder in Antworten).
  Brechend und damit nur in einer neuen Version: Felder entfernen oder umbenennen,
  Typ oder Bedeutung aendern, neue Pflichtfelder, strengere Pruefung, andere
  Statuscodes oder Fehlerformate, Rechte zum Nachteil bestehender Clients.
- ``/board/...`` (unversioniert, bis v0.7.0) bleibt als Alias mit denselben
  Antworten und den Headern ``Deprecation``, ``Sunset`` und ``Link`` auf den Nachfolger.
- ``GET /board/versions`` nennt die Versionen; ``/health`` nennt sie ebenfalls.

Board-App (``conclave_board.api.app``) und Personal (``conclave.api.app``) binden
die Routen mit ``register_board_api`` ein. Anmeldung, Zugriffslisten und Grenzen
setzt die App; die Regeln je Ticket prueft der BoardService.
"""

import json as _json
from datetime import timedelta
from typing import Callable

from flask import Blueprint, Flask, g, jsonify, request

from conclave_board.api.security import BOARD_IMPORT_MAX_BYTES
from conclave_board.api.versions import (  # noqa: F401  (Namen auch hier erreichbar)
    ALIAS_DEPRECATION, ALIAS_PREFIX, ALIAS_SUNSET, PREFIXES, V1_PREFIX, VERSIONS_PATH, board_versions,
)
from conclave_board.application.board import (
    BoardError, comment_to_dict, event_to_dict, initiative_to_dict, project_event_to_dict, project_to_dict,
    task_to_dict,
)

def _iso(value):
    return value.isoformat() if value is not None else None


def register_board_api(app: Flask, board, *, import_max_bytes: Callable[[], int] | None = None) -> None:
    """Board-Routen unter ``/board/v1`` und als abgekuendigten Alias unter ``/board``, dazu die Versionen."""
    blueprint = create_board_blueprint(board, import_max_bytes=import_max_bytes)
    app.register_blueprint(blueprint, url_prefix=V1_PREFIX, name="board_v1")
    app.register_blueprint(blueprint, url_prefix=ALIAS_PREFIX, name="board")

    @app.get(VERSIONS_PATH)
    def board_api_versions():
        """Versionen der Board-API (ohne Token)."""
        return jsonify(board_versions()), 200


def create_board_blueprint(board, *, import_max_bytes: Callable[[], int] | None = None) -> Blueprint:
    """Blueprint mit allen Board-Routen; ``board`` ist der BoardService oder ``None`` (Board abgeschaltet).

    ``import_max_bytes`` liefert die Grenze fuer ``POST /board/import`` je Anfrage (Standard 50 MB).
    """
    bp = Blueprint("board", __name__)
    import_limit = import_max_bytes or (lambda: BOARD_IMPORT_MAX_BYTES)

    @bp.app_errorhandler(BoardError)
    def _handle_board_error(e):
        return jsonify({"error": str(e), "type": e.type}), e.status

    @bp.before_request
    def _check_project_scope():
        """Zugaenge mit eingeschraenkten Projekten (T4) sehen fremde Projekte nicht: 404."""
        principal = g.get("principal")
        if principal is None or principal.projects is None or board is None:
            return
        board.require_visible(principal, (request.view_args or {}).get("slug"))
        board.require_visible(principal, request.args.get("project") or None)
        if request.method == "POST" and request.path.endswith("/tasks"):
            body = request.get_json(silent=True)
            if isinstance(body, dict) and isinstance(body.get("project"), str):
                board.require_visible(principal, body["project"])

    def _visible(tasks):
        principal = g.get("principal")
        return [t for t in tasks if principal is None or principal.sees(t.project_slug)]

    @bp.after_request
    def _mark_alias(response):
        """Der Alias /board antwortet wie v1, mit Hinweis auf die Abkuendigung."""
        if request.blueprint == "board":
            response.headers["Deprecation"] = ALIAS_DEPRECATION
            response.headers["Sunset"] = ALIAS_SUNSET
            successor = V1_PREFIX + request.path[len(ALIAS_PREFIX):]
            response.headers["Link"] = f'<{successor}>; rel="successor-version"'
        return response

    # ── Board (Plan board.md, B3) ───────────────────────────────────────
    def _board():
        if board is None:
            raise BoardError("Das Board ist in dieser Instanz nicht verfuegbar.", 503, "BoardDisabled")
        return board

    def _names():
        """Anzeigenamen der Konten fuer diese Anfrage (``BoardPolicy.actor_name``, T8), je Konto einmal gefragt."""
        cache = g.get("_board_actor_names")
        if cache is None:
            cache = g._board_actor_names = {}
        policy = _board().policy

        def name(actor_id):
            if actor_id not in cache:
                cache[actor_id] = policy.actor_name(actor_id) if actor_id else None
            return cache[actor_id]
        return name

    def _json_object() -> dict:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise BoardError("JSON-Objekt erwartet.", 400, "ValidationError")
        return body

    def _check_task_fields(body: dict, allowed: set) -> None:
        """Gleiche Typpruefung fuer Anlegen (POST) und Aendern (PATCH)."""
        unknown = set(body) - allowed
        if unknown:
            raise BoardError(f"Unbekannte Felder: {sorted(unknown)}", 400, "ValidationError")
        for name in ("project", "title", "description", "status", "kind", "control", "scope", "initiative"):
            if body.get(name) is not None and not isinstance(body[name], str):
                raise BoardError(f"{name} muss Text sein.", 400, "ValidationError")
        tags = body.get("tags")
        if tags is not None and (not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)):
            raise BoardError("tags muss eine Liste von Texten sein.", 400, "ValidationError")
        if body.get("human") is not None and not isinstance(body["human"], bool):
            raise BoardError("human muss true oder false sein.", 400, "ValidationError")
        index = body.get("index")
        if index is not None and (isinstance(index, bool) or not isinstance(index, int)):
            raise BoardError("index muss eine ganze Zahl sein.", 400, "ValidationError")
        rank = body.get("rank")
        if rank is not None and (isinstance(rank, bool) or not isinstance(rank, (int, float))):
            raise BoardError("rank muss eine Zahl sein.", 400, "ValidationError")
        version = body.get("version")
        if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
            raise BoardError("version muss eine ganze Zahl sein.", 400, "ValidationError")

    def _flag(name: str, default: bool = False) -> bool:
        return request.args.get(name, "true" if default else "false").lower() in ("1", "true", "yes")

    @bp.get("")
    def board_overview():
        """Spalten, Projekte und Aenderungszaehler des Boards."""
        b = _board()
        projects = [p for p in b.list_projects() if g.principal.sees(p.slug)]
        return jsonify({"statuses": list(b.flow.statuses), "projects": [project_to_dict(p) for p in projects],
                        "changes": b.change_token_for(g.principal), "control": b.control_state(principal=g.principal),
                        "reviewer": b.reviewer_status()}), 200

    @bp.get("/reviewer")
    def board_reviewer_status():
        """Laeuft der automatische Reviewer? ``active`` oder ``off`` mit ``since`` (W3)."""
        return jsonify(_board().reviewer_status()), 200

    @bp.post("/reviewer/heartbeat")
    def board_reviewer_heartbeat():
        """Lebenszeichen des Reviewers, etwa alle 60 s (nur Reviewer-Zugang). Body: version, task."""
        if not g.principal.is_reviewer:                    # vor jeder Pruefung des Body
            raise BoardError("Den Herzschlag sendet nur der Reviewer-Zugang.", 403, "Forbidden")
        body = _json_object()
        unknown = set(body) - {"version", "task"}
        if unknown:
            raise BoardError(f"Unbekannte Felder: {', '.join(sorted(unknown))}.", 400, "ValidationError")
        return jsonify(_board().reviewer_heartbeat(g.principal, body.get("version") or "", body.get("task"))), 200

    def _control(slug: str | None = None) -> dict:
        """Offene Pausen und unquittierte Hinweise des Menschen (P6), in jeder Board-Antwort."""
        return _board().control_state(slug, g.get("principal"))

    @bp.get("/changes")
    def board_changes():
        """Aenderungszaehler; die UI laedt neu, wenn er steigt."""
        return jsonify({"changes": _board().change_token_for(g.principal)}), 200

    @bp.post("/projects")
    def board_create_project():
        """Projekt anlegen (Freigabe-Recht)."""
        body = _json_object()
        project = _board().create_project(g.principal, body.get("slug"), body.get("name"))
        return jsonify(project_to_dict(project)), 201

    @bp.put("/projects/<slug>")
    def board_rename_project(slug: str):
        """Projekt umbenennen (Freigabe-Recht)."""
        project = _board().rename_project(g.principal, slug, _json_object().get("name"))
        return jsonify(project_to_dict(project)), 200

    @bp.delete("/projects/<slug>")
    def board_delete_project(slug: str):
        """Projekt samt Tickets loeschen (Freigabe-Recht); only_empty=true nur ohne Tickets und Vorhaben, sonst 409."""
        _board().delete_project(g.principal, slug, only_empty=_flag("only_empty"))
        return "", 204

    @bp.get("/tasks")
    def board_list_tasks():
        """Tickets in Board-Reihenfolge; Filter project, status (mehrfach), include_done."""
        statuses = request.args.getlist("status") or None
        slug = request.args.get("project") or None
        tasks = _visible(_board().list_tasks(slug, statuses, include_done=_flag("include_done")))
        return jsonify({"tasks": [task_to_dict(t, _names()) for t in tasks], "control": _control(slug)}), 200

    @bp.post("/tasks")
    def board_create_task():
        """Ticket anlegen; neue Tickets landen in der ersten Spalte.

        Steuertickets (nur Mensch): kind=control, control=pause|hint, scope=project|all (P6)."""
        body = _json_object()
        _check_task_fields(body, {"project", "title", "description", "tags", "status", "human", "kind", "control",
                                  "scope", "initiative"})
        task = _board().create_task(g.principal, body.get("project"), body.get("title"),
                                    description=body.get("description") or "", tags=body.get("tags") or [],
                                    human=body.get("human", False), status=body.get("status"),
                                    kind=body.get("kind") or "task", control=body.get("control"),
                                    scope=body.get("scope") or "project", initiative=body.get("initiative") or None)
        return jsonify({**task_to_dict(task, _names()), "control": _control(task.project_slug)}), 201

    @bp.get("/search")
    def board_search():
        """Suche in Titel, Tags, Beschreibung und Kommentaren."""
        slug = request.args.get("project") or None
        tasks = _visible(_board().search(request.args.get("q", ""), slug, include_done=_flag("include_done", True)))
        return jsonify({"tasks": [task_to_dict(t, _names()) for t in tasks], "control": _control(slug)}), 200

    @bp.post("/next")
    def board_next_task():
        """Oberstes freies Ticket der ersten Spalte uebernehmen (atomar); mit ``task`` genau dieses."""
        body = _json_object() if request.get_data(cache=True) else {}
        ref = body.get("task")
        if ref is not None and (not isinstance(ref, str) or not ref.strip()):
            raise BoardError("task muss eine Ticket-Referenz wie 'api#12' sein.", 400, "ValidationError")
        b = _board()
        slug = body.get("project") or None
        try:
            task = b.next_task(g.principal, slug, task=ref)
        except BoardError as e:
            if e.type != "Paused":
                raise
            # Pause des Menschen (P6): kein Ticket, sondern die Pause
            return jsonify({"task": None, "paused": True, "pause": e.pause, "control": _control(slug)}), 200
        if task is None:
            return jsonify({"task": None, "control": _control(slug)}), 200
        # Nacharbeit (P3): der letzte Review-Kommentar kommt gleich mit
        return jsonify({"task": task_to_dict(task, _names()), "last_review": _last_review(b, task.ref),
                        "control": _control(task.project_slug)}), 200

    def _last_review(b, ref: str):
        comment = b.last_review(ref)
        return comment_to_dict(comment, _names()) if comment else None

    def _ref(slug: str, number: int) -> str:
        return f"{slug}#{number}"

    @bp.get("/projects/<slug>/tasks/<int:number>")
    def board_get_task(slug: str, number: int):
        """Ein Ticket mit Kommentaren und ``can_approve``.

        ``can_approve``: Hat dieser Zugang im Projekt das Freigabe-Recht? Die Oberflaeche zeigt danach,
        was nur damit geht (z. B. "Review neu starten", conclave#145)."""
        b = _board()
        task = b.get_task(_ref(slug, number))
        return jsonify({**task_to_dict(task, _names()), "comments": [comment_to_dict(c, _names()) for c in b.comments(task.ref)],
                        "last_review": _last_review(b, task.ref), "status_since": _iso(b.status_since(task)),
                        "can_approve": b.can_approve(g.principal, task.project_slug),
                        "control": _control(slug)}), 200

    @bp.post("/projects/<slug>/tasks/<int:number>/release")
    def board_release_task(slug: str, number: int):
        """Haengendes Ticket freigeben: zurueck in die erste Spalte, Zustaendigkeit leer (Mensch, T5)."""
        task = _board().release_task(g.principal, _ref(slug, number))
        return jsonify({**task_to_dict(task, _names()), "control": _control(slug)}), 200

    @bp.get("/stuck")
    def board_stuck():
        """Uebernommene Tickets, die laenger als ``minutes`` (Standard 60) in Arbeit stehen (Mensch, T5)."""
        raw = request.args.get("minutes", "60")
        if not raw.isdigit() or not 1 <= int(raw) <= 525600:
            raise BoardError("minutes muss eine ganze Zahl von 1 bis 525600 sein.", 400, "ValidationError")
        slug = request.args.get("project") or None
        found = _board().stuck(g.principal, slug, timedelta(minutes=int(raw)))
        return jsonify({"tasks": [{**task_to_dict(t, _names()), "status_since": _iso(since)} for t, since in found],
                        "control": _control(slug)}), 200

    @bp.get("/projects/<slug>/initiatives/<initiative>/tasks/<int:number>")
    def board_get_task_in_initiative(slug: str, initiative: str, number: int):
        """Ein Ticket ueber seine Vorhaben-Nummer (``projekt/vorhaben-n``, P2); wie das Ticket selbst."""
        task = _board().get_task(f"{slug}/{initiative}-{number}")
        return board_get_task(slug, task.number)

    @bp.get("/projects/<slug>/initiatives")
    def board_list_initiatives(slug: str):
        """Vorhaben des Projekts nach Rang (P2)."""
        return jsonify({"initiatives": [initiative_to_dict(i) for i in _board().list_initiatives(slug)]}), 200

    @bp.post("/projects/<slug>/initiatives")
    def board_create_initiative(slug: str):
        """Vorhaben anlegen: slug, title, optional rank (Freigabe-Recht)."""
        body = _json_object()
        _check_initiative_fields(body, {"slug", "title", "rank"})
        initiative = _board().create_initiative(g.principal, slug, body.get("slug"), body.get("title"),
                                                rank=body.get("rank"))
        return jsonify(initiative_to_dict(initiative)), 201

    @bp.put("/projects/<slug>/initiatives/<initiative>")
    def board_update_initiative(slug: str, initiative: str):
        """Vorhaben umbenennen oder ranken: title, rank (Freigabe-Recht)."""
        body = _json_object()
        _check_initiative_fields(body, {"title", "rank"})
        changed = _board().update_initiative(g.principal, slug, initiative, title=body.get("title"),
                                             rank=body.get("rank"))
        return jsonify(initiative_to_dict(changed)), 200

    def _check_initiative_fields(body: dict, allowed: set) -> None:
        unknown = set(body) - allowed
        if unknown:
            raise BoardError(f"Unbekannte Felder: {sorted(unknown)}", 400, "ValidationError")
        for name in ("slug", "title"):
            if body.get(name) is not None and not isinstance(body[name], str):
                raise BoardError(f"{name} muss Text sein.", 400, "ValidationError")
        rank = body.get("rank")
        if rank is not None and (isinstance(rank, bool) or not isinstance(rank, (int, float))):
            raise BoardError("rank muss eine Zahl sein.", 400, "ValidationError")

    @bp.patch("/projects/<slug>/tasks/<int:number>")
    def board_update_task(slug: str, number: int):
        """Ticket aendern: title, description, tags, status, human, index, rank, version, initiative.

        ``index`` ist der Platz in der Spalte; mit ``version`` wird nur geschrieben, wenn das
        Ticket noch diesen Stand hat (sonst 409, R9). ``initiative`` ordnet das Ticket einem
        Vorhaben zu (``null`` = keinem); das darf nur der Mensch (P2)."""
        body = _json_object()
        _check_task_fields(body, {"title", "description", "tags", "status", "human", "index", "rank", "version",
                                  "initiative", "assignee"})
        if body.get("assignee") is not None and not isinstance(body["assignee"], str):
            raise BoardError("assignee muss Text oder null sein.", 400, "ValidationError")
        b = _board()
        if "initiative" in body and not b.can_approve(g.principal, slug):
            raise BoardError("Vorhaben ordnet nur der Mensch zu.", 403, "HumanOnly")
        ref = _ref(slug, number)
        fields = {k: v for k, v in body.items() if k != "initiative"}
        task = None
        if fields or "initiative" not in body:
            extra = {"assignee": body["assignee"]} if "assignee" in body else {}
            task = b.update_task(g.principal, ref, title=body.get("title"), description=body.get("description"),
                                 tags=body.get("tags"), status=body.get("status"), human=body.get("human"),
                                 index=body.get("index"), rank=body.get("rank"), version=body.get("version"), **extra)
        if "initiative" in body:
            if task is None and body.get("version") is not None:
                current = b.get_task(ref)
                if current.version != body["version"]:
                    raise BoardError(f"Ticket '{ref}' hat inzwischen Version {current.version} "
                                     f"(erwartet {body['version']}); bitte neu laden.", 409, "Conflict")
            task = b.assign_initiative(g.principal, ref, body.get("initiative") or None)
        return jsonify({**task_to_dict(task, _names()), "control": _control(slug)}), 200

    @bp.delete("/projects/<slug>/tasks/<int:number>")
    def board_delete_task(slug: str, number: int):
        """Ticket loeschen (Freigabe-Recht)."""
        _board().delete_task(g.principal, _ref(slug, number))
        return "", 204

    @bp.get("/projects/<slug>/tasks/<int:number>/comments")
    def board_list_comments(slug: str, number: int):
        """Kommentare eines Tickets mit Herkunft."""
        return jsonify({"comments": [comment_to_dict(c, _names()) for c in _board().comments(_ref(slug, number))]}), 200

    @bp.post("/projects/<slug>/tasks/<int:number>/comments")
    def board_add_comment(slug: str, number: int):
        """Kommentar schreiben; die Herkunft kommt aus dem Token."""
        body = _json_object()
        comment = _board().add_comment(g.principal, _ref(slug, number), body.get("body"),
                                       author_name=body.get("author_name") or "")
        return jsonify({**comment_to_dict(comment, _names()), "control": _control(slug)}), 201

    @bp.get("/projects/<slug>/tasks/<int:number>/history")
    def board_history(slug: str, number: int):
        """Verlauf eines Tickets: Anlegen und jede Aenderung mit Herkunft."""
        return jsonify({"history": [event_to_dict(e, _names()) for e in _board().history(_ref(slug, number))]}), 200

    @bp.post("/projects/<slug>/tasks/<int:number>/review")
    def board_review_task(slug: str, number: int):
        """Review-Status setzen (nur Reviewer-Zugang).

        Body: state, comment, optional blocking, suggestions, checked. Ergebnis und Kommentar
        werden zusammen gespeichert (P3)."""
        body = _json_object()
        unknown = set(body) - {"state", "comment", "blocking", "suggestions", "checked"}
        if unknown:
            raise BoardError(f"Unbekannte Felder: {', '.join(sorted(unknown))}.", 400, "ValidationError")
        task = _board().review(g.principal, _ref(slug, number), body.get("state"), body.get("comment"),
                               blocking=body.get("blocking"), suggestions=body.get("suggestions"),
                               checked=body.get("checked"))
        return jsonify(task_to_dict(task, _names())), 200

    @bp.post("/projects/<slug>/tasks/<int:number>/review/request")
    def board_request_review(slug: str, number: int):
        """Review neu anfordern: Status ``requested``, das Ticket bleibt in review (Freigabe-Recht, conclave#145)."""
        body = _json_object()
        if body:
            raise BoardError(f"Unbekannte Felder: {', '.join(sorted(body))}.", 400, "ValidationError")
        task = _board().request_review(g.principal, _ref(slug, number))
        return jsonify({**task_to_dict(task, _names()), "control": _control(slug)}), 200

    @bp.get("/projects/<slug>/history")
    def board_project_history(slug: str):
        """Verlauf eines Projekts: Anlegen, Umbenennen, geloeschte Tickets (nur Mensch)."""
        return jsonify({"history": [project_event_to_dict(e, _names()) for e in _board().project_history(slug)]}), 200

    @bp.put("/comments/<comment_id>")
    def board_edit_comment(comment_id: str):
        """Eigenen Kommentar aendern (nur Mensch)."""
        comment = _board().edit_comment(g.principal, comment_id, _json_object().get("body"))
        return jsonify(comment_to_dict(comment, _names())), 200

    @bp.delete("/comments/<comment_id>")
    def board_delete_comment(comment_id: str):
        """Eigenen Kommentar loeschen (nur Mensch)."""
        _board().delete_comment(g.principal, comment_id)
        return "", 204

    @bp.post("/import")
    def board_import():
        """JSON-Export eines Boards uebernehmen (Freigabe-Recht, idempotent)."""
        limit = import_limit()
        too_large = BoardError(f"Export zu gross (hoechstens {limit // (1024 * 1024)} MB).",
                               413, "ImportTooLarge")
        if (request.content_length or 0) > limit:
            raise too_large
        # Mit Obergrenze lesen: greift auch ohne Content-Length (z. B. chunked)
        request.max_content_length = limit + 1    # eigene Grenze statt der allgemeinen (R6)
        raw = request.stream.read(limit + 1)
        if len(raw) > limit:
            raise too_large
        try:
            data = _json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise BoardError("Export ist kein gueltiges JSON.", 400, "ImportFormatError") from None
        return jsonify(_board().import_export(g.principal, data)), 200

    return bp
