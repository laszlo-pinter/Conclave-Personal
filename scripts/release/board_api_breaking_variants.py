"""Erzeugt absichtlich brechende Varianten des Board-v1-Vertrags (T3, Selbsttest der CI).

``check_board_api.sh`` prueft, dass ``oasdiff breaking --fail-on ERR`` jede Variante als
Bruch meldet und den unveraenderten Vertrag nicht. So ist die Abnahme "eine absichtlich
brechende Aenderung laesst die CI scheitern" in jedem Lauf belegt, und ein falsch
eingestelltes Werkzeug (Version, Flag) faellt sofort auf.

Aufruf: python scripts/release/board_api_breaking_variants.py <board-v1.json> <ausgabeordner>
"""

import copy
import json
import sys
from pathlib import Path


def _json(op: dict, kind: str) -> dict:
    holder = op["requestBody"] if kind == "request" else next(
        r for code, r in op["responses"].items() if code.startswith("2") and "content" in r)
    return holder["content"]["application/json"]["schema"]


def removed_operation(spec: dict) -> dict:
    """Route entfernt: GET /board/v1/tasks."""
    spec["paths"]["/board/v1/tasks"].pop("get")
    return spec


def new_required_request_field(spec: dict) -> dict:
    """Neues Pflichtfeld in der Anfrage: POST /board/v1/tasks verlangt ``priority``."""
    schema = _json(spec["paths"]["/board/v1/tasks"]["post"], "request")
    schema["properties"]["priority"] = {"type": "string"}
    schema["required"] = sorted({*schema.get("required", []), "priority"})
    return spec


def removed_response_field(spec: dict) -> dict:
    """Antwortfeld entfernt: ``ref`` fehlt im Ticket von GET /board/v1/projects/{slug}/tasks/{number}."""
    schema = _json(spec["paths"]["/board/v1/projects/{slug}/tasks/{number}"]["get"], "response")
    schema["properties"].pop("ref")
    schema["required"] = [name for name in schema["required"] if name != "ref"]
    return spec


def changed_field_type(spec: dict) -> dict:
    """Typ geaendert: ``number`` im Ticket wird Text."""
    schema = _json(spec["paths"]["/board/v1/projects/{slug}/tasks/{number}"]["get"], "response")
    schema["properties"]["number"] = {"type": "string"}
    return spec


VARIANTS = {
    "removed-operation": removed_operation,
    "new-required-request-field": new_required_request_field,
    "removed-response-field": removed_response_field,
    "changed-field-type": changed_field_type,
}


def main(argv: list[str]) -> int:
    source, out = Path(argv[0]), Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    spec = json.loads(source.read_text(encoding="utf-8"))
    for name, change in VARIANTS.items():
        (out / f"{name}.json").write_text(json.dumps(change(copy.deepcopy(spec)), indent=2), encoding="utf-8")
        print(out / f"{name}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
