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
- **Reviewer-Token:** `CONCLAVE_REVIEWER_KEY` bzw. `reviewer.token` (gleiche
  Dateirechte), Präfix `cvr_`, für den automatischen Reviewer. Es darf das
  Board lesen, kommentieren und als einziges den Review-Status setzen. Es darf
  keine Tickets anlegen, ändern, verschieben oder übernehmen und keine anderen
  Bereiche nutzen; für den Reviewer gelten alle Grenzen eines Agenten. Gleicht
  es einem anderen Token, gibt es keinen Reviewer-Zugang. Agenten, die Code
  schreiben, sollen es nicht lesen können: im Agent-Host sperren wie `api.token`.
- **Rolle prüfen:** `GET /auth/whoami` liefert `{"role": "human"|"agent"|"reviewer"}`.
  Bekommt der MCP-Server `human`, lehnt er jedes Tool ab (seit v0.6.2; nur mit
  `CONCLAVE_MCP_ALLOW_HUMAN=1` arbeitet er trotzdem, mit Warnung, für die
  Fehlersuche). `CONCLAVE_API_KEY` liest er nicht. Pfadteile in Tool-Aufrufen
  werden vollständig kodiert. `conclave-mcp --reviewer` arbeitet nur mit der
  Rolle `reviewer` und bietet nur drei Tools; der normale MCP-Server lehnt das
  Reviewer-Token ab und kennt das Review-Tool nicht.
- **Rechte des Agent-Zugangs:** nur die Routen, die die MCP-Tools brauchen
  (Liste in `api/access.py`); alles andere ergibt `403`
  `{"type": "HumanOnly"}`. Neue Routen sind für Agenten gesperrt, bis sie
  bewusst freigegeben werden. Agenten dürfen nicht löschen, keine Einstellungen,
  Agents, Backups oder Logs sehen oder ändern, keine Consultations wiederholen
  und nur Participants vom Typ `model` anlegen.
