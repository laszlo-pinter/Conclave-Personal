# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Schemas der Board-API v1 (T3): Anfragen, Antworten, Statuscodes, Query-Parameter.

Quelle fuer den Vertrag ``packages/board/openapi/board-v1.json`` (``scripts/gen-openapi.py``)
und fuer den Test, der die echten Antworten dagegen prueft (tests/board_package/test_api_schemas.py).
Erst damit erkennt ``oasdiff breaking`` auch Brueche an Feldern: entfernte oder umbenannte
Felder, geaenderte Typen, neue Pflichtfelder.

Schluessel: (Methode, Pfad relativ zum Praefix), gleich fuer ``/board/v1`` und den Alias.
Antwortfelder, die immer vorkommen, sind ``required``; Clients ignorieren unbekannte Felder,
deshalb sind Antworten offen (keine ``additionalProperties: false``). Anfragen nennen ihre
Felder; ``additionalProperties: false`` nur dort, wo die API Unbekanntes wirklich ablehnt
(Tickets, Vorhaben, Review). Projekte und Kommentare ignorieren weitere Felder; sie abzulehnen
waere eine strengere Pruefung und damit ein Bruch.
"""

from __future__ import annotations

from copy import deepcopy

from conclave_board.domain.board import REVIEW_RESULTS


def _nullable(schema: dict) -> dict:
    return {**schema, "nullable": True}


STRING = {"type": "string"}
INTEGER = {"type": "integer"}
NUMBER = {"type": "number"}
BOOLEAN = {"type": "boolean"}
TIME = {"type": "string", "format": "date-time", "nullable": True}


# Laeuft der Reviewer? (W3): active mit last_seen, version, task; off mit since (letzter Herzschlag oder null)
REVIEWER = {"type": "object", "required": ["state"], "properties": {
    "state": {"type": "string", "enum": ["active", "off"]},
    "since": TIME, "last_seen": TIME, "version": STRING, "task": _nullable(STRING)}}


def _object(properties: dict, required=None, *, closed: bool = False) -> dict:
    schema = {"type": "object", "properties": properties,
              "required": sorted(properties if required is None else required)}
    if closed:
        schema["additionalProperties"] = False
    if not schema["required"]:
        del schema["required"]
    return schema


PROJECT = _object({"slug": STRING, "name": STRING, "created_at": TIME})

INITIATIVE = _object({"project": STRING, "slug": STRING, "title": STRING, "rank": NUMBER, "created_at": TIME})

DIRECTIVE = _nullable(_object({"type": STRING, "scope": STRING, "ack_by": _nullable(STRING), "ack_at": TIME}))

REVIEW = _object({"state": STRING, "at": TIME, "red_count": INTEGER, "blocking": _nullable(INTEGER),
                  "suggestions": _nullable(INTEGER), "checked": STRING})

TASK_FIELDS = {
    "ref": STRING, "project": STRING, "number": INTEGER, "title": STRING,
    "initiative": _nullable(STRING), "initiative_ref": _nullable(STRING),
    "description": STRING, "tags": {"type": "array", "items": STRING}, "status": STRING,
    "position": NUMBER, "rank": NUMBER, "human": BOOLEAN, "assignee": _nullable(STRING),
    "version": INTEGER, "origin": _nullable(STRING), "created_by": STRING, "kind": STRING,
    "directive": DIRECTIVE, "review": REVIEW, "created_at": TIME, "updated_at": TIME,
    "actor_name": _nullable(STRING),
}
TASK = _object(TASK_FIELDS)

COMMENT = _object({"id": STRING, "body": STRING, "origin": _nullable(STRING), "actor_id": _nullable(STRING),
                   "actor_name": _nullable(STRING), "author_name": STRING, "created_at": TIME, "updated_at": TIME})

EVENT = _object({"field": STRING, "old": {"nullable": True}, "new": {"nullable": True},
                 "origin": _nullable(STRING), "actor_id": _nullable(STRING), "actor_name": _nullable(STRING),
                 "created_at": TIME})

CONTROL_ENTRY = _object({"task": STRING, "type": STRING, "scope": _nullable(STRING), "reason": STRING,
                         "text": STRING, "by": STRING, "at": TIME})
CONTROL = _object({"pauses": {"type": "array", "items": CONTROL_ENTRY},
                   "hints": {"type": "array", "items": CONTROL_ENTRY}})

TASK_LIST = _object({"tasks": {"type": "array", "items": TASK}, "control": CONTROL})
TASK_WITH_CONTROL = _object({**TASK_FIELDS, "control": CONTROL})
TASK_DETAIL = _object({**TASK_FIELDS, "comments": {"type": "array", "items": COMMENT},
                       "last_review": _nullable(COMMENT), "status_since": TIME, "control": CONTROL})
STUCK_TASK = _object({**TASK_FIELDS, "status_since": TIME})

VERSIONS = _object({
    "current": STRING,
    "versions": {"type": "array", "items": _object({"version": STRING, "path": STRING, "status": STRING})},
    "deprecated": {"type": "array", "items": _object({"path": STRING, "successor": STRING, "sunset": STRING})},
})

TAGS = {"type": "array", "items": STRING}
BOOL_QUERY = {"type": "string", "enum": ["true", "false", "1", "0", "yes", "no"]}


def _q(name: str, schema: dict, description: str = "") -> dict:
    param = {"name": name, "in": "query", "required": False, "schema": schema}
    if description:
        param["description"] = description
    return param


# (Methode, relativer Pfad) -> {"status", "request", "response", "query"}
BOARD_SCHEMAS: dict[tuple[str, str], dict] = {
    ("GET", ""): {"response": _object({"statuses": {"type": "array", "items": STRING},
                                       "projects": {"type": "array", "items": PROJECT},
                                       "changes": INTEGER, "control": CONTROL, "reviewer": REVIEWER})},
    ("GET", "/reviewer"): {"response": REVIEWER},
    ("POST", "/reviewer/heartbeat"): {
        "request": _object({"version": STRING, "task": _nullable(STRING)}, required=[], closed=True),
        "response": REVIEWER},
    ("GET", "/changes"): {"response": _object({"changes": INTEGER})},
    ("POST", "/projects"): {"status": 201, "request": _object({"slug": STRING, "name": STRING}),
                            "response": PROJECT},
    ("PUT", "/projects/<slug>"): {"request": _object({"name": STRING}), "response": PROJECT},
    ("DELETE", "/projects/<slug>"): {"status": 204, "query": [
        _q("only_empty", BOOL_QUERY, "nur loeschen, wenn das Projekt keine Tickets hat; sonst 409 ProjectNotEmpty")]},
    ("GET", "/tasks"): {"response": TASK_LIST,
                        "query": [_q("project", STRING), _q("status", STRING, "mehrfach moeglich"),
                                  _q("include_done", BOOL_QUERY)]},
    ("POST", "/tasks"): {
        "status": 201,
        "request": _object({"project": STRING, "title": STRING, "description": STRING, "tags": TAGS,
                            "status": STRING, "human": BOOLEAN, "kind": {"type": "string", "enum": ["task", "control"]},
                            "control": {"type": "string", "enum": ["pause", "hint"]},
                            "scope": {"type": "string", "enum": ["project", "all", "mine"]}, "initiative": STRING},
                           required=["project", "title"], closed=True),
        "response": TASK_WITH_CONTROL},
    ("GET", "/search"): {"response": TASK_LIST,
                         "query": [_q("q", STRING), _q("project", STRING), _q("include_done", BOOL_QUERY)]},
    ("POST", "/next"): {
        "request": _object({"project": STRING, "task": STRING}, required=[]),
        "response": _object({"task": _nullable(TASK), "last_review": _nullable(COMMENT), "paused": BOOLEAN,
                             "pause": _nullable(CONTROL_ENTRY), "control": CONTROL}, required=["task", "control"])},
    ("GET", "/projects/<slug>/tasks/<int:number>"): {"response": TASK_DETAIL},
    ("GET", "/projects/<slug>/initiatives/<initiative>/tasks/<int:number>"): {"response": TASK_DETAIL},
    ("GET", "/projects/<slug>/initiatives"): {"response": _object({"initiatives": {"type": "array", "items": INITIATIVE}})},
    ("POST", "/projects/<slug>/initiatives"): {
        "status": 201, "request": _object({"slug": STRING, "title": STRING, "rank": NUMBER},
                                          required=["slug", "title"], closed=True),
        "response": INITIATIVE},
    ("PUT", "/projects/<slug>/initiatives/<initiative>"): {
        "request": _object({"title": STRING, "rank": NUMBER}, required=[], closed=True), "response": INITIATIVE},
    ("PATCH", "/projects/<slug>/tasks/<int:number>"): {
        "request": _object({"title": STRING, "description": STRING, "tags": TAGS, "status": STRING, "human": BOOLEAN,
                            "index": INTEGER, "rank": NUMBER, "version": INTEGER, "initiative": _nullable(STRING),
                            "assignee": _nullable(STRING)},
                           required=[], closed=True),
        "response": TASK_WITH_CONTROL},
    ("DELETE", "/projects/<slug>/tasks/<int:number>"): {"status": 204},
    ("POST", "/projects/<slug>/tasks/<int:number>/release"): {"request": {"type": "object"},
                                                             "response": TASK_WITH_CONTROL},
    ("GET", "/stuck"): {"response": _object({"tasks": {"type": "array", "items": STUCK_TASK}, "control": CONTROL}),
                        "query": [_q("project", STRING), _q("minutes", STRING, "Standard 60")]},
    ("GET", "/projects/<slug>/tasks/<int:number>/comments"): {
        "response": _object({"comments": {"type": "array", "items": COMMENT}})},
    ("POST", "/projects/<slug>/tasks/<int:number>/comments"): {
        "status": 201, "request": _object({"body": STRING, "author_name": STRING}, required=["body"]),
        "response": _object({**COMMENT["properties"], "control": CONTROL})},
    ("GET", "/projects/<slug>/tasks/<int:number>/history"): {
        "response": _object({"history": {"type": "array", "items": EVENT}})},
    ("POST", "/projects/<slug>/tasks/<int:number>/review"): {
        "request": _object({"state": {"type": "string", "enum": [*REVIEW_RESULTS, "none"]}, "comment": STRING,
                            "blocking": INTEGER, "suggestions": INTEGER, "checked": STRING},
                           required=["state"], closed=True),
        "response": TASK},
    ("GET", "/projects/<slug>/history"): {"response": _object({"history": {"type": "array", "items": EVENT}})},
    ("PUT", "/comments/<comment_id>"): {"request": _object({"body": STRING}), "response": COMMENT},
    ("DELETE", "/comments/<comment_id>"): {"status": 204},
    ("POST", "/import"): {"request": {"type": "object"},
                          "response": _object({"projects_created": INTEGER, "tasks_imported": INTEGER,
                                               "tasks_skipped": INTEGER, "comments_imported": INTEGER,
                                               "skipped_refs": {"type": "array", "items": STRING}})},
}

VERSIONS_SCHEMA = {"response": VERSIONS}


def schema_for(method: str, relative_path: str) -> dict:
    """Kopie des Eintrags (der Generator ergaenzt ihn, das Original bleibt unveraendert)."""
    return deepcopy(BOARD_SCHEMAS.get((method, relative_path), {}))
