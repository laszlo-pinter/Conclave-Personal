#!/usr/bin/env python3
"""Generiert die OpenAPI-Spezifikationen aus den registrierten Flask-Routen (T3).

Statt den Quelltext per Regex zu lesen, baut das Skript die Apps und liest ihre
``url_map``: Personal (``conclave.api.app``) und die Board-App
(``conclave_board.api.app``). Ausgaben:

- ``static/openapi.json`` und ``src/conclave/assets/static/openapi.json``: alle Routen
  von Personal; der Alias ``/board/...`` ist als ``deprecated`` markiert.
- ``packages/board/openapi/board-v1.json``: der Vertrag der Board-API v1
  (``/board/v1/...`` und ``/board/versions``). Gegen ihn prueft die CI mit
  ``oasdiff breaking``, ob eine Aenderung innerhalb von v1 bricht.

Aufruf: python scripts/gen-openapi.py
"""

import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "board" / "src"))
sys.path.insert(0, str(ROOT / "src"))

OUTS = (
    ROOT / "static" / "openapi.json",
    ROOT / "src" / "conclave" / "assets" / "static" / "openapi.json",
)
BOARD_V1_OUT = ROOT / "packages" / "board" / "openapi" / "board-v1.json"

# Bekannte Request/Response-Schemas pro Endpoint-Pattern.
# Wer einen Client gegen Conclave baut, sollte sich an die hier gelisteten
# Field-Names halten — sie sind Vertragsbestandteil zwischen Conclave und seinen
# Konsumenten (AlphaStruct, Inducta-AI, ...).
_MESSAGE = {"type": "object", "properties": {
    "id": {"type": "string"}, "sequence": {"type": "integer"},
    "author_type": {"type": "string", "enum": ["user", "model"]},
    "author_id": {"type": "string", "nullable": True},
    "origin": {"type": "string", "enum": ["human", "agent"], "nullable": True,
               "description": "Zugang laut Token; null = unbekannt (Modellantworten, alte Nachrichten, CLI)"},
    "content": {"type": "string"},
}}

