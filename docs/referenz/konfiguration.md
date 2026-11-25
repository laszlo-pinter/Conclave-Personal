# Konfiguration

Alle Konfiguration über Umgebungsvariablen. Die TOML-Config ist nur für
wenige Werte ein Fallback (siehe [TOML-Config](#toml-config)).

## Priorität

1. Umgebungsvariable (höchste)
2. TOML-Config im plattformabhängigen Config-Verzeichnis
3. Default-Werte

## Server

| Variable | Default | Beschreibung |
|----------|---------|-------------|
| CONCLAVE_MODE | development | `development` (Token automatisch aus `api.token`) / `production` (`CONCLAVE_API_KEY` und Secret-Key Pflicht) |
| CONCLAVE_HOST | 127.0.0.1 | Bind-Adresse |
| CONCLAVE_PORT | 8000 | Server-Port |
| CONCLAVE_LOG_LEVEL | INFO | DEBUG / INFO / WARNING / ERROR |
| CONCLAVE_DEBUG | — | `1` oder `true` aktiviert den Debug-Modus (wie `--debug`). Abgelehnt im Production-Modus und bei Nicht-Loopback-`CONCLAVE_HOST` |
| CONCLAVE_RATE_LIMIT | 120 per minute | Anfragen je Route, Zugang (Mensch, Agent) und Client-IP, Syntax von flask-limiter (`120/minute; 2000/hour`), `off`, `none`, `0` oder leer schalten ab. Auch als `[server] rate_limit` in der TOML-Config oder in der UI unter Settings (wirkt sofort); die Umgebungsvariable hat Vorrang und sperrt die UI-Änderung |
| CONCLAVE_CONFIG_FILE | plattformabhängig | Pfad der `config.toml` (z. B. getrennt für Testinstanzen) |
| CONCLAVE_LOG_DIR | plattformabhängig | Verzeichnis für `conclave-server.log` (z. B. getrennt für Testinstanzen) |
| CONCLAVE_SERVER_THREADS | 16 | Threads des WSGI-Servers (waitress). Laufende Streams belegen je einen Thread |
| CONCLAVE_ASSET_DIR | — | Alternatives Verzeichnis für die UI-Assets (`conclave-ui.html` und `static/`); ohne Wert die mitgelieferten Assets |
| CONCLAVE_API_URL | http://localhost:8000 | URL der Conclave-API für die Programme, die mit dem Server sprechen: `conclave-mcp`, `conclave board wait` (Standard von `--url`) und der Reviewer (Standard von `conclave_url`, dort `http://127.0.0.1:8000`). Der Server selbst liest sie nicht |

## Datenbank

| Variable | Default | Beschreibung |
|----------|---------|-------------|
| CONCLAVE_DB_PROVIDER | sqlite | `sqlite` oder `postgres`. `postgres` wirkt nur für `conclave server`, `conclave desktop` und `conclave-api`; alle anderen CLI-Kommandos nutzen immer SQLite |
| CONCLAVE_DB_PATH | plattformabhängig | SQLite-Dateipfad |
| CONCLAVE_DB_DSN | — | PostgreSQL Connection String |
| CONCLAVE_DB_POOL_SIZE | 10 | Höchstzahl gleichzeitiger PostgreSQL-Verbindungen des Servers (Anfragen und Worker). Ist keine frei, wartet eine Anfrage bis zu 30 Sekunden |

Der eigenständige Board-Server aus dem Board-Paket (`conclave-board-server`) liest eigene
Variablen mit dem Präfix `CONCLAVE_BOARD_` (`CONCLAVE_BOARD_DSN`, `CONCLAVE_BOARD_POOL_SIZE`,
`CONCLAVE_BOARD_ALLOWED_HOSTS`, `CONCLAVE_BOARD_TRUSTED_PROXIES`); sie gelten nicht für Conclave
Personal. Beschrieben sind sie im
[README des Board-Pakets](../../packages/board/README.md).

## Backup

| Variable | Default | Beschreibung |
|----------|---------|-------------|
| CONCLAVE_BACKUP_DIR | — | Backup-Verzeichnis. Ohne Wert: API bei SQLite `backups/` neben der DB, sonst (PostgreSQL und CLI) `<Elternordner des Workspace>/backups` |
| CONCLAVE_RESTORE_MAX_BYTES | 536870912 | Max. Gesamtgröße (unkomprimiert) der Dateien in einem Restore-ZIP |

## Sicherheit

| Variable | Default | Beschreibung |
|----------|---------|-------------|
| CONCLAVE_SECRET_KEY | — | Fernet-Key (base64). Nicht ändern nach Erstanlage! |
| CONCLAVE_SECRET_KEY_FILE | plattformabhängig | Datei für lokalen Fernet-Key |
| CONCLAVE_API_KEY | — | Mensch-Token (Bearer) für UI, REST-API und CLI. Leer: Token aus `CONCLAVE_API_TOKEN_FILE`, beim ersten Serverstart erzeugt. Nie in eine MCP- oder Agent-Konfiguration eintragen |
| CONCLAVE_API_TOKEN_FILE | `<config_dir>/api.token` | Datei für das automatisch erzeugte Mensch-Token (nur Benutzer lesbar) |
| CONCLAVE_AGENT_KEY | — | Agent-Token für den MCP-Server und andere Agenten (eingeschränkte Rechte). Leer: Token aus `CONCLAVE_AGENT_TOKEN_FILE`, beim ersten Serverstart erzeugt. Gleich dem Mensch-Token: kein Agent-Zugang |
| CONCLAVE_AGENT_TOKEN_FILE | `<config_dir>/agent.token` | Datei für das automatisch erzeugte Agent-Token (nur Benutzer lesbar) |
| CONCLAVE_REVIEWER_KEY | — | Reviewer-Token für den automatischen Reviewer (`conclave-mcp --reviewer`). Leer: Token aus `CONCLAVE_REVIEWER_TOKEN_FILE`, beim ersten Serverstart erzeugt. Gleich einem anderen Token: kein Reviewer-Zugang |
| CONCLAVE_REVIEWER_TOKEN_FILE | `<config_dir>/reviewer.token` | Datei für das automatisch erzeugte Reviewer-Token (nur Benutzer lesbar) |
| CONCLAVE_MCP_ROLE | `agent` | `reviewer` startet `conclave-mcp` als Reviewer-Server (wie `--reviewer`) |
| CONCLAVE_MCP_ALLOW_HUMAN | — | `1`: `conclave-mcp` arbeitet auch mit dem Mensch-Token, statt es abzulehnen (mit Warnung auf stderr; Agenten haben dann vollen Zugang). Nur zur Fehlersuche, siehe [Sicherheit](../sicherheit.md#mensch--und-agent-zugang) |
| CONCLAVE_ALLOWED_HOSTS | — | Zusätzlich erlaubte `Host`-Header (kommasepariert, optional mit Port). `localhost`, `127.0.0.1`, `[::1]` sind immer erlaubt. Pflicht bei Nicht-Loopback-`CONCLAVE_HOST` |
| CONCLAVE_ALLOWED_ORIGINS | `http://localhost,http://localhost:8000,http://127.0.0.1,http://127.0.0.1:8000` | CORS-Allowlist (kommasepariert, exakte Origins) |

Neue Tokens beginnen mit `cvh_` (Mensch), `cva_` (Agent) bzw. `cvr_` (Reviewer); die Rolle
ergibt sich aber allein daraus, in welcher Variable bzw. Datei das Token steht.
Ein älteres `api.token` ohne Präfix bleibt gültig. Pfad und
MCP-Einrichtungsbefehl zeigt `conclave token show --agent`.

`CONCLAVE_AGENT_KEY` und `CONCLAVE_AGENT_TOKEN_FILE` sind reserviert und werden
nicht als Agent-Definition `CONCLAVE_AGENT_<ID>` gelesen (bis v0.4.0 entstand
daraus ein Agent mit der ID `KEY` bzw. `TOKEN_FILE`).

## Provider API-Keys (Fallback)

Werte werden beim Einlesen bereinigt: umschließende Leerzeichen und
Anführungszeichen (`"sk-..."`) werden entfernt, im Log erscheint dann einmalig
eine Warnung mit dem Variablennamen. Unter Windows den Namen ohne `$env:` und
den Wert ohne Anführungszeichen eintragen.

| Variable | Beschreibung |
|----------|-------------|
| ANTHROPIC_API_KEY | Fallback wenn Agent keinen eigenen Key hat |
| OPENAI_API_KEY | Fallback wenn Agent keinen eigenen Key hat |
| GEMINI_API_KEY | Fallback wenn Agent keinen eigenen Key hat |
| MISTRAL_API_KEY | Fallback für Mistral-Presets |
| DEEPSEEK_API_KEY | Fallback für DeepSeek-Presets |
| DASHSCOPE_API_KEY | Fallback für Qwen/DashScope-Presets |

Ein Fallback-Key geht nur an Host und Schema seines Presets (z. B.
`OPENAI_API_KEY` nur an `https://api.openai.com`). Hat ein Agent eine eigene
Adresse auf einem anderen Host, etwa ein Gateway, bekommt er keinen
Fallback-Key; der Key wird dann beim Agent eingetragen. Sendet ein Agent nach
einer Änderung (Adresse, Preset oder Provider) an einen anderen Host, verwirft
Conclave den gespeicherten Key, außer er wird neu eingegeben.

## Agent-Seeding

Beim Start von `conclave server`, `conclave desktop` und `conclave-api` werden
Agents aus Umgebungsvariablen angelegt, sofern es noch keinen Agent mit dieser
ID gibt (bestehende Agents werden nicht verändert):

| Variable | Beschreibung |
|----------|-------------|
| CONCLAVE_AGENT_<ID> | `<provider>:<model>[:<preset>[:<name>]]`, Name ohne Angabe = ID |
| CONCLAVE_AGENT_<ID>_API_URL | Optionale API-URL des Agenten |
| CONCLAVE_AGENT_<ID>_API_KEY | Optionaler API-Key; ohne Wert wird bei gesetztem Preset dessen Key-Variable (z. B. `DEEPSEEK_API_KEY`) gelesen |

## Workspace + Token

| Variable | Default | Beschreibung |
|----------|---------|-------------|
| CONCLAVE_WORKSPACE | plattformabhängig | Lokaler Workspace-Pfad. Ohne Wert gilt der Plattformdefault (siehe unten) für alle Einstiegspunkte (CLI-Kommandos, Server, Desktop, `conclave-api`) |
| CONCLAVE_WORKSPACE_AUTOLIST | — | Gesetzt (nicht leer): Liste aller Workspace-Dateien im System-Prompt aller Agenten. Standardmäßig aus |
| CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES | 524288 | Max. Dateigröße für `@workspace/...`, `@read(...)` und `context_files:` in Agent-Kontexten |
| CONCLAVE_WORKSPACE_UI_READ_LIMIT_BYTES | 2097152 | Max. Dateigröße für UI/API/CLI-Lesezugriffe |
| CONCLAVE_WORKSPACE_WRITE_LIMIT_BYTES | 524288 | Max. Größe für Workspace-Schreibzugriffe und `@save(...)` |
| CONCLAVE_OLLAMA_PORT | 11434 | Port des lokalen Providers (Ollama). `localhost` ist nur für den Provider `ollama` und nur auf diesem Port erlaubt; entfernte Provider brauchen `https` |
| CONCLAVE_MAX_MESSAGES | 25 | Max. Nachrichten pro Provider-Call für Preset-Agents (UniversalAdapter), wenn am Agenten kein eigenes Limit gesetzt ist. Die nativen Anthropic-/OpenAI-Adapter kürzen nur mit Agent-Limit. Pro Agent: Feld `max_messages` (leer = dieser Default, `0` = keine Kürzung) |

Versteckte Pfade, also Komponenten mit führendem Punkt wie `.private/`,
werden in UI/API/CLI, Agent-Directives und `context_files:` nicht angezeigt
oder gelesen.

`context_files:` ist eine Zeile in den Chat-Regeln einer Conversation, z. B.
`context_files: notizen.md, docs/plan.md`. Alle Agenten (Preset-Agents und
native Anthropic-/OpenAI-Agenten) bekommen den Inhalt dieser Dateien in den
System-Prompt. Geladen werden nur
Dateien innerhalb des Workspace, nicht versteckt und höchstens
`CONCLAVE_WORKSPACE_AGENT_READ_LIMIT_BYTES` groß; abgelehnte Einträge werden
als Warnung geloggt.

## Plattformpfade

Windows:

| Zweck | Default |
|-------|---------|
| Config | `%APPDATA%\Conclave` |
| Datenbank | `%LOCALAPPDATA%\Conclave\conclave.db` |
| Logs | `%LOCALAPPDATA%\Conclave\logs` |
| Workspace | `%USERPROFILE%\Conclave\workspace` |
| Secret-Key-Datei | `%APPDATA%\Conclave\secret.key` |

Linux:

| Zweck | Default |
|-------|---------|
| Config | `$XDG_CONFIG_HOME/conclave` oder `~/.config/conclave` |
| Datenbank | `$XDG_DATA_HOME/conclave/conclave.db` oder `~/.local/share/conclave/conclave.db` |
| Logs | `$XDG_STATE_HOME/conclave/logs` oder `~/.local/state/conclave/logs` |
| Workspace | `~/Conclave/workspace` |
| Secret-Key-Datei | `$XDG_CONFIG_HOME/conclave/secret.key` oder `~/.config/conclave/secret.key` |

## TOML-Config

Default-Pfade:

- Windows: `%APPDATA%\Conclave\config.toml`
- Linux: `$XDG_CONFIG_HOME/conclave/config.toml` oder
  `~/.config/conclave/config.toml`
- Abweichender Pfad über `CONCLAVE_CONFIG_FILE`.

Aus der TOML-Datei werden nur diese Schlüssel gelesen; alles andere ist nur
über Umgebungsvariablen einstellbar:

- `[database]` `provider`, `path` (Alias `db_path`) und `dsn`. Statt
  `[database]` wird auch die ältere Sektion `[conclave]` akzeptiert.
  Vorrang hat `CONCLAVE_DB_PATH`, dann `path`, dann der Plattformdefault
  (für alle Einstiegspunkte).
- `[server]` `rate_limit`
- `[ui]` `mode` (siehe [Oberfläche](#oberfläche))
- `[reviewer]` und `[reviewer.projects]` (siehe [Reviewer](#reviewer))
- `[limits]` Grenzen für Agenten (siehe unten)
- `[board]` `statuses`, `source` (Board und Quelle der Consultations, siehe
  unten)
- `[consultations]` `reviewers`, `max_per_hour`, `comment_max_chars`
  (siehe unten)
- `[kanzo]` `url` (nur für ein externes Kanzo)
- `[participants]` (Altbestand, siehe unten)

```toml
[database]
provider = "sqlite"
# Optional. Ohne diesen Wert nutzt Conclave den plattformabhängigen Default:
# Windows: %LOCALAPPDATA%\Conclave\conclave.db
# Linux:   $XDG_DATA_HOME/conclave/conclave.db
path = "/pfad/zur/conclave.db"
# dsn = "host=localhost dbname=conclave user=conclave password=..."

[server]
# Anfragen je Route, Zugang und Client-IP (flask-limiter-Syntax). Mehrere Grenzen mit ";"
# trennen, "off" schaltet die Begrenzung ab. Wirksam nach Neustart des Servers;
# CONCLAVE_RATE_LIMIT hat Vorrang.
rate_limit = "120 per minute"

[ui]
# "studio" (Standard) oder "board": nur die Board-Seite, ohne Studio
mode = "studio"

[board]
# Spalten des Boards: neue Tickets in die erste, die letzte gilt als erledigt
statuses = ["todo", "doing", "review", "done"]
# Woher Consultations Tickets lesen: "internal" (eigenes Board) oder "kanzo"
source = "internal"

[consultations]
# Zweitmeinungen zu Tickets: wer Ticket-Inhalte sieht, Grenzen
reviewers = ["gpt", "claude"]
max_per_hour = 3
comment_max_chars = 2000

[kanzo]
# nur mit [board] source = "kanzo"
url = "http://localhost:4242/mcp"

[participants.claude]
# Altbestand: wird einmalig als Agent in die DB übernommen
name = "Claude"
provider = "anthropic"
model = "claude-sonnet-5"
system_prompt = ""
```

`[participants]` ist ein Altbestand: Jeder Eintrag `[participants.<id>]` wird
beim Start einmalig als Agent in die Datenbank übernommen, falls es noch
keinen Agent mit dieser ID gibt. Gelesen werden nur `name`, `provider`,
`model` und `system_prompt`; API-Keys kommen nicht aus der TOML-Datei.
Danach werden Agents über UI, API oder CLI verwaltet.

## Board

Das eigene Board (siehe [Mit dem Board arbeiten](../mit-dem-board-arbeiten.md)).

| Schlüssel | Default | Bedeutung |
|---|---|---|
| `statuses` | `["todo", "doing", "review", "done"]` | Spalten in dieser Reihenfolge, mindestens zwei, ohne Doppelte; Namen aus Kleinbuchstaben, Ziffern und `-` (höchstens 40 Zeichen). Neue Tickets landen in der ersten, die letzte gilt als erledigt (nur der Mensch schiebt dorthin). `next_task` schiebt von der ersten in die zweite; bei nur zwei Spalten ist das ein Schritt nach „erledigt“ und deshalb nur mit Freigabe-Recht möglich. |
| `source` | `internal`, oder `kanzo`, wenn `[kanzo] url` bzw. `CONCLAVE_KANZO_URL` gesetzt ist | Woher Consultations Tickets lesen: `internal` (eigenes Board, Kommentare mit Herkunft `system`) oder `kanzo` (externes Kanzo unter `[kanzo] url`). |

Spalten nachträglich umzubenennen ändert gespeicherte Tickets nicht: Tickets
mit einem Status, der nicht mehr in `statuses` steht, zeigt die UI nicht an,
bis die Spalte wieder da ist. Ausnahme ist die letzte Spalte: Fehlt ihr alter
Name in `statuses`, verschiebt Conclave beim Start deren Tickets in die neue
letzte Spalte, damit sie erledigt bleiben (Verlaufseintrag mit Herkunft
`system`). Kommt nur eine Spalte hinter der alten letzten dazu, bleiben die
Tickets, wo sie sind.

Das Board braucht SQLite ab Version 3.35 (bei Python 3.11 und 3.12 üblich)
oder PostgreSQL.

## Oberfläche

Abschnitt `[ui]`: welche Oberfläche der Browser unter `/` sieht.

| Schlüssel | Default | Bedeutung |
|---|---|---|
| `mode` | `"studio"` | `"studio"`: das Studio wie bisher, das Board ist ein Reiter darin. `"board"`: nur das Board. `/` leitet auf `/ui/board` weiter, das Studio (Seite, Skripte, Stile) antwortet mit 404 und dem Hinweis „Board-Modus“. `conclave desktop` und `conclave web` öffnen dann direkt die Board-Seite. |

- Die Board-Seite unter `/ui/board` gibt es in beiden Modi. Sie zeigt dieselbe Ansicht wie der
  Board-Reiter des Studios und meldet sich mit dem Token des Tabs an, wie das Studio.
- Die API ist in beiden Modi gleich. Agenten mit `conclave-mcp`, Consultations, der Reviewer und
  `/api-docs` arbeiten im Board-Modus weiter. Der Modus ändert nur die Oberfläche und ist keine
  Zugriffsgrenze; die regelt das Token.
- Ein anderer Wert als `"studio"` oder `"board"` bricht den Start mit einer Meldung ab, die
  `config.toml` nennt. Der Modus gilt nach einem Neustart des Servers.

## Reviewer

Der automatische Reviewer `conclave-reviewer` (siehe
[Mit dem Board arbeiten](../mit-dem-board-arbeiten.md)). Steht der Abschnitt
`[reviewer]` in der `config.toml`, startet `conclave desktop` den Reviewer und
beendet ihn mit sich selbst. `conclave server` startet keinen.

```toml
[reviewer]
poll_seconds = 30
[reviewer.projects]
conclave = ["C:\\...\\conclave", "C:\\...\\conclave-plugins"]
```

| Schlüssel | Default | Bedeutung |
|---|---|---|
| `enabled` | `true` | `false`: kein Start, auch nicht von Hand |
| `projects` | – (Pflicht) | Unterabschnitt `[reviewer.projects]`: Kurzname des Board-Projekts = Pfad des Checkouts oder Liste von Pfaden. Bei mehreren Checkouts wird der genannte Commit in allen gesucht |
| `poll_seconds` | `30` | Abstand der Abfragen des Änderungszählers; die Review-Spalte liest er nur nach einer Änderung |
| `max_reviews_per_hour` | `6` | Höchstens so viele Reviews je Stunde, weitere warten |
| `review_timeout_minutes` | `30` | Danach wird `claude` samt Kindprozessen beendet; das Review bleibt `running`, mit einem Hinweis am Ticket |
| `claude_exe` | leer | Pfad zu `claude`; leer: die VS-Code-Erweiterung, sonst `PATH` |
| `agent` | `claude` | Wer das Review schreibt: `claude` oder `codex` (`codex exec`, siehe unten) |
| `codex_exe` | leer | Pfad zu `codex`; leer: die VS-Code-Erweiterung von OpenAI, sonst `PATH` |
| `codex_model` | leer | Modell für `codex exec -m`; leer: das Standardmodell von Codex |
| `prompt_file` | leer | Eigene Fassung des Review-Auftrags, relativ zum Ordner der `config.toml`; leer: die mitgelieferte Fassung. Ohne die Platzhalter `{get}`, `{comment}` und `{board}` startet er nicht |
| `author` | `CD · auto-review` | Name im Review-Kommentar |
| `review_status` | `review` | Spalte, die er beobachtet |
| `conclave_url` | `CONCLAVE_API_URL` bzw. `http://127.0.0.1:8000` | Adresse des Servers |
| `conclave_mcp_exe` | `conclave-mcp` derselben Installation, sonst `PATH` | MCP-Server für das Review (mit `--reviewer`) |
| `reviewer_token_file` | wie `CONCLAVE_REVIEWER_TOKEN_FILE` | Das Token liest nur der MCP-Server; der Start prüft nur, ob die Datei da ist |
| `legacy_lock_file` | leer | Sperrdatei des früheren, getrennten Watchers: Hält er sie, startet der Reviewer nicht |

**Codex statt Claude (`agent = "codex"`, experimentell).** Der Reviewer startet dann
`codex exec --ignore-user-config --ephemeral -s read-only -c approval_policy="never" -C <Worktree> -`.
Die MCP-Server (Board als Reviewer, git je Checkout) bekommt Codex über
`-c mcp_servers.<name>.…`. System-Prompt und Auftrag kommen zusammen über stdin, und die
Kommandozeile enthält wie bei `claude` keinen Text aus einem Ticket. Der wichtige Unterschied:
Codex hat immer eine Shell. `-s read-only` verbietet nur das Schreiben, gelesen werden kann alles,
was das Windows-Konto lesen darf, und localhost ist erreichbar. Conclaves eigene Token-Dateien und
`secret.key` schützen ihre Dateirechte, andere Zugangsdaten im Profil (z. B. `pgpass.conf`, `.ssh`)
nicht. Unter Windows lässt sich das Lesen mit Codex-Bordmitteln nur über das „elevated“-Backend
einschränken, und das greift auf Systemebene ein (eigene Konten, Firewall-Regeln, Sperreinträge im
Profil). Codex als Reviewer deshalb nur unter einem **eigenen Windows-Konto** ohne Zugangsdaten
betreiben, nicht unter dem eigenen Benutzer.

**Entfernter Board-Server (ab v0.9.0, optional).** Ohne diese Schlüssel ändert sich nichts. Mit
`server = "team"` prüft der Reviewer gegen einen Board-Server mit Konten statt gegen Conclave Personal.
Die Einstellungen stehen dann meist in einer eigenen Datei, gestartet mit
`conclave-reviewer run --settings <Datei>`. Relative Pfade gelten relativ zu dieser Datei.

| Schlüssel | Default | Bedeutung |
|---|---|---|
| `server` | `personal` | `team`: entfernter Board-Server; dann gelten die Pflichten und Standards dieser Tabelle |
| `server_url` | – (Pflicht mit `team`) | Adresse des Servers, `https`; `http` nur für diesen Rechner. Statt `conclave_url` |
| `ca_bundle` | – (Pflicht mit `team`) | Eigene CA als PEM-Datei. Es gilt nur diese CA; `SSL_CERT_FILE`, `SSL_CERT_DIR` und Proxy-Variablen wirken nicht, Umleitungen werden nicht verfolgt |
| `reviewer_token_file` / `reviewer_token_credential` | – (eins davon Pflicht mit `team`) | Token-Datei nur für den Benutzer bzw. Zielname einer generischen Anmeldeinformation in der Windows-Anmeldeinformationsverwaltung. Das Token steht nie in der Datei |
| `data_dir` | `<Konfigurationsordner>/reviewer` | Datenordner; `--data-dir` hat Vorrang |
| `conclave_mcp_exe`, `conclave_mcp_args` | mit `team`: `conclave-board-mcp`, `["--reviewer"]` | MCP-Server des Board-Servers |
| `fetch` | mit `team`: `true` | Vor jedem Review `git fetch` in den Checkouts; die Branches von `origin` haben Vorrang |
| `missing_commits` | mit `team`: `red` | `red`: Ist keiner der genannten Commits im Git-Server, oder fehlt der zu prüfende (`branch` @ `hash`), ist das Review rot, ohne `claude`. `yellow`: wie in Personal nur ein Hinweis |

Mit `server = "team"` steht die Ausgabe von `claude` nicht im Log.

Die Daten liegen in `<Konfigurationsordner>/reviewer` (Windows
`%APPDATA%\Conclave\reviewer`, nur für den Benutzer lesbar):

- `reviewer.log`: das Protokoll, nach der Rotation `reviewer.log.1`
- `reviewer-start.log`: Fehler beim Start durch `conclave desktop`; zuerst hier
  nachsehen, wenn das Board „Reviewer aus“ zeigt
- `state.json`, `status.json`, `reviewer.lock`
- `mcp-board.json`: die MCP-Konfiguration des laufenden Reviews
- `review-prompt.md`: der System-Prompt des laufenden Reviews (`--append-system-prompt-file`). Den Auftrag
  bekommt `claude` über stdin; auf seiner Kommandozeile steht kein Text aus dem Ticket, auch nicht der Titel
- `worktrees/`: die Worktrees während eines Reviews

`CONCLAVE_REVIEWER_DATA_DIR` legt einen anderen Ordner fest,
`CONCLAVE_CONFIG_FILE` eine andere `config.toml`.

## Grenzen für Agenten

`[limits]` begrenzt, was Agenten (Agent-Token) über Conclave an Modellen
verbrauchen. Budgets zählen Tokens (Eingabe plus Ausgabe) der letzten 24 Stunden
für Läufe, die ein Agent über `invoke`, `orchestrate` oder `orchestrate-parallel`
ausgelöst hat. `0` schaltet ein Budget bzw. die Grenze gleichzeitiger Läufe ab.
`agent_rate_limit = "off"` heißt: Für Agenten gilt dann das allgemeine
`rate_limit`. Umgekehrt gilt `agent_rate_limit` auch, wenn das allgemeine
`rate_limit` abgeschaltet ist. Für den Menschen gilt keine dieser Grenzen.

```toml
[limits]
agent_tokens_per_day = 2000000        # alle Agenten zusammen
conversation_tokens_per_day = 500000  # je Conversation, für Agenten
agent_concurrent_runs = 2             # gleichzeitige Modellläufe von Agenten
agent_rate_limit = "60 per minute"    # eigenes Rate-Limit für Agent-Anfragen
```

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `agent_tokens_per_day` | `2000000` | Tagesbudget aller Agent-Läufe; erschöpft → `429 AgentBudgetExceeded` |
| `conversation_tokens_per_day` | `500000` | Tagesbudget je Conversation für Agenten; erschöpft → `429 ConversationBudgetExceeded` (auch gegen Schleifen, die dieselbe Conversation immer wieder anstoßen) |
| `agent_concurrent_runs` | `2` | Höchstens so viele Modellläufe von Agenten gleichzeitig; sonst `429 TooManyAgentRuns` |
| `agent_rate_limit` | `60 per minute` | Rate-Limit für Anfragen mit dem Agent- oder Reviewer-Token, getrennt vom allgemeinen `rate_limit`; die UI bleibt so bedienbar, auch wenn Agenten viel anfragen |

Consultations zählen nicht zum Budget; für sie gilt `[consultations] max_per_hour`.

## Consultations

Consultations holen eine Zweitmeinung zu einem Ticket aus dem eigenen Board
oder aus [Kanzo](https://github.com/emanuele-em/kanzo) (`[board] source`,
siehe oben und [API-Referenz](api.md#consultations)). Eingestellt wird das
nur in `config.toml`; die API nimmt keine Ziel-Adresse an.

Abschnitt `[consultations]`:

| Schlüssel | Default | Bedeutung |
|---|---|---|
| `reviewers` | leer | Agent-IDs, die als Reviewer erlaubt sind – also wer Ticket-Inhalte zu sehen bekommt. **Leer = Consultations sind aus.** |
| `max_per_hour` | `3` | Höchstens so viele Consultations pro Ticket und Stunde, je Zugang (Mensch, Agent) getrennt, gezählt beim Anlegen. |
| `comment_max_chars` | `2000` | Kommentare werden auf diese Länge gekürzt (mindestens 200), die Schlusszeile kommt danach. |

Bis v0.6.0 standen diese Schlüssel unter `[kanzo]`. Dort werden sie weiter
gelesen, wenn `[consultations]` sie nicht setzt; der Server schreibt dann eine
Warnung ins Log. Steht ein Schlüssel in beiden Abschnitten, gilt
`[consultations]`, ebenfalls mit Warnung.

Abschnitt `[kanzo]` (nur mit `[board] source = "kanzo"`):

| Schlüssel | Default | Bedeutung |
|---|---|---|
| `url` | `http://localhost:4242/mcp` | Kanzos MCP-Endpunkt (`mcp_http = true` in Kanzos Konfiguration, das ist dort der Default). Umgebungsvariable `CONCLAVE_KANZO_URL` hat Vorrang. Nur `http://` oder `https://`. |

Die Consultations laufen in einem Hintergrund-Thread des Servers
(`conclave desktop`, `conclave server`, `conclave-api`). Für die Verbindung zu
Kanzo braucht der Server das MCP-SDK: `pip install "conclave-personal[mcp]"`;
für das eigene Board nicht.
