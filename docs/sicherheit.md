# Sicherheit Für Conclave Personal

Conclave Personal ist als lokales Werkzeug für einzelne Nutzer gedacht. Die
lokale API ist ein technischer Betriebsmodus, kein öffentliches Internet-
Interface.

## Lokale API

- Standard-Host ist `127.0.0.1`.
- Die API verlangt immer ein Token. Ist `CONCLAVE_API_KEY` nicht gesetzt,
  erzeugt der Server beim ersten Start ein zufälliges Token und legt es in
  `api.token` im Konfigurationsverzeichnis ab (Linux `0600`, Windows ACL nur
  für den aktuellen Benutzer). CLI-Werkzeuge (`conclave-watch`) und der
  MCP-Server lesen es von dort, wenn `CONCLAVE_API_KEY` leer ist.
- Ohne Token erreichbar sind nur `GET`/`HEAD` auf `/`, `/static/*`, `/health`,
  `/api-docs` und `/openapi.json` sowie CORS-Preflights (`OPTIONS`, leere
  Antwort `204`).
- `conclave desktop` und `conclave web` öffnen den Browser mit dem Token im
  URL-Fragment (`#token=…`). Fragmente werden nicht an den Server gesendet; die
  UI übernimmt das Token und entfernt es sofort aus der Adresszeile.
- Der `Host`-Header wird geprüft (Schutz gegen DNS-Rebinding). Erlaubt sind
  `localhost`, `127.0.0.1` und `[::1]` sowie Einträge aus
  `CONCLAVE_ALLOWED_HOSTS`; andere Hosts erhalten `421`, auch mit gültigem
  Token.
- POST-Anfragen brauchen `Content-Type: application/json` oder den Header
  `X-Conclave-Client`, sonst `415`. Fremde Webseiten können so keine Aktionen
  per einfachem Formular oder `fetch` ohne CORS-Preflight auslösen (CSRF).
- Bindung an Nicht-Loopback-Adressen wie `0.0.0.0` ist nur mit
  `CONCLAVE_API_KEY` und `CONCLAVE_ALLOWED_HOSTS` erlaubt.
- Im `production`-Modus müssen `CONCLAVE_API_KEY` und ein
  Verschlüsselungsschlüssel (`CONCLAVE_SECRET_KEY` oder eine vorhandene
  Schlüsseldatei `secret.key` bzw. `CONCLAVE_SECRET_KEY_FILE`) gesetzt sein;
  `CONCLAVE_DEBUG` wird dort abgelehnt.
- Browser-Clients senden den API-Key als Bearer-Token.
- CORS wird über `CONCLAVE_ALLOWED_ORIGINS` begrenzt.
- `Origin: null` ist nicht Teil der Default-CORS-Allowlist und muss bewusst
  konfiguriert werden.
- API-Key-Vergleiche laufen konstantzeitnah über `hmac.compare_digest`.

Empfohlene lokale Produktion:

```powershell
$env:CONCLAVE_MODE = "production"
$env:CONCLAVE_API_KEY = "<starkes-lokales-token>"
$env:CONCLAVE_SECRET_KEY = "<fernet-schluessel>"  # oder CONCLAVE_SECRET_KEY_FILE / vorhandene secret.key
conclave desktop
```

## Browser-UI

- Modellantworten gelten als nicht vertrauenswürdig. Markdown wird mit
  `marked` in HTML gewandelt und anschließend mit DOMPurify gefiltert
  (`renderMarkdown()` in `static/js/utils.js`).
- Erlaubt sind nur Text- und Strukturelemente (Absätze, Listen, Tabellen,
  Code, Links). Skripte, Bilder, SVG, Formulare, `style`-, `id`- und
  Event-Attribute werden entfernt. Einzige Ausnahme sind GFM-Aufgabenlisten:
  `input` bleibt nur als deaktivierte Checkbox erhalten, andere Eingabefelder
  werden entfernt.
- Links sind nur mit `http(s)`, `mailto` oder `#` erlaubt und öffnen mit
  `target="_blank"` und `rel="noopener noreferrer"`.
- Ist DOMPurify nicht geladen, wird nie HTML ausgegeben, nur escapter Text.
- Alle Bibliotheken und Schriften (DOMPurify, marked, highlight.js, Swagger UI,
  Syne, Syne Mono, DM Sans) werden lokal unter `static/vendor/` ausgeliefert;
  Versionen, Lizenzen und Prüfsummen stehen in `THIRD_PARTY.md`. Zur Laufzeit
  werden keine fremden Server kontaktiert.