SCHEMAS = {
    ("POST", "/board/import"): {
        "errors": {"400": "Export ungueltig (ImportFormatError), es wurde nichts geschrieben",
                   "403": "HumanOnly: nur mit dem Mensch-Token",
                   "413": "ImportTooLarge: Export groesser als 50 MB"},
    },
    ("GET", "/conversations/<conversation_id>"): {
        "response": {"required": ["id", "messages"], "properties": {
            "id": {"type": "string"}, "status": {"type": "string"},
            "messages": {"type": "array", "items": _MESSAGE},
            "participants": {"type": "array", "items": {"type": "object"}},
        }},
    },
    ("GET", "/conversations/<conversation_id>/export"): {
        "response": {"required": ["id", "messages"], "properties": {
            "id": {"type": "string"}, "topic": {"type": "string"},
            "messages": {"type": "array", "items": _MESSAGE},
            "participants": {"type": "array", "items": {"type": "object"}},
            "context_reports": {"type": "array", "items": {"type": "object"}},
        }},
    },
    ("POST", "/conversations"): {
        "request": {"properties": {"topic": {"type": "string"}}, "example": {"topic": "Mein Thema"}},
        "response": {"required": ["conversation_id"], "properties": {"conversation_id": {"type": "string"}}},
    },
    ("POST", "/conversations/<conversation_id>/messages"): {
        "request": {"required": ["content"], "properties": {"content": {"type": "string"}}},
        "response": {"properties": {"content": {"type": "string"}, "sequence": {"type": "integer"},
                                    "origin": {"type": "string", "enum": ["human", "agent"],
                                               "description": "Zugang laut Token; nie aus dem Body"}}},
    },
    ("POST", "/conversations/<conversation_id>/participants"): {
        "request": {"required": ["participant_id", "name"], "properties": {
            "participant_id": {"type": "string"}, "name": {"type": "string"},
            "type": {"type": "string", "enum": ["model", "user"], "default": "model",
                     "description": "Mit dem Agent-Token nur model"},
        }},
        "response": {"properties": {"participant_id": {"type": "string"}}},
        "errors": {"400": "type ist nicht model oder user (ValidationError)",
                   "403": "HumanOnly: type user mit dem Agent-Token"},
    },
    ("POST", "/conversations/<conversation_id>/participants/<participant_id>/invoke"): {
        "response": {
            "required": ["participant_id", "content"],
            "properties": {
                "participant_id": {"type": "string"},
                "content": {"type": "string"},
                "sequence": {"type": "integer"},
            },
        },
    },
    ("POST", "/conversations/<conversation_id>/floor/grant"): {
        "request": {"required": ["participant_id"], "properties": {"participant_id": {"type": "string"}}},
    },
    ("POST", "/agents"): {
        "request": {"required": ["id", "name", "model"], "properties": {
            "id": {"type": "string"}, "name": {"type": "string"}, "provider": {"type": "string"},
            "model": {"type": "string"}, "preset": {"type": "string"}, "api_key": {"type": "string"},
            "api_url": {"type": "string"}, "system_prompt": {"type": "string"},
            "max_messages": {"type": "integer", "minimum": 0, "nullable": True,
                             "description": "Kuerzungslimit: null = globaler Default, 0 = keine Kuerzung"},
        }},
    },
    ("POST", "/conversations/<conversation_id>/orchestrate"): {
        "request": {"required": ["sequence"], "properties": {"sequence": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "string", "minLength": 1}}}},
    },
    ("POST", "/conversations/<conversation_id>/orchestrate-parallel"): {
        "request": {"required": ["groups"], "properties": {"groups": {"type": "array", "minItems": 1, "items": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}}}},
    },
    ("POST", "/conversations/<conversation_id>/orchestrate-parallel-stream"): {
        "request": {"required": ["groups"], "properties": {"groups": {"type": "array", "minItems": 1, "items": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}}}},
    },
    ("POST", "/conversations/<conversation_id>/auto-loop"): {
        "request": {"required": ["sequence"], "properties": {
            "sequence": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "string", "minLength": 1}},
            "stop_signal": {"type": "string", "default": "@done", "minLength": 1, "maxLength": 128},
            "max_rounds": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
            "rotation": {"type": "string", "default": "none", "enum": ["none", "round_robin"]},
        }},
    },
    ("GET", "/health"): {
        "response": {"required": ["status"], "properties": {"status": {"type": "string"}}},
    },
    ("GET", "/auth/whoami"): {
        "response": {"required": ["role"], "properties": {"role": {"type": "string", "enum": ["human", "agent"]}}},
    },
    ("GET", "/providers"): {
        "response": {"required": ["providers"], "properties": {"providers": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "label": {"type": "string"},
                "description": {"type": "string"},
                "requires_api_key": {"type": "boolean"},
                "api_key_available": {"type": "boolean"},
                "api_key_configured": {"type": "boolean"},
                "local": {"type": "boolean"},
                "recommended": {"type": "boolean"},
                "models": {"type": "array", "items": {"type": "string"}},
            },
        }}}},
    },
    ("GET", "/agent-roles"): {
        "response": {"required": ["roles"], "properties": {"roles": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "label": {"type": "string"},
                "prompt": {"type": "string"},
            },
        }}}},
    },
    ("GET", "/conversations/<conversation_id>/messages/<message_id>/context"): {
        "response": {"required": ["report"], "properties": {
            "id": {"type": "string"}, "run_id": {"type": "string"}, "message_id": {"type": "string"},
            "participant_id": {"type": "string"},
            "usage": {"type": "object", "properties": {
                "input_tokens": {"type": "integer"}, "output_tokens": {"type": "integer"}}},
            "report": {"type": "object", "properties": {
                "messages_total": {"type": "integer"}, "messages_sent": {"type": "integer"},
                "omitted_sequences": {"type": "array", "items": {"type": "integer"}},
                "anchor_sequence": {"type": "integer"}, "truncation_limit": {"type": "integer"},
                "system_parts": {"type": "array", "items": {"type": "string"}},
                "context_files": {"type": "array", "items": {"type": "object"}},
                "skipped_context_files": {"type": "array", "items": {"type": "object"}},
                "inline_files": {"type": "array", "items": {"type": "object"}},
                "read_results": {"type": "array", "items": {"type": "object"}},
                "estimated_tokens": {"type": "integer"}, "adapter": {"type": "string"},
                "attempts": {"type": "integer"},
            }},
        }},
    },
    ("GET", "/conversations/<conversation_id>/participants/<participant_id>/context-preview"): {
        "response": {"required": ["participant_id", "report"], "properties": {
            "participant_id": {"type": "string"}, "report": {"type": "object"},
        }},
    },
    ("POST", "/consultations"): {
        "request": {"required": ["task", "question"],
                    "description": "Der Kanal (human/agent) ergibt sich aus dem Token. "
                                   "Ein Feld channel im Body wird mit 400 (ChannelNotAllowed) abgelehnt.",
                    "properties": {
            "task": {"type": "string", "example": "api#12"},
            "question": {"type": "string", "maxLength": 4000},
            "context": {"type": "string", "maxLength": 8000},
            "reviewers": {"type": "array", "items": {"type": "string"},
                          "description": "Teilmenge von [consultations] reviewers; Standard: alle erlaubten"},
            "include_previous": {"type": "boolean", "default": False},
            "requested_by": {"type": "string"},
        }},
        "response": {"required": ["id", "status", "reviewers"], "properties": {
            "id": {"type": "string"}, "status": {"type": "string"}, "task": {"type": "string"},
            "reviewers": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "provider": {"type": "string"}}}},
        }},
        "errors": {"429": "ConsultationLimit (je Ticket und Stunde); fuer Agenten auch AgentBudgetExceeded "
                          "(Tagesbudget, [limits]). Erreicht ein Agent erst im Worker eine Grenze "
                          "(Budget oder TooManyAgentRuns), endet die Consultation mit status failed und "
                          "der Meldung in error."},
    },
    ("GET", "/consultations/<consultation_id>"): {
        "response": {"required": ["id", "status", "deliveries"], "properties": {
            "id": {"type": "string"}, "status": {"type": "string"}, "error": {"type": "string"},
            "conversation_id": {"type": "string"},
            "deliveries": {"type": "array", "items": {"type": "object"}},
            "retry_possible": {"type": "boolean"},
        }},
    },
    ("GET", "/consultations"): {
        "response": {"required": ["consultations"], "properties": {
            "consultations": {"type": "array", "items": {"type": "object"}}}},
    },
    ("POST", "/consultations/<consultation_id>/retry"): {
        "request": {"properties": {"rerun": {"type": "boolean", "default": False,
                                             "description": "true: Modelle erneut aufrufen (neue Consultation)"}}},
    },
    ("GET", "/conversations/<conversation_id>/tool-events"): {
        "response": {"required": ["tool_events"], "properties": {"tool_events": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "conversation_id": {"type": "string"},
                "message_id": {"type": "string", "nullable": True},
                "run_id": {"type": "string", "nullable": True},
                "participant_id": {"type": "string"},
                "tool": {"type": "string"},
                "status": {"type": "string"},
                "input": {"type": "object"},
                "output": {"type": "object"},
                "error": {"type": "string", "nullable": True},
                "created_at": {"type": "string"},
            },
        }}}},
    },
    ("POST", "/agents/<agent_id>/test"): {
        "response": {"required": ["success", "status", "message"], "properties": {
            "success": {"type": "boolean"},
            "status": {"type": "string"},
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "latency_ms": {"type": "integer"},
            "message": {"type": "string"},
            "hint": {"type": "string"},
        }},
    },
    ("GET", "/runs"): {
        "response": {"required": ["runs"], "properties": {"runs": {"type": "array", "items": {"type": "object"}}}},
    },
    ("GET", "/runs/<run_id>"): {
        "response": {"required": ["id", "conversation_id"], "properties": {
            "id": {"type": "string"},
            "conversation_id": {"type": "string"},
            "origin": {"type": "string", "nullable": True, "enum": ["agent", None],
                       "description": "agent, wenn ein Agent den Lauf ausgeloest hat (R11); sonst null"},
        }},
    },
    ("GET", "/settings"): {
        "response": {"required": ["settings"], "properties": {"settings": {
            "type": "object",
            "properties": {
                "workspace_path": {"type": "string"},
                "workspace_limits": {"type": "object"},
                "provider_keys": {"type": "object"},
            },
        }}},
    },
    ("PUT", "/settings"): {
        "request": {"properties": {"workspace_path": {"type": "string"}}},
        "response": {"required": ["settings"], "properties": {"settings": {
            "type": "object",
            "properties": {
                "workspace_path": {"type": "string"},
                "workspace_limits": {"type": "object"},
            },
        }}},
    },
    ("POST", "/backup"): {
        "response": {"required": ["backup_path", "format"], "properties": {
            "backup_path": {"type": "string"},
            "format": {"type": "string"},
        }},
    },
    ("POST", "/restore"): {
        "request": {"required": ["backup_path"], "properties": {
            "backup_path": {"type": "string"},
            "replace_workspace": {"type": "boolean", "default": True},
        }},
        "response": {"required": ["status"], "properties": {
            "status": {"type": "string"},
            "format": {"type": "string"},
            "db_restored": {"type": "boolean"},
            "workspace_files_restored": {"type": "integer"},
            "workspace_replaced": {"type": "boolean"},
            "pre_restore_backup_path": {"type": "string"},
        }},
    },
    ("GET", "/workspace"): {
        "response": {"required": ["files"], "properties": {
            "files": {"type": "array", "items": {"type": "object"}},
            "limits": {"type": "object"},
        }},
    },
    ("GET", "/workspace/<path:filepath>"): {
        "response": {"required": ["path", "content"], "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        }},
    },
    ("POST", "/workspace/<path:filepath>"): {
        "request": {"properties": {"content": {"type": "string"}}},
        "response": {"required": ["path", "size"], "properties": {
            "path": {"type": "string"},
            "size": {"type": "integer"},
        }},
    },
}



