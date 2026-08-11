## Beschreibung
[Was ändert dieser PR?]

## Typ
- [ ] Feature
- [ ] Bugfix
- [ ] Refactoring
- [ ] Dokumentation

## Betroffene Flows
[Welche docs/flows/*.md sind betroffen? Welche müssen aktualisiert werden?]

## Tests
- [ ] Neue Tests geschrieben
- [ ] Bestehende Tests grün (`python -m pytest tests/ -q`)
- [ ] Testabdeckung für den geänderten Code

## Docs-Debt
- [ ] Keine Doku-Änderung nötig
- [ ] docs/ aktualisiert: [welche Dateien?]
- [ ] API-Referenz regeneriert (`python scripts/gen-openapi.py`)
- [ ] Docstrings für neue Klassen/Funktionen

## Schichtgrenzen
- [ ] Keine Import-Verletzung (`rg "from conclave.infrastructure" src/conclave/domain`)
- [ ] Neue Protocols in ports.py für neue Interfaces

## Security
- [ ] Keine hartcodierten Secrets
- [ ] Path-Traversal-Schutz bei Dateizugriff
- [ ] Input-Validierung bei neuen Endpoints
