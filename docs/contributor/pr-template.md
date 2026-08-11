# PR-Template

## Pflichtfelder

```markdown
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
- [ ] API-Referenz regeneriert (`python scripts/gen-api-ref.py`)
- [ ] Docstrings für neue Klassen/Funktionen

## Schichtgrenzen
- [ ] Keine Import-Verletzung (`grep -r "from conclave.infrastructure" src/conclave/domain/`)
- [ ] Neue Protocols in ports.py für neue Interfaces

## Security
- [ ] Keine hartcodierten Secrets
- [ ] Path-Traversal-Schutz bei Dateizugriff
- [ ] Input-Validierung bei neuen Endpoints
```

## Wann ist ein PR mergebar?

1. Alle Tests grün
2. Docs-Debt beantwortet (nicht "nein" ankreuzen und ignorieren)
3. Kein Schichtgrenzen-Verstoss
4. Mindestens 1 Review
5. Betroffene Flow-Docs aktualisiert (oder explizit als Docs-Debt markiert)

## Guard-Prinzip

Aus dem Dokumentationsplan (Section 6):
> "Jedes dokumentierte Interface existiert im Code"

Wenn ein PR ein Interface ändert das in docs/ referenziert wird,
muss die Doku im gleichen PR aktualisiert werden — nicht als Follow-Up.
