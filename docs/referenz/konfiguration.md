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
| CONCLAVE_RATE_LIMIT | 120 per minute | Anfragen je Route und Client-IP, Syntax von flask-limiter (`120/minute; 2000/hour`), `off`, `none`, `0` oder leer schalten ab. Auch als `[server] rate_limit` in der TOML-Config oder in der UI unter Settings (wirkt sofort); die Umgebungsvariable hat Vorrang und sperrt die UI-Änderung |
| CONCLAVE_CONFIG_FILE | plattformabhängig | Pfad der `config.toml` (z. B. getrennt für Testinstanzen) |
| CONCLAVE_LOG_DIR | plattformabhängig | Verzeichnis für `conclave-server.log` (z. B. getrennt für Testinstanzen) |
| CONCLAVE_SERVER_THREADS | 16 | Threads des WSGI-Servers (waitress). Laufende Streams belegen je einen Thread |
| CONCLAVE_ASSET_DIR | — | Alternatives Verzeichnis für die UI-Assets (`conclave-ui.html` und `static/`); ohne Wert die mitgelieferten Assets |
| CONCLAVE_API_URL | http://localhost:8000 | Nur MCP-Server (`conclave-mcp`): URL der Conclave-API |

## Datenbank

| Variable | Default | Beschreibung |
|----------|---------|-------------|
| CONCLAVE_DB_PROVIDER | sqlite | `sqlite` oder `postgres`. `postgres` wirkt nur für `conclave server`, `conclave desktop` und `conclave-api`; alle anderen CLI-Kommandos nutzen immer SQLite |
| CONCLAVE_DB_PATH | plattformabhängig | SQLite-Dateipfad |
| CONCLAVE_DB_DSN | — | PostgreSQL Connection String |

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
| CONCLAVE_API_KEY | — | API-Token (Bearer). Leer: Token aus `CONCLAVE_API_TOKEN_FILE`, beim ersten Serverstart erzeugt |
| CONCLAVE_API_TOKEN_FILE | `<config_dir>/api.token` | Datei für das automatisch erzeugte API-Token (nur Benutzer lesbar) |
| CONCLAVE_ALLOWED_HOSTS | — | Zusätzlich erlaubte `Host`-Header (kommasepariert, optional mit Port). `localhost`, `127.0.0.1`, `[::1]` sind immer erlaubt. Pflicht bei Nicht-Loopback-`CONCLAVE_HOST` |
| CONCLAVE_ALLOWED_ORIGINS | `http://localhost,http://localhost:8000,http://127.0.0.1,http://127.0.0.1:8000` | CORS-Allowlist (kommasepariert, exakte Origins) |

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
# Anfragen je Route und Client-IP (flask-limiter-Syntax). Mehrere Grenzen mit ";"
# trennen, "off" schaltet die Begrenzung ab. Wirksam nach Neustart des Servers;
# CONCLAVE_RATE_LIMIT hat Vorrang.
rate_limit = "120 per minute"

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
