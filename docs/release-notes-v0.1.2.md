# Release Notes: v0.1.2

## Kurzfassung

Conclave v0.1.2 ist ein Packaging-Patch. Die UI-Ressourcen werden jetzt direkt
als Python-Package-Data ausgeliefert, damit `conclave desktop` aus Wheel-,
pipx- und normalen Installationen robuster startet.

## Änderungen

- UI, CSS, JavaScript, OpenAPI-Datei und Startskripte liegen als Package-Data
  unter `src/conclave/assets/`.
- Runtime-Asset-Lookup nutzt `importlib.resources` statt installierter
  `share/conclave`-Pfade.
- `tool.setuptools.data-files` wurde entfernt.
- Release- und CI-Prüfungen validieren die neue Wheel-/sdist-Struktur.
- README und UI-Architekturdokumentation unterscheiden jetzt klar zwischen
  aktuellem flachen JavaScript-Aufbau und späterem Zielbild.

## Installation

```bash
pipx install conclave-personal
conclave desktop
```

## Lokale Artefaktprüfung

```bash
python -m build --sdist --wheel
python -m venv .venv-smoke
.venv-smoke/Scripts/pip install dist/conclave_personal-0.1.2-py3-none-any.whl
.venv-smoke/Scripts/conclave --help
```

Unter Linux entsprechend mit `.venv-smoke/bin/...`.

## Status

v0.1.2 bleibt Alpha.
