# PR-Template

## Pflichtfelder

```markdown
## Beschreibung
[Was aendert dieser PR?]

## Typ
- [ ] Feature
- [ ] Bugfix
- [ ] Refactoring
- [ ] Dokumentation

## Betroffene Flows
[Welche docs/flows/*.md sind betroffen? Welche muessen aktualisiert werden?]

## Tests
- [ ] Neue Tests geschrieben
- [ ] Bestehende Tests gruen (`python -m pytest tests/ -q`)
- [ ] Testabdeckung fuer den geaenderten Code

## Docs-Debt
- [ ] Keine Doku-Aenderung noetig
- [ ] docs/ aktualisiert: [welche Dateien?]
- [ ] API-Referenz regeneriert (`python scripts/gen-api-ref.py`)
- [ ] Docstrings fuer neue Klassen/Funktionen

## Schichtgrenzen
- [ ] Keine Import-Verletzung (`grep -r "from conclave.infrastructure" src/conclave/domain/`)
- [ ] Neue Protocols in ports.py fuer neue Interfaces

## Security
- [ ] Keine hartcodierten Secrets
- [ ] Path-Traversal-Schutz bei Dateizugriff
- [ ] Input-Validierung bei neuen Endpoints
```

## Wann ist ein PR mergebar?

1. Alle Tests gruen
2. Docs-Debt beantwortet (nicht "nein" ankreuzen und ignorieren)
3. Kein Schichtgrenzen-Verstoss
4. Mindestens 1 Review
5. Betroffene Flow-Docs aktualisiert (oder explizit als Docs-Debt markiert)

## Guard-Prinzip

Aus dem Dokumentationsplan (Section 6):
> "Jedes dokumentierte Interface existiert im Code"

Wenn ein PR ein Interface aendert das in docs/ referenziert wird,
muss die Doku im gleichen PR aktualisiert werden — nicht als Follow-Up.
