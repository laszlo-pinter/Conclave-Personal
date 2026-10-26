"""Einzelne Werte in config.toml setzen, ohne den Rest der Datei anzufassen.

tomllib kann nur lesen. Fuer die wenigen Werte, die die UI aendern darf, wird
die Zeile ``key = "wert"`` im passenden Abschnitt ersetzt oder ergaenzt.
Kommentare und andere Abschnitte bleiben erhalten; das Ergebnis wird vor dem
Schreiben mit tomllib geprueft.
"""

import json
import re
import tomllib
from pathlib import Path


def set_toml_string(path: Path, section: str, key: str, value: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    new_line = f"{key} = {json.dumps(value)}"  # JSON-Strings sind gueltige TOML-Basic-Strings

    header = re.compile(rf"^\s*\[\s*{re.escape(section)}\s*\]\s*(#.*)?$")
    any_header = re.compile(r"^\s*\[")
    key_line = re.compile(rf"^\s*{re.escape(key)}\s*=")

    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", new_line]
    else:
        end = next((i for i in range(start + 1, len(lines)) if any_header.match(lines[i])), len(lines))
        existing = next((i for i in range(start + 1, end) if key_line.match(lines[i])), None)
        if existing is not None:
            lines[existing] = new_line
        else:
            insert_at = end
            while insert_at > start + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, new_line)

    result = "\n".join(lines) + "\n"
    if tomllib.loads(result).get(section, {}).get(key) != value:
        raise ValueError(f"config.toml konnte nicht sicher aktualisiert werden ({section}.{key})")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result, encoding="utf-8")
