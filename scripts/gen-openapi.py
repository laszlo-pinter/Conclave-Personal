#!/usr/bin/env python3
"""Generiert die OpenAPI-Spec aus den Flask-Routes in app.py."""

import json
import re
from pathlib import Path

APP_PY = Path(__file__).parent.parent / "src" / "conclave" / "api" / "app.py"
ROOT = Path(__file__).parent.parent
OUTS = (
    ROOT / "static" / "openapi.json",
    ROOT / "src" / "conclave" / "assets" / "static" / "openapi.json",
)

# Bekannte Request/Response-Schemas pro Endpoint-Pattern.
# Wer einen Client gegen Conclave baut, sollte sich an die hier gelisteten
# Field-Names halten — sie sind Vertragsbestandteil zwischen Conclave und seinen
# Konsumenten (AlphaStruct, Inducta-AI, ...).
SCHEMAS = {
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
            "participant_id": {"type": "string"}, "name": {"type": "string"}, "type": {"type": "string", "enum": ["model", "user"]},
        }},
        "response": {"properties": {"participant_id": {"type": "string"}}},
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
                          "description": "Teilmenge von [kanzo] reviewers; Standard: alle erlaubten"},
            "include_previous": {"type": "boolean", "default": False},
            "requested_by": {"type": "string"},
        }},
        "response": {"required": ["id", "status", "reviewers"], "properties": {
            "id": {"type": "string"}, "status": {"type": "string"}, "task": {"type": "string"},
            "reviewers": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "provider": {"type": "string"}}}},
        }},
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



def _project_version() -> str:
    import tomllib
    data = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]

def extract_routes(source: str) -> list[dict]:
    pattern = re.compile(
        r'@app\.(get|post|put|delete)\(["\']([^"\']+)["\']\)\s*\n'
        r'\s*def\s+(\w+)\(.*?\):\s*\n'
        r'(?:\s*"""(.*?)""")?',
        re.DOTALL,
    )
    routes = []
    for m in pattern.finditer(source):
        method = m.group(1).upper()
        path = m.group(2)
        func = m.group(3)
        doc = (m.group(4) or "").strip().split("\n")[0]
        routes.append({"method": method, "path": path, "func": func, "doc": doc})
    return routes


def flask_to_openapi_path(path: str) -> str:
    """Konvertiert Flask-Pfad (<param>) zu OpenAPI-Pfad ({param})."""
    return re.sub(r'<(?:path:)?(\w+)>', r'{\1}', path)


def build_spec(routes: list[dict]) -> dict:
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

        # Response-Body aus SCHEMAS (falls vorhanden)
        schema_key = (r["method"], r["path"])
        resp_200 = {"description": "Erfolg"}
        if schema_key in SCHEMAS and "response" in SCHEMAS[schema_key]:
            resp_schema = SCHEMAS[schema_key]["response"]
            resp_200["content"] = {"application/json": {"schema": {"type": "object", **resp_schema}}}

        operation = {
            "summary": doc,
            "tags": [tag],
            "operationId": r["func"],
            "responses": {
                "200": resp_200,
            },
        }

        # Path-Parameter extrahieren
        params = re.findall(r'\{(\w+)\}', oapi_path)
        if params:
            operation["parameters"] = [
                {"name": p, "in": "path", "required": True, "schema": {"type": "string"}}
                for p in params
            ]

        # Request-Body aus SCHEMAS
        if schema_key in SCHEMAS and "request" in SCHEMAS[schema_key]:
            req_schema = SCHEMAS[schema_key]["request"]
            # required: True nur wenn das Schema mindestens ein required-Feld definiert
            # (sonst ist der Body optional).
            body_required = bool(req_schema.get("required"))
            operation["requestBody"] = {
                "required": body_required,
                "content": {"application/json": {"schema": {"type": "object", **req_schema}}},
            }

        if method in ("post", "put", "delete"):
            if "requestBody" not in operation and method in ("post", "put"):
                operation["requestBody"] = {
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }

        paths.setdefault(oapi_path, {})[method] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Conclave API",
            "description": "Host-gesteuertes Multi-Model-Konversationssystem",
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


def main():
    source = APP_PY.read_text(encoding="utf-8")
    routes = extract_routes(source)
    spec = build_spec(routes)
    payload = json.dumps(spec, indent=2, ensure_ascii=False)
    for out in OUTS:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(f"{len(routes)} Routes -> {', '.join(str(out) for out in OUTS)}")


if __name__ == "__main__":
    main()
