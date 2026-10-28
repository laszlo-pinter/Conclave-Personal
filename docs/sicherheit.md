# Sicherheit Für Conclave Personal

Conclave Personal ist als lokales Werkzeug für einzelne Nutzer gedacht. Die
lokale API ist ein technischer Betriebsmodus, kein öffentliches Internet-
Interface.

## Lokale API

- Standard-Host ist `127.0.0.1`.
- Die API verlangt immer ein Token. Ist `CONCLAVE_API_KEY` nicht gesetzt,
  erzeugt der Server beim ersten Start ein zufälliges Token und legt es in
  `api.token` im Konfigurationsverzeichnis ab (Linux `0600`, Windows ACL nur
  für den aktuellen Benutzer). CLI-Werkzeuge (`conclave web`, `conclave-watch`)
  lesen es von dort, wenn `CONCLAVE_API_KEY` leer ist. Agenten bekommen ein
  eigenes Token, siehe [Mensch- und Agent-Zugang](#mensch--und-agent-zugang).
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

## Mensch- und Agent-Zugang

Seit v0.5.0 unterscheidet Conclave am **Token**, wer anfragt. Angaben in der
Anfrage spielen dafür keine Rolle.

- **Mensch-Token:** `CONCLAVE_API_KEY` bzw. `api.token`. Gilt für die UI, die
  REST-API und die CLI. Neue Tokens beginnen mit `cvh_`; ein älteres
  `api.token` ohne Präfix bleibt gültig und zählt als Mensch.
- **Agent-Token:** `CONCLAVE_AGENT_KEY` bzw. `agent.token` (neben `api.token`,
  gleiche Dateirechte), Präfix `cva_`. Der MCP-Server liest nur dieses Token,
  nie `api.token`. Ist es gleich dem Mensch-Token, gibt es keinen
  Agent-Zugang.
- **Rolle prüfen:** `GET /auth/whoami` liefert `{"role": "human"|"agent"}`.
  Bekommt der MCP-Server `human`, schreibt er eine Warnung nach stderr.
- **Rechte des Agent-Zugangs:** nur die Routen, die die MCP-Tools brauchen
  (Liste in `api/access.py`); alles andere ergibt `403`
  `{"type": "HumanOnly"}`. Neue Routen sind für Agenten gesperrt, bis sie
  bewusst freigegeben werden. Agenten dürfen nicht löschen, keine Einstellungen,
  Agents, Backups oder Logs sehen oder ändern, keine Consultations wiederholen
  und nur Participants vom Typ `model` anlegen.
- **Herkunft:** Nachrichten über `POST /conversations/<id>/messages` tragen
  `origin: human|agent` aus dem Token (UI: „über Agent“). Ältere Nachrichten
  und Wege ohne Token (CLI) haben `origin: null` (unbekannt). Für die Modelle
  bleiben Agent-Nachrichten normale User-Nachrichten.
- **Consultations:** Der Kanal (`human`/`agent`) kommt aus dem Token; `channel`
  im Body ergibt `400`. Tickets „nur für Menschen“ lehnen API und Worker für
  alles außer `human` ab, über MCP wie über direkte REST-Aufrufe.

### Grenze: gleicher Betriebssystem-Benutzer

Agenten wie Claude Code laufen unter demselben Benutzer wie Conclave. Ein Agent
mit Shell kann deshalb jede Datei lesen, die Conclave lesen kann, auch
`api.token`, und damit den Mensch-Zugang nutzen, ebenso über Befehle, die das
Token selbst lesen (z. B. `conclave token show --reveal`). Getrennte Tokens
allein sind also **keine harte Grenze**. Sie schützen vor Agenten, die den
vorgesehenen Weg über MCP gehen, und vor dem bequemen Umweg. Eine harte Grenze
entsteht erst mit einer Sperre im Agent-Host; dafür muss der MCP-Server
`api.token` nicht mehr lesen.

Claude Desktop ohne Dateisystem-Zugriff (kein Dateisystem-MCP) erreicht
Conclave nur über die MCP-Tools und damit nur mit dem Agent-Zugang.

**Beispiel Claude Code** (Benutzereinstellungen `~/.claude/settings.json`,
geprüft gegen die Claude-Code-Doku zu Berechtigungen und Sandbox, Stand
Oktober 2026):

```json
{
  "permissions": {
    "deny": [
      "Read(~/AppData/Roaming/Conclave/api.token)",
      "Read(~/AppData/Roaming/Conclave/secret.key)",
      "Read(~/.config/conclave/api.token)",
      "Read(~/.config/conclave/secret.key)"
    ]
  }
}
```

- `~/` steht für das Benutzerverzeichnis; absolute Pfade beginnen mit `//`
  (unter Windows z. B. `//c/Users/<name>/...`). Die Zeilen für Windows
  (`%APPDATA%\Conclave`) und Linux/macOS (`~/.config/conclave`) dürfen beide
  stehen bleiben. Mit `CONCLAVE_API_TOKEN_FILE` gilt der dort gesetzte Pfad.
- `secret.key` gehört dazu: Mit ihm und der Datenbank ließen sich die
  gespeicherten Provider-Keys entschlüsseln.
- `Read`-Deny-Regeln gelten für die Datei-Tools von Claude Code und für
  Shell-Befehle, die Claude Code als Dateizugriff erkennt (`cat`, `head`,
  `sed` …). Sie gelten **nicht** für Programme, die Dateien selbst öffnen,
  etwa ein Python-Skript.
- Für eine Sperre, die alle Prozesse trifft, braucht es die Sandbox von Claude
  Code (`"sandbox": {"enabled": true}`; die `Read`-Deny-Regeln fließen dort ein,
  zusätzlich `sandbox.filesystem.denyRead`). Die Sandbox gibt es auf macOS,
  Linux und WSL2. **Unter nativem Windows laufen Befehle ohne Sandbox** – dort
  bleibt die Trennung eine Absprache plus Deny-Regel, keine harte Grenze.

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

## Consultations (Kanzo)

Consultations lesen ein Ticket aus Kanzo, geben es an Remote-Provider und
schreiben deren Antworten als Kommentar zurück. Ticket-Inhalte sind fremd und
werden als Daten behandelt:

- **Daten-Block:** Das Ticket steht im Prompt zwischen einer zufälligen
  Begrenzung, die der Ticket-Inhalt nicht vorzeitig schließen kann; die Regeln
  der Conversation sagen, dass sein Inhalt keine Anweisung ist.
- **Keine Wirkung über das Kommentieren hinaus:** Conclave ruft in Kanzo nur
  `get_task` und `add_comment` auf. Es setzt bei Consultations keine
  `@workspace/`-Dateien in den Prompt ein und führt `@save`/`@read` aus
  Reviewer-Antworten nicht aus – sonst könnte ein Ticket Workspace-Inhalte in
  einen Kommentar schleusen oder Dateien schreiben lassen.
- **Kennzeichnung:** Jeder Kommentar endet mit „Zweitmeinung von … über
  Conclave, nicht geprüft“ samt Provider, Modell und Kennung. Zeilen, die diese
  Schlusszeile nachahmen, werden aus der Antwort entfernt.
- **Kein Echtheitsnachweis:** Kanzo hat keine Anmeldung; Autor und
  Schlusszeile kann jeder schreiben. Die Kennzeichnung schützt vor
  Verwechslung, nicht vor Täuschung – Kommentaren mit dieser Kennzeichnung
  nicht mehr vertrauen als anderen Kommentaren.
- **Keine Rückkopplung:** Frühere Conclave-Kommentare fließen nur mit
  `include_previous: true` in neue Consultations ein, dann ausdrücklich als
  „frühere Modellausgabe“.
- **Tickets nur für Menschen:** Tickets mit Kanzos `human`-Markierung werden
  mit dem Agent-Token abgelehnt, über das MCP-Tool wie über einen direkten
  REST-Aufruf (`403 HumanOnlyTicket`); der Kanal kommt aus dem Token
  (seit v0.5.0). Die bekannte Lücke aus v0.4.0 ist damit geschlossen, soweit
  die [Grenze des gleichen Benutzers](#grenze-gleicher-betriebssystem-benutzer)
  reicht: Ein Agent, der `api.token` lesen kann, hat den Mensch-Zugang.
- **Feste Adresse:** Die Kanzo-Adresse steht nur in `config.toml`
  (`[kanzo] url`); die API nimmt keine Ziel-URL an (SSRF).
- **Grenzen:** Reviewer nur aus `[kanzo] reviewers` (wer Ticket-Inhalte sieht),
  höchstens `max_per_hour` Consultations pro Ticket und Stunde, Kommentare
  gekürzt. Nach einem Neustart werden Modelle nie automatisch erneut aufgerufen.
- **Datenabfluss:** Der Ticket-Inhalt geht an die Provider der Reviewer; die
  Antwort von `POST /consultations` und jeder Kommentar nennen sie. Mit
  `kanzo sync` landen die Kommentare im Git-Repository des Kanzo-Boards.
- Conclave spricht Kanzo (AGPL-3.0) nur über MCP an und enthält keinen Code
  aus Kanzo.

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

Siehe auch: [Release Notes v0.2.0](release-notes-v0.2.0.md) (Sicherheits-Release) und die folgenden Versionen im [Dokumentationsindex](index.md).