def _human_only() -> frozenset:
    from conclave.api.access import HUMAN_ONLY as routes
    return routes


HUMAN_ONLY = _human_only()


def _project_version() -> str:
    import tomllib
    data = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]

def routes_from_app(app) -> list[dict]:
    """Routen in Registrierungsreihenfolge: Methode, Flask-Pfad, View-Name, erste Doc-Zeile."""
    from conclave_board.api.versions import ALIAS_PREFIX, V1_PREFIX
    routes = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static" or rule.endpoint.endswith(".static"):   # auch Board-Seite (U1)
            continue
        view = app.view_functions[rule.endpoint]
        doc = (view.__doc__ or "").strip().split("\n")[0]
        blueprint = rule.endpoint.rsplit(".", 1)[0] if "." in rule.endpoint else ""
        for method in sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS")):
            routes.append({
                "method": method, "path": rule.rule, "func": view.__name__, "doc": doc,
                "v1": blueprint == "board_v1",
                "alias": blueprint == "board",
                # Schemas und Zugriffsliste sind fuer beide Praefixe gleich; Schluessel ist der Alias-Pfad
                "key_path": ALIAS_PREFIX + rule.rule[len(V1_PREFIX):] if blueprint == "board_v1" else rule.rule,
            })
    return routes


def personal_app():
    from conclave.api.app import create_app
    return create_app(MagicMock(), allow_unauthenticated=True)


