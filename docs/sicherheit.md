# Sicherheit Fuer Conclave Personal

Conclave Personal ist als lokales Werkzeug fuer einzelne Nutzer gedacht. Die
lokale API ist ein technischer Betriebsmodus, kein oeffentliches Internet-
Interface.

## Lokale API

- Standard-Host ist `127.0.0.1`.
- Die API sollte nicht an `0.0.0.0` gebunden werden, solange sie nicht bewusst
  hinter einem eigenen Schutzmechanismus betrieben wird.
- Im `production`-Modus muss `CONCLAVE_API_KEY` gesetzt sein.
- Browser-Clients senden den API-Key als Bearer-Token.
- CORS wird ueber `CONCLAVE_ALLOWED_ORIGINS` begrenzt.

Empfohlene lokale Produktion:

```powershell
$env:CONCLAVE_MODE = "production"
$env:CONCLAVE_API_KEY = "<starkes-lokales-token>"
conclave desktop
```

## Secrets

- Provider-API-Keys gehoeren nicht in Git.
- `.env`, `*.key`, `*.pem`, lokale DBs und Logs sind aus Git und den Release-
  Artefakten ausgeschlossen.
- Agent-Keys werden lokal verschluesselt gespeichert, wenn sie in der DB
  abgelegt werden.
- `CONCLAVE_SECRET_KEY` oder `CONCLAVE_SECRET_KEY_FILE` nach der Erstanlage
  nicht ohne Backup wechseln, sonst koennen verschluesselte Werte unlesbar
  werden.

## Workspace

- Workspace-Zugriffe bleiben innerhalb des konfigurierten Workspace-Roots.
- Pfad-Traversal und absolute Ausbrueche werden blockiert.
- Versteckte Pfade mit Komponenten wie `.private/` werden nicht gelesen oder
  angezeigt.
- Dateigroessenlimits verhindern versehentliche Vollimporte grosser Dateien in
  Agent-Kontexte.

## Provider

- Echte Provider-Calls laufen nur, wenn ein Agent mit passendem Provider, Modell
  und Key konfiguriert ist.
- Tests und CI verwenden Mocks, Fakes oder lokale In-Memory-Komponenten.
- Lokale Ollama-Modelle koennen ohne API-Key betrieben werden.

## Release-Artefakte

Vor einem Release werden Wheel und Source Distribution auf verbotene Inhalte
geprueft:

- keine Workspace-Daten
- keine Datenbanken
- keine Secret-Key-Dateien
- keine Logs
- keine Python-Caches
- keine alten DSGVO-/Legal-Pfade

Siehe auch: [Release-Checkliste](release-checkliste.md).