- **Grenzen für Agenten:** Tagesbudget in Tokens für alle Agenten und je
  Conversation, höchstens N gleichzeitige Modellläufe, eigenes Rate-Limit
  (`[limits]`, siehe [Konfiguration](referenz/konfiguration.md#grenzen-für-agenten)).
  Erschöpft → `429` mit Angabe, welche Grenze greift. Das Rate-Limit zählt nach
  Zugang und IP, Agenten bremsen die UI also nicht aus.
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
  stehen bleiben. Wer `CONCLAVE_API_TOKEN_FILE`, `CONCLAVE_SECRET_KEY_FILE`
  oder (Linux/macOS) `XDG_CONFIG_HOME` setzt, trägt die dort gesetzten Pfade ein.
- `secret.key` gehört dazu: Mit ihm und der Datenbank ließen sich die
  gespeicherten Provider-Keys entschlüsseln.

### Dateirechte

- `secret.key` und die Token-Dateien entstehen nur einmal, auch wenn zwei
  Prozesse gleichzeitig starten, und sind nur für den Benutzer lesbar.
  Hat eine vorhandene Datei weitere Rechte, entfernt Conclave sie beim Start
  und schreibt eine Warnung ins Log. Eine leere Token-Datei wird mit Warnung
  durch ein neues Token ersetzt.
- Windows: Datei und Konfigurationsverzeichnis (`%APPDATA%\Conclave`) haben
  ohne Vererbung nur Einträge für den Benutzer, SYSTEM und die Administratoren;
  andere Gruppen verlieren den Zugriff. Das Verzeichnis wird nur gehärtet, wenn
  `secret.key` darin liegt.
- Linux/macOS: Konfigurations-, Daten- und Log-Verzeichnis `0700`;
  Datenbank, Logs und Backups `0600`.

### Schlüsselwechsel

```powershell
conclave key rotate
```

Erzeugt einen neuen `secret.key` und verschlüsselt alle Daten in einer
Transaktion neu. Der alte Schlüssel bleibt als `secret.key.old-<Zeit>` neben
der Datei liegen; ältere Backups brauchen ihn, und sie gelten weiterhin als
eigene. Bricht der Wechsel ab, setzt ein erneuter Aufruf ihn fort; es geht
nichts verloren. Ein laufender Server wird danach neu gestartet. Kommt der
Schlüssel aus `CONCLAVE_SECRET_KEY`, wird er dort gewechselt.

Abgelöste Schlüssel gelten weiter: zum Entschlüsseln und für die Prüfung, ob
ein Backup ein eigenes ist. Wer wechselt, weil der alte Schlüssel in fremde
Hände gelangt sein könnte, nimmt `conclave key rotate --drop-old`. Danach
werden alle abgelösten Schlüssel gelöscht, und ältere Backups gelten als fremd.
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
  Code, Links). Skripte, Bilder, SVG, Formulare, `style`-, `id`-, `class`-
  und Event-Attribute werden entfernt; `class` bleibt nur als Sprachangabe
  `language-*` an `code`. Einzige Ausnahme sind GFM-Aufgabenlisten:
  `input` bleibt nur als deaktivierte Checkbox erhalten, andere Eingabefelder
  werden entfernt.
- Links sind nur mit `http(s)`, `mailto` oder `#` erlaubt. Externe Links
  öffnen mit `target="_blank"` und `rel="noopener noreferrer"`, Sprungmarken
  (`#…`) im selben Tab. Links, deren Fragment `token=` enthält, verlieren ihr
  Ziel.
- **Token in der UI:** Das Token liegt nur im `sessionStorage` des Tabs (bis
  v0.6.1 dauerhaft im `localStorage`; ein altes Token wird einmal übernommen
  und dort gelöscht). `conclave desktop` und `conclave web` übergeben es beim
  Start im URL-Fragment. Ein Token aus dem Fragment prüft die UI zuerst per
  `/auth/whoami`: Ein Mensch-Token in einem Tab ohne gespeichertes Token gilt
  sofort; ein Agent-Token, ein ungültiges Token oder ein Wechsel gegenüber dem
  gespeicherten Token gelten erst nach einer Rückfrage, die die Rolle nennt. Die Rolle
  des aktuellen Zugangs („Mensch“ oder „Agent“) steht in der Seitenleiste.
  `conclave web --url` hängt das Token nur an lokale Adressen, nie an einen
  fremden Host.
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
- Keys aus der Umgebung bzw. Konfiguration (`OPENAI_API_KEY` usw.) gehen nur
  an Host und Schema ihres Presets. Ein gespeicherter Agent-Key wird verworfen,
  wenn der Agent nach einer Änderung an einen anderen Host sendet und kein
  neuer Key eingegeben wird.
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
- Pfadkomponenten mit `:`, Windows-Gerätenamen (`CON`, `NUL`, `COM1` usw.,
  auch mit Endung), Punkt oder Leerzeichen am Ende, Steuerzeichen und
  8.3-Kurznamen (`NAME~1`) werden abgelehnt.
- Der Workspace darf Home-, Konfigurations-, Daten-, Log- und
  Backup-Verzeichnis nicht sein oder enthalten, ebenso keine Token-,
  Schlüssel- oder Datenbankdatei. Der Server startet mit einem solchen
  `CONCLAVE_WORKSPACE` nicht; `PUT /settings` lehnt ihn mit `400` ab.
  Token-, Schlüssel- und Datenbankdateien sind über den Workspace nie
  erreichbar.
- Agenten legen nur neue Dateien an; vorhandene Dateien überschreibt nur der
  Mensch (`403`). Unter `agents/` dürfen Agenten auch überschreiben.
  `conclave_notify.json` ist für Agenten gesperrt.
- Dateien werden über eine temporäre Datei geschrieben und dann ausgetauscht;
  bricht das Schreiben ab, bleibt die alte Datei erhalten.
- Dateigrößenlimits verhindern versehentliche Vollimporte großer Dateien in
  Agent-Kontexte.
- `context_files:` in den Chat-Regeln unterliegt denselben Grenzen wie
  `@workspace/` und `@read()`: nur Dateien im Workspace, keine versteckten
  Pfade, Agent-Leselimit.
- `@workspace/` wird nur in Nachrichten von Mensch und Agent eingesetzt, je Datei
  einmal (auch bei anderer Schreibweise des Pfads), höchstens 10 Dateien pro
  Nachricht und zusammen höchstens das Agent-Leselimit pro Prompt (neuere
  Nachrichten zuerst); jede Datei steht beim Speichern der Nachricht einmal als
  Tool-Event im Verlauf. Texte, deren Verweise nie eingesetzt werden (Tickets
  in Consultations), erzeugen keine solchen Einträge.
- `@read()` in Modellantworten ist standardmäßig aus und wird nur nach Freigabe
  durch den Menschen je Conversation ausgeführt, mit denselben Grenzen.
- Anfragen sind auf 10 MB begrenzt (`413 RequestTooLarge`), der Board-Import auf
  50 MB. Board-Felder haben Längengrenzen (Titel 300 Zeichen, Beschreibung und
  Kommentar 65.536 Zeichen, höchstens 50 Tags zu je 50 Zeichen).
- `POST /restore` stellt nur Backups aus dem Backup-Verzeichnis wieder her
  (Dateiname, keine Pfade) und leert den Workspace nur nach ausdrücklicher
  Bestätigung. ZIP-Inhalte werden auf Pfad-Traversal, Symlinks, Größe und
  Prüfsummen geprüft; vor jedem Restore entsteht ein automatisches Backup.
- Ein Restore ändert nichts, solange nicht das ganze Archiv geprüft und
  entpackt ist; die Datenbank kommt zuletzt. Backups enthalten keine verlinkten
  Inhalte (Symlinks, Junctions).
- Backups tragen eine Signatur, abgeleitet aus `secret.key`. Ein Backup ohne
  belegte eigene Herkunft wird erst nach Bestätigung eingespielt; vorher zeigt
  Conclave die Agents und Ziel-URLs aus dem Backup. Trigger und Views aus
  Backup-Datenbanken werden verworfen.

## Provider

- Echte Provider-Calls laufen nur, wenn ein Agent mit passendem Provider, Modell
  und Key konfiguriert ist.
- Tests und CI verwenden Mocks, Fakes oder lokale In-Memory-Komponenten.
- Lokale Ollama-Modelle können ohne API-Key betrieben werden.
- Provider-Fehler liefern `429` (Rate-Limit), `504` (Timeout) oder `502`
  (nicht erreichbar, sonstige Fehler).
- Ausgehende Verbindungen zu Providern sind auf öffentliche Adressen
  beschränkt. Conclave löst den Namen bei jeder Anfrage auf, prüft jede
  Adresse und verbindet sich mit der geprüften Adresse; Host-Header und
  TLS-Servername bleiben beim Namen. Nicht auflösbare Namen werden abgelehnt.
- Entfernte Provider nur über `https`. `localhost` ist nur für den lokalen
  Provider (Ollama) erlaubt, und nur auf dessen Port
  (`CONCLAVE_OLLAMA_PORT`, Standard `11434`). Ein Agent mit einer nicht mehr
  erlaubten URL wird beim Start übersprungen; sein Aufruf nennt den Grund.
- Provider-Keys stehen in Headern, nicht in der URL (Gemini:
  `x-goog-api-key`).
- Fehlermeldungen an Clients und im Log enthalten keine Provider-URLs und
  keine Keys. Unbekannte Fehler erscheinen nur mit ihrem Typ, Details stehen
  im Server-Log. Streams melden Fehler als `data: [ERROR] {"error": ..., "type": ...}`.

## Board

Das Board (seit v0.6.0, siehe [Mit dem Board arbeiten](mit-dem-board-arbeiten.md))
setzt seine Regeln am Token durch, nicht an Angaben in der Anfrage:

- **Herkunft:** Kommentare und Verlauf bekommen `origin` (`human`, `agent`,
  `system` für Conclave selbst, `null` für importierte) und `actor_id` vom
  Server. Felder wie `origin` oder `actor_id` im Body werden ignoriert bzw.
  bei Tickets mit `400` abgelehnt; ein `author_name` ist nur ein Anzeigename.
- **Freigabe-Recht** (heute: der Mensch): nach und aus der letzten Spalte
  schieben, löschen, Projekte verwalten, importieren. Mit dem Agent-Token
  ergibt das `403 HumanOnly`, ohne dass etwas geschrieben wird.
- **Priorität** (`rank`, Reihenfolge der ersten Spalte und von `next_task`)
  ändert nur der Mensch; Agenten bekommen für `index` und `rank` `403`.
- **Agenten** lesen erledigte Tickets und Tickets „nur für Menschen“ nur
  (erledigte dürfen sie kommentieren), dürfen die Markierung „nur für
  Menschen“ setzen, aber nicht entfernen, und bekommen solche Tickets nie über
  `next_task`. Aus der ersten Spalte kommen sie nur über `next_task` heraus
  (oberstes oder bestimmtes Ticket), sodass jede Übernahme im Verlauf steht.
  Die Prüfungen laufen im selben Schreibvorgang wie die Änderung (keine Lücke
  zwischen Prüfen und Schreiben); `next_task` vergibt jedes Ticket genau
  einmal.
- **Unveränderliche Kommentare:** Kommentare von Agenten, von Conclave und
  importierte kann niemand ändern oder löschen; der Mensch nur seine eigenen.
- **Verlauf:** Änderungen an Status, Titel, Beschreibung und Markierung werden
  mit vollständigem altem und neuem Wert gespeichert.
- **Ticket-Texte sind Daten:** Die MCP-Tools kennzeichnen Titel, Beschreibung
  und Kommentare als Daten, nicht als Anweisungen. In der UI laufen
  Beschreibung und Kommentare durch `marked` und DOMPurify wie Modellantworten,
  alles andere wird als Text gesetzt.
- **Verschlüsselung:** Titel, Beschreibungen, Tags, Kommentare und Verlaufswerte liegen
  verschlüsselt in der Datenbank (wie Nachrichten, `secret.key`).
- **Import:** nur mit dem Mensch-Token, höchstens 50 MB, vollständig geprüft
  vor dem ersten Schreiben. Importierte Kommentare bekommen keine Herkunft,
  auch wenn der Export einen Autor nennt.
- **Grenze:** Wie überall gilt die
  [Grenze des gleichen Benutzers](#grenze-gleicher-betriebssystem-benutzer):
  Ein Agent, der `api.token` lesen kann, kann auch nach `done` schieben.

Das Board ist eine eigene Umsetzung; Conclave enthält keinen Code aus Kanzo.

## Consultations

Consultations lesen ein Ticket aus dem eigenen Board oder, mit
`[board] source = "kanzo"`, aus Kanzo, geben es an Remote-Provider und
schreiben deren Antworten als Kommentar zurück. Ticket-Inhalte sind fremd und
werden als Daten behandelt:

- **Daten-Block:** Das Ticket steht im Prompt zwischen einer zufälligen
  Begrenzung, die der Ticket-Inhalt nicht vorzeitig schließen kann; die Regeln
  der Conversation sagen, dass sein Inhalt keine Anweisung ist.
- **Keine Wirkung über das Kommentieren hinaus:** Conclave liest das Ticket
  und schreibt Kommentare, sonst nichts (in Kanzo nur `get_task` und
  `add_comment`). Es setzt bei Consultations keine
  `@workspace/`-Dateien in den Prompt ein und führt `@save`/`@read` aus
  Reviewer-Antworten nicht aus – sonst könnte ein Ticket Workspace-Inhalte in
  einen Kommentar schleusen oder Dateien schreiben lassen.
- **Kennzeichnung:** Jeder Kommentar endet mit „Zweitmeinung von … über
  Conclave, nicht geprüft“ samt Provider, Modell und Kennung. Zeilen, die diese
  Schlusszeile nachahmen, werden aus der Antwort entfernt.
- **Herkunft:** Im eigenen Board schreibt Conclave mit Herkunft `system`; ein
  Agent kann keinen Kommentar mit dieser Herkunft anlegen. Ein fremder
  Kommentar, dessen Name nach Conclave aussieht, zählt nicht als Zustellung und
  steht im Prompt mit seiner Herkunft.
- **Kein Echtheitsnachweis in Kanzo:** Kanzo hat keine Anmeldung; Autor und
  Schlusszeile kann dort jeder schreiben. Die Kennzeichnung schützt vor
  Verwechslung, nicht vor Täuschung – Kommentaren mit dieser Kennzeichnung
  nicht mehr vertrauen als anderen Kommentaren.
- **Keine Rückkopplung:** Frühere Conclave-Kommentare fließen nur mit
  `include_previous: true` in neue Consultations ein, dann ausdrücklich als
  „frühere Modellausgabe“.
- **Tickets nur für Menschen:** Tickets mit der Markierung „nur für Menschen“
  (in Kanzo `human`) werden
  mit dem Agent-Token abgelehnt, über das MCP-Tool wie über einen direkten
  REST-Aufruf (`403 HumanOnlyTicket`); der Kanal kommt aus dem Token
  (seit v0.5.0). Die bekannte Lücke aus v0.4.0 ist damit geschlossen, soweit
  die [Grenze des gleichen Benutzers](#grenze-gleicher-betriebssystem-benutzer)
  reicht: Ein Agent, der `api.token` lesen kann, hat den Mensch-Zugang.
- **Feste Adresse:** Die Kanzo-Adresse steht nur in `config.toml`
  (`[kanzo] url`); die API nimmt keine Ziel-URL an (SSRF).
- **Grenzen:** Reviewer nur aus `[consultations] reviewers` (wer Ticket-Inhalte sieht),
  höchstens `max_per_hour` Consultations pro Ticket und Stunde, je Zugang und
  für die normalisierte Referenz, atomar gezählt; Kommentare gekürzt. Nach einem
  Neustart werden Modelle nie automatisch erneut aufgerufen.
- **Erneute Prüfung:** Vor dem Zustellen prüft Conclave noch einmal „nur für
  Menschen“; ein inzwischen markiertes Ticket bekommt keinen Kommentar aus einem
  Agent-Auftrag.
- **Datenabfluss:** Der Ticket-Inhalt geht an die Provider der Reviewer; die
  Antwort von `POST /consultations` und jeder Kommentar nennen sie. Bei Kanzo
  landen die Kommentare mit `kanzo sync` im Git-Repository des Kanzo-Boards.
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
- Checkouts speichern keine Git-Zugangsdaten (`persist-credentials: false`).

## Release-Artefakte

Der CI-Job `build` (`.github/workflows/ci.yml`) baut Wheel und Source
Distribution bei jedem Push auf `main` und jedem Pull Request.
`scripts/release/check_dist.py` prüft sie auf Name und Version, Pflichtdateien
und verbotene Inhalte:

- keine Workspace-Daten
- keine Datenbanken
- keine Secret-Key- und Token-Dateien
- keine Logs und `.env`-Dateien
- keine Python-Caches
- keine alten DSGVO-/Legal-Pfade

Build-Werkzeuge (`pip`, `build`, `setuptools`, `wheel` und ihre
Abhängigkeiten) stehen mit Hashes in `requirements/release-tools.txt`. Gebaut
wird ohne Isolation mit genau diesen Werkzeugen.

## Veröffentlichen

`.github/workflows/publish.yml` veröffentlicht nur unter diesen Bedingungen:

1. Der Lauf gehört zu einem Tag `v<Version>`, und die Version passt zu
   `pyproject.toml` (`scripts/release/check_version.py`). Ohne Tag oder bei
   Abweichung bricht der Lauf ab.
2. Die volle CI ist grün: Tests unter Linux und Windows, UI-Tests, `pip-audit`
   und `bandit`, PostgreSQL, Paketprüfung. Im Release-Lauf ohne pip-Cache.
3. Die Pakete werden mit den gepinnten Werkzeugen neu gebaut und geprüft.
4. Der Job `publish` läuft im GitHub-Environment `pypi`. Dort ist eine Freigabe
   durch den Maintainer Pflicht (Einstellung in GitHub, siehe unten).

Einrichtung des Environments in GitHub: Repository → Settings → Environments
→ `pypi` → „Required reviewers“ aktivieren und den Maintainer eintragen;
„Prevent self-review“ nicht setzen, wenn nur eine Person freigibt. Unter
„Deployment branches and tags“ „Selected branches and tags“ wählen und die
Regel `v*` (Typ Tag) anlegen. Bei PyPI ist das Projekt per Trusted Publishing
an diesen Workflow und dieses Environment gebunden.

Siehe auch: [Release Notes v0.2.0](release-notes-v0.2.0.md) (Sicherheits-Release) und die folgenden Versionen im [Dokumentationsindex](index.md).