def board_app():
    from conclave_board.api.app import create_board_app
    return create_board_app(None, None, allow_unauthenticated=True)


def flask_to_openapi_path(path: str) -> str:
    """Konvertiert Flask-Pfad (<param>, <conv:param>) zu OpenAPI-Pfad ({param})."""
    return re.sub(r'<(?:\w+:)?(\w+)>', r'{\1}', path)


def path_param_types(path: str) -> dict[str, str]:
    """OpenAPI-Typ je Pfad-Parameter: <int:x> -> integer, sonst string."""
    return {name: ("integer" if conv == "int" else "string")
            for conv, name in re.findall(r'<(?:(\w+):)?(\w+)>', path)}


def _schemas_for(r: dict) -> dict:
    """Eintrag aus SCHEMAS, fuer Board-Routen ergaenzt um die Schemas des Board-Pakets (T3)."""
    from conclave_board.api.schemas import VERSIONS_SCHEMA, schema_for
    from conclave_board.api.versions import ALIAS_PREFIX, VERSIONS_PATH
    entry = dict(SCHEMAS.get((r["method"], r["key_path"]), {}))
    if r["path"] == VERSIONS_PATH:
        entry.update(VERSIONS_SCHEMA)
    elif r["v1"] or r["alias"]:
        entry.update(schema_for(r["method"], r["key_path"][len(ALIAS_PREFIX):]))
    return entry


