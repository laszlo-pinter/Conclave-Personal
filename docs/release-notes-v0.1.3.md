# Release Notes: v0.1.3

## Kurzfassung

Conclave v0.1.3 ist ein kleiner Veröffentlichungs-Patch für die öffentliche
Projektdarstellung und die Quellverteilung.

## Änderungen

- README-Installation beschreibt das veröffentlichte Paket eindeutig als
  `conclave-personal`; der CLI-Befehl bleibt `conclave`.
- Vorveröffentlichungsformulierungen im README wurden entfernt.
- Release-Verifikation im README beschreibt den geprüften Stand in
  Vergangenheitsform.
- Screenshots bleiben im GitHub-README sichtbar, werden aber nicht mehr in das
  sdist aufgenommen.
- Readiness-Tests schützen die korrigierten Installationshinweise und die
  schlankere sdist-Konfiguration.

## Installation

```bash
pipx install conclave-personal
conclave desktop
```

## Lokale Artefaktprüfung

```bash
python -m build --sdist --wheel
python -m venv .venv-smoke
.venv-smoke/Scripts/pip install dist/conclave_personal-0.1.3-py3-none-any.whl
.venv-smoke/Scripts/conclave --help
```

Unter Linux entsprechend mit `.venv-smoke/bin/...`.

## Status

v0.1.3 bleibt Alpha.