- Jede Antwort trägt eine Content-Security-Policy: Skripte, Styles, Schriften,
  Bilder und Verbindungen nur vom eigenen Server (`'self'`, Bilder zusätzlich
  `data:`), keine Inline-Skripte, kein `eval`, keine `<style>`-Blöcke, keine
  Einbettung in fremde Seiten (`frame-ancestors 'none'`). Erlaubt sind nur
  `style`-Attribute (`style-src-attr 'unsafe-inline'`).
- Weitere Header: `Referrer-Policy: no-referrer`, `Permissions-Policy`
  (Mikrofon nur für die eigene Seite wegen der Spracheingabe, Kamera und
  Standort gesperrt).
- Wegen `connect-src 'self'` spricht die UI nur mit dem Server, von dem sie
  geladen wurde. Eine abweichende API-URL im Key-Dialog wird vom Browser
  blockiert.
- Jede `innerHTML`-/`insertAdjacentHTML`-Stelle braucht einen Kommentar
  `// safe-html: <Begründung>`; `tests/ui/test_html_sinks.py` lässt neue Stellen
  ohne Begründung scheitern. Werte aus API-Antworten werden mit `esc()`
  (maskiert `& < > " '`) eingesetzt.

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

- Workspace-Root ist `CONCLAVE_WORKSPACE`, sonst `~/Conclave/workspace` (für
  alle Einstiegspunkte: CLI, `conclave-api`, Server, Desktop).
- Workspace-Zugriffe bleiben innerhalb des konfigurierten Workspace-Roots.
- Pfad-Traversal und absolute Ausbrüche werden blockiert.
- Versteckte Pfade mit Komponenten wie `.private/` werden nicht gelesen oder
  angezeigt.
- Dateigrößenlimits verhindern versehentliche Vollimporte großer Dateien in
  Agent-Kontexte.
- `context_files:` in den Chat-Regeln unterliegt denselben Grenzen wie
  `@workspace/` und `@read()`: nur Dateien im Workspace, keine versteckten
  Pfade, Agent-Leselimit.
- `POST /restore` stellt nur Backups aus dem Backup-Verzeichnis wieder her
  (Dateiname, keine Pfade) und leert den Workspace nur nach ausdrücklicher
  Bestätigung. ZIP-Inhalte werden auf Pfad-Traversal, Symlinks und Größe
  geprüft; vor jedem Restore entsteht ein automatisches Backup.

## Provider

- Echte Provider-Calls laufen nur, wenn ein Agent mit passendem Provider, Modell
  und Key konfiguriert ist.
- Tests und CI verwenden Mocks, Fakes oder lokale In-Memory-Komponenten.
- Lokale Ollama-Modelle können ohne API-Key betrieben werden.
- Provider-Fehler liefern `429` (Rate-Limit), `504` (Timeout) oder `502`
  (nicht erreichbar, sonstige Fehler).
- Custom-Provider-URLs werden gegen SSRF-Risiken geprüft. Private,
  reservierte, Loopback- und Link-Local-Ziele werden blockiert; DNS-Auflösung
  auf solche Ziele wird ebenfalls abgelehnt. Localhost ist nur für explizite
  lokale Provider wie Ollama erlaubt.

## CI-Prüfungen

- `pip-audit` prüft alle installierten Abhängigkeiten auf bekannte
  Schwachstellen, `bandit` den Quellcode (ab Schweregrad „medium“). Ausnahmen
  stehen als `# nosec <ID>` mit Begründung direkt im Code.
- Der Job `ui-browser` lädt die UI in Chromium und prüft XSS-Schutz, CSP und
  Token-Login; `tests/ui/test_html_sinks.py` lehnt neue `innerHTML`-Stellen
  ohne `// safe-html:`-Begründung ab.
- Alle GitHub Actions sind auf Commit-SHAs gepinnt (Version als Kommentar).
  Updates erfolgen bewusst: neue SHA per `git ls-remote --tags` ermitteln und
  Kommentar mitpflegen.

## Release-Artefakte

Der CI-Job `build` (`.github/workflows/ci.yml`) baut Wheel und Source
Distribution bei jedem Push auf `main` und jedem Pull Request und prüft sie auf
verbotene Inhalte:

- keine Workspace-Daten
- keine Datenbanken
- keine Secret-Key-Dateien
- keine Logs
- keine Python-Caches
- keine alten DSGVO-/Legal-Pfade

Siehe auch: [Release Notes v0.2.1](release-notes-v0.2.1.md) und [v0.2.0](release-notes-v0.2.0.md).