def build_spec(routes: list[dict], *, title: str = "Conclave API",
               description: str = "Host-gesteuertes Multi-Model-Konversationssystem") -> dict:
    from conclave_board.api.versions import ALIAS_SUNSET, V1_PREFIX
    paths = {}
    tags_set = set()

    for r in routes:
        oapi_path = flask_to_openapi_path(r["path"])
        method = r["method"].lower()
        doc = r["doc"] or r["func"].replace("_", " ").title()

        # Tag aus Pfad ableiten
        parts = oapi_path.strip("/").split("/")
        tag = parts[0] if parts else "other"
        tags_set.add(tag)

        # Response-Body aus SCHEMAS bzw. den Schemas des Board-Pakets (falls vorhanden)
        schema_key = (r["method"], r["key_path"])
        entry = _schemas_for(r)
        success = str(entry.get("status", 200))
        resp_ok = {"description": "Erfolg, ohne Inhalt" if success == "204" else "Erfolg"}
        if "response" in entry:
            resp_ok["content"] = {"application/json": {"schema": {"type": "object", **entry["response"]}}}

        operation = {
            "summary": doc,
            "tags": [tag],
            # v1 eigene IDs; der Alias behaelt die bisherigen (unveraendert fuer bestehende Clients)
            "operationId": ("v1_" + r["func"]) if r["v1"] else r["func"],
            "responses": {
                success: resp_ok,
            },
        }
        for code, text in entry.get("errors", {}).items():
            operation["responses"][code] = {"description": text}
        # Agent-Zugang (api/access.py): alles ausser der Allowlist ergibt 403 HumanOnly
        if r["alias"]:
            operation["deprecated"] = True
            operation["description"] = (f"Abgekuendigter Alias von {V1_PREFIX}{r['path'][len('/board'):]}; "
                                        f"Antworten tragen Deprecation, Sunset ({ALIAS_SUNSET}) und Link.")
        if (r["method"], r["key_path"]) in HUMAN_ONLY:
            note = "Nur mit dem Mensch-Token; das Agent-Token ergibt 403 HumanOnly."
            operation["description"] = (operation.get("description", "") + " " + note).strip()
            operation["responses"].setdefault("403", {"description": "HumanOnly: nur fuer den Menschen-Zugang"})

        # Path-Parameter extrahieren
        params = re.findall(r'\{(\w+)\}', oapi_path)
        types = path_param_types(r["path"])
        if params:
            operation["parameters"] = [
                {"name": p, "in": "path", "required": True, "schema": {"type": types.get(p, "string")}}
                for p in params
            ]
        if entry.get("query"):
            operation.setdefault("parameters", []).extend(entry["query"])

        # Request-Body aus SCHEMAS
        if "request" in entry:
            req_schema = entry["request"]
            # required: True nur wenn das Schema mindestens ein required-Feld definiert
            # (sonst ist der Body optional).
            body_required = bool(req_schema.get("required"))
            operation["requestBody"] = {
                "required": body_required,
                "content": {"application/json": {"schema": {"type": "object", **req_schema}}},
            }

        if method in ("post", "put", "patch", "delete"):
            if "requestBody" not in operation and method in ("post", "put", "patch"):
                operation["requestBody"] = {
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }

        paths.setdefault(oapi_path, {})[method] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "description": description,
            "version": _project_version(),
        },
        "servers": [
            {"url": "http://localhost:8000", "description": "Lokal (localhost)"},
            {"url": "http://127.0.0.1:8000", "description": "Lokal (127.0.0.1)"},
        ],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
                "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            },
        },
        "security": [{"BearerAuth": []}, {"ApiKeyAuth": []}],
    }


def board_v1_spec() -> dict:
    """Vertrag der Board-API v1 aus der Board-App: nur /board/v1/... und /board/versions."""
    from conclave_board.api.versions import V1_PREFIX, VERSIONS_PATH
    routes = [r for r in routes_from_app(board_app())
              if r["path"] == V1_PREFIX or r["path"].startswith(V1_PREFIX + "/") or r["path"] == VERSIONS_PATH]
    spec = build_spec(routes, title="Conclave Board API v1",
                      description="Board-API v1 (Tickets, Review, Vorhaben, Steuertickets). Innerhalb von v1 nur "
                                  "Ergaenzungen; Clients ignorieren unbekannte Felder.")
    spec["servers"] = [{"url": "http://127.0.0.1:8200", "description": "Board-Server lokal"}]
    return spec


def personal_spec() -> dict:
    return build_spec(routes_from_app(personal_app()))


def _write(path: Path, spec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    spec = personal_spec()
    for out in OUTS:
        _write(out, spec)
    board = board_v1_spec()
    _write(BOARD_V1_OUT, board)
    print(f"{sum(len(v) for v in spec['paths'].values())} Operationen -> {', '.join(str(o) for o in OUTS)}")
    print(f"{sum(len(v) for v in board['paths'].values())} Operationen (Board v1) -> {BOARD_V1_OUT}")


if __name__ == "__main__":
    main()
