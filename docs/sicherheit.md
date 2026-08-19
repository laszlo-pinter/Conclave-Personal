# Sicherheit Für Conclave Personal

Conclave Personal ist als lokales Werkzeug für einzelne Nutzer gedacht. Die
lokale API ist ein technischer Betriebsmodus, kein öffentliches Internet-
Interface.

## Lokale API

- Standard-Host ist `127.0.0.1`.
- Bindung an Nicht-Loopback-Adressen wie `0.0.0.0` ist nur mit
  `CONCLAVE_API_KEY` erlaubt.
- Im `production`-Modus muss `CONCLAVE_API_KEY` gesetzt sein.
- Browser-Clients senden den API-Key als Bearer-Token.
- CORS wird über `CONCLAVE_ALLOWED_ORIGINS` begrenzt.
- `Origin: null` ist nicht Teil der Default-CORS-Allowlist und muss bewusst
  konfiguriert werden.
- API-Key-Vergleiche laufen konstantzeitnah über `hmac.compare_digest`.

Empfohlene lokale Produktion:

```powershell
$env:CONCLAVE_MODE = "production"
$env:CONCLAVE_API_KEY = "<starkes-lokales-token>"
conclave desktop
```

## Secrets

- Provider-API-Keys gehören nicht in Git.
- `.env`, `*.key`, `*.pem`, lokale DBs und Logs sind aus Git und den Release-
  Artefakten ausgeschlossen.
- Agent-Keys werden lokal verschlüsselt gespeichert, wenn sie in der DB
  abgelegt werden.
- `CONCLAVE_SECRET_KEY` oder `CONCLAVE_SECRET_KEY_FILE` nach der Erstanlage
  nicht ohne Backup wechseln, sonst können verschlüsselte Werte unlesbar
  werden.

## Workspace

- Workspace-Zugriffe bleiben innerhalb des konfigurierten Workspace-Roots.
- Pfad-Traversal und absolute Ausbrüche werden blockiert.
- Versteckte Pfade mit Komponenten wie `.private/` werden nicht gelesen oder
  angezeigt.
- Dateigrößenlimits verhindern versehentliche Vollimporte großer Dateien in
  Agent-Kontexte.

## Provider

- Echte Provider-Calls laufen nur, wenn ein Agent mit passendem Provider, Modell
  und Key konfiguriert ist.
- Tests und CI verwenden Mocks, Fakes oder lokale In-Memory-Komponenten.
- Lokale Ollama-Modelle können ohne API-Key betrieben werden.
- Custom-Provider-URLs werden gegen SSRF-Risiken geprüft. Private,
  reservierte, Loopback- und Link-Local-Ziele werden blockiert; DNS-Auflösung
  auf solche Ziele wird ebenfalls abgelehnt. Localhost ist nur für explizite
  lokale Provider wie Ollama erlaubt.

## Release-Artefakte

Vor einem Release werden Wheel und Source Distribution auf verbotene Inhalte
geprüft:

- keine Workspace-Daten
- keine Datenbanken
- keine Secret-Key-Dateien
- keine Logs
- keine Python-Caches
- keine alten DSGVO-/Legal-Pfade

Siehe auch: [Release Notes v0.1.17](release-notes-v0.1.17.md).
