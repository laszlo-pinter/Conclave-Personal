#!/usr/bin/env python3
"""Generiert static/openapi.json aus den Flask-Routes in app.py."""

import json
import re
from pathlib import Path

APP_PY = Path(__file__).parent.parent / "src" / "conclave" / "api" / "app.py"
OUT = Path(__file__).parent.parent / "static" / "openapi.json"

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
        "response": {"properties": {"content": {"type": "string"}, "sequence": {"type": "integer"}}},
    },
    ("POST", "/conversations/<conversation_id>/participants"): {
        "request": {"required": ["participant_id", "name"], "properties": {
            "participant_id": {"type": "string"}, "name": {"type": "string"}, "type": {"type": "string", "enum": ["model", "user"]},
        }},
        "response": {"properties": {"participant_id": {"type": "string"}}},
    },
    ("POST", "/conversations/<conversation_id>/participants/<participant_id>/invoke"): {
        "request": {
            "description": "Body ist optional. Ohne Body: einfacher Invoke. Mit judge_via: Chain-of-Verification - nach dem Primary-Invoke wird ein Judge-Agent mit dem gerenderten judge_prompt aufgerufen.",
            "properties": {
                "judge_via": {"type": "string", "description": "Agent-ID des Judges (Cross-Model-Verification)."},
                "judge_prompt": {"type": "string", "description": "Template mit Platzhaltern {primary_response} und {original_prompt}. Erforderlich wenn judge_via gesetzt ist."},
            },
        },
        "response": {
            "required": ["participant_id", "content"],
            "properties": {
                "participant_id": {"type": "string"},
                "content": {"type": "string"},
                "sequence": {"type": "integer"},
                "judge": {
                    "type": "object",
                    "description": "Nur gesetzt wenn judge_via im Request war. Bei Judge-Fehler enthaelt es 'error' statt 'content'.",
                    "properties": {
                        "participant_id": {"type": "string"},
                        "content": {"type": "string"},
                        "sequence": {"type": "integer"},
                        "error": {"type": "string"},
                    },
                },
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
        }},
    },
    ("POST", "/conversations/<conversation_id>/orchestrate"): {
        "request": {"required": ["sequence"], "properties": {"sequence": {"type": "array", "items": {"type": "string"}}}},
    },
    ("POST", "/conversations/<conversation_id>/orchestrate-parallel"): {
        "request": {"required": ["groups"], "properties": {"groups": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}}},
    },
    ("POST", "/conversations/<conversation_id>/judge"): {
        "request": {"required": ["primary_id", "judge_id", "judge_prompt"], "properties": {
            "primary_id": {"type": "string"},
            "judge_id": {"type": "string"},
            "judge_prompt": {"type": "string"},
        }},
        "response": {"required": ["participant_id", "content", "judge"], "properties": {
            "participant_id": {"type": "string"},
            "content": {"type": "string"},
            "sequence": {"type": "integer"},
            "judge": {"type": "object"},
        }},
    },
    ("POST", "/conversations/<conversation_id>/auto-loop"): {
        "request": {"required": ["sequence"], "properties": {
            "sequence": {"type": "array", "items": {"type": "string"}},
            "stop_signal": {"type": "string", "default": "@done"},
            "max_rounds": {"type": "integer", "default": 20},
        }},
    },
    ("GET", "/health"): {
        "response": {"required": ["status"], "properties": {"status": {"type": "string"}}},
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
        "request": {"required": ["backup_path"], "properties": {"backup_path": {"type": "string"}}},
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
            # (sonst ist der Body optional, wie bei /invoke mit judge_via).
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
            "version": "0.1.0",
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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(routes)} Routes -> {OUT}")


if __name__ == "__main__":
    main()
