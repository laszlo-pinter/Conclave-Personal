# Provider-Smoke-Test

Ziel: Nach Installation oder Checkout prüfen, ob Conclave lokale Runtime,
Agent-Konfiguration, Provider-Keys und Multi-Agent-Aufruf sauber verbindet.

Der Smoke-Test nutzt vier Remote-Provider:

- Claude über Anthropic
- Gemini über Google
- GPT über OpenAI Responses
- DeepSeek über die offizielle DeepSeek API

Remote-Provider erhalten die für den Modellaufruf erforderlichen Prompt- und
Kontextdaten.

## 1. Projektumgebung Starten

Im Projektordner bleiben, nicht in `.venv` wechseln:

Windows / PowerShell:

```powershell
cd "<pfad-zum-checkout>\Conclave-Personal"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Linux / Bash:

```bash
cd "<pfad-zum-checkout>/Conclave-Personal"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Wenn PowerShell die Aktivierung blockiert:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Fallback ohne Aktivierung:

Windows / PowerShell:

```powershell
.\.venv\Scripts\python.exe -m conclave.cli.main --help
```

Linux / Bash:

```bash
.venv/bin/python -m conclave.cli.main --help
```

In allen folgenden CLI-Beispielen kann `conclave` durch
`python -m conclave.cli.main` ersetzt werden, wenn das Script-Kommando im PATH
noch nicht verfügbar ist.

## 2. API-Keys Setzen

Die Keys werden nur lokal im aktuellen Terminalprozess gesetzt:

Windows / PowerShell:

```powershell
$env:ANTHROPIC_API_KEY="sk-ant-..."
$env:GEMINI_API_KEY="..."
$env:OPENAI_API_KEY="sk-..."
$env:DEEPSEEK_API_KEY="sk-..."
```

Linux / Bash:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="..."
export OPENAI_API_KEY="sk-..."
export DEEPSEEK_API_KEY="sk-..."
```

`/providers` meldet einen Provider als verfügbar, wenn ein Fallback-Key über
Environment Variable oder Konfiguration vorhanden ist. Eigene Keys einzelner
Agenten fließen dort nicht ein; sie erscheinen in der Agentenliste als
Chip "Key" (ohne eigenen Key: "Env").

Umschließende Anführungszeichen und Leerzeichen in den Werten entfernt
Conclave automatisch und warnt dazu einmal pro Variable im Log. Wer die
Variablen über den Windows-Dialog "Umgebungsvariablen" setzt, trägt als Namen
nur `OPENAI_API_KEY` usw. ein, nicht `$env:OPENAI_API_KEY`.

Wichtig: Server und CLI-Kommandos sind getrennte Prozesse. Der Server liest die
Keys aus dem Terminal, in dem er gestartet wurde. CLI-Kommandos wie
`conclave agent-new` oder `conclave invoke` laufen in einem eigenen Prozess und
lesen die Keys aus ihrer eigenen Umgebung. Da der Server sein Terminal
blockiert, laufen die Schritte ab Abschnitt 4 in einem zweiten Terminal;
dort die venv aktivieren und die Keys ebenfalls setzen.

## 3. Server/UI Starten

Windows / PowerShell und Linux / Bash:

```powershell
python -m conclave.cli.main desktop --port 8001
```

Wenn das `conclave`-Kommando korrekt installiert und im PATH ist, geht auch:

```powershell
conclave desktop --port 8001
```

## 4. Provider-Verfügbarkeit Prüfen

Die API verlangt immer ein Token (ohne Token: 401). Ist `CONCLAVE_API_KEY`
nicht gesetzt, legt der Server beim ersten Start die Datei `api.token` im
Konfigurationsverzeichnis an und gibt ihren Pfad beim Start aus
(`Conclave API-Token: …`): Windows `%APPDATA%\Conclave\api.token`, Linux
`~/.config/conclave/api.token` (bzw. `$XDG_CONFIG_HOME/conclave/`); `CONCLAVE_API_TOKEN_FILE` überschreibt den
Pfad. Läuft der Server mit `CONCLAVE_API_KEY`, diesen Wert als Token
verwenden. POST-Anfragen brauchen zusätzlich `Content-Type: application/json`.

Windows / PowerShell:

```powershell
$tok = Get-Content "$env:APPDATA\Conclave\api.token"
Invoke-RestMethod -Uri http://127.0.0.1:8001/providers -Headers @{Authorization="Bearer $tok"} | ConvertTo-Json -Depth 10
```

Linux / Bash:

```bash
curl -s -H "Authorization: Bearer $(cat ~/.config/conclave/api.token)" http://127.0.0.1:8001/providers | python -m json.tool
```

Erwartung:

- `anthropic` hat `api_key_available: true`
- `gemini` hat `api_key_available: true`
- `openai-responses` hat `api_key_available: true`
- `deepseek` hat `api_key_available: true`

Wenn OpenAI `false` zeigt, wurde der Server ohne `OPENAI_API_KEY` gestartet.
Terminal-Variable setzen und Server neu starten. Diese Anzeige betrifft nur den
Server (UI); für CLI-Aufrufe zählt die Umgebung des CLI-Terminals.

## 5. Agenten Anlegen

Windows / PowerShell und Linux / Bash:

```powershell
conclave agent-new Claude --name "Claude" --provider anthropic --preset anthropic --model "<anthropic-model>"
conclave agent-new Gemini --name "Gemini" --provider gemini --preset gemini --model "<gemini-model>"
conclave agent-new GPT --name "GPT" --provider openai-responses --preset openai-responses --model "<openai-model>"
conclave agent-new DeepSeek --name "DeepSeek" --provider deepseek --preset deepseek --model "deepseek-v4-flash"
```

Wenn die Agenten bereits existieren, stattdessen in der UI prüfen oder mit
`conclave agent-show <id>` kontrollieren.

Ersetze die Modell-Platzhalter durch Modelle, die in deinem jeweiligen
Provider-Account aktuell verfügbar sind.

## 6. Conversation Erstellen Und Alle Vier Modelle Testen

Windows / PowerShell:

```powershell
$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "Provider-Smoke-Test"
conclave add-participant $conv Claude --name "Claude"
conclave add-participant $conv Gemini --name "Gemini"
conclave add-participant $conv GPT --name "GPT"
conclave add-participant $conv DeepSeek --name "DeepSeek"
conclave message $conv "Antworte in einem Satz: Welcher Provider bist du und funktioniert der Conclave-Aufruf?"
conclave invoke $conv Claude
conclave invoke $conv Gemini
conclave invoke $conv GPT
conclave invoke $conv DeepSeek
conclave runs --conversation-id $conv
```

Linux / Bash:

```bash
conv=$(conclave --json new | python -c "import sys,json; print(json.load(sys.stdin)['conversation_id'])")
conclave topic "$conv" "Provider-Smoke-Test"
conclave add-participant "$conv" Claude --name "Claude"
conclave add-participant "$conv" Gemini --name "Gemini"
conclave add-participant "$conv" GPT --name "GPT"
conclave add-participant "$conv" DeepSeek --name "DeepSeek"
conclave message "$conv" "Antworte in einem Satz: Welcher Provider bist du und funktioniert der Conclave-Aufruf?"
conclave invoke "$conv" Claude
conclave invoke "$conv" Gemini
conclave invoke "$conv" GPT
conclave invoke "$conv" DeepSeek
conclave runs --conversation-id "$conv"
```

Erwartung:

- alle vier Invokes liefern eine Antwort
- `conclave runs --conversation-id $conv` zeigt vier erfolgreiche Runs
- die UI zeigt die vier Modellantworten in derselben Conversation

## Häufige Fehler

### `conclave` Wird Nicht Gefunden

Im Projektordner bleiben und entweder die venv aktivieren oder direkt Python
verwenden:

Windows / PowerShell:

```powershell
.\.venv\Scripts\python.exe -m conclave.cli.main desktop --port 8001
```

Linux / Bash:

```bash
.venv/bin/python -m conclave.cli.main desktop --port 8001
```

### OpenAI Liefert 401

Der Agent hat keinen eigenen Key, und der Prozess, der den Aufruf ausführt,
hat keinen gültigen OpenAI-Key. Welcher Prozess das ist, hängt vom Weg ab:

- **Aufruf aus der UI:** Der laufende Server wurde ohne gültigen OpenAI-Key
  gestartet.
- **Aufruf per CLI** (`conclave invoke`, `conclave orchestrate` …): Das
  CLI-Terminal hat keinen gültigen `OPENAI_API_KEY`. Key dort setzen; ein
  Server-Neustart hilft hier nicht.

Server prüfen (Token wie in Abschnitt 4):

Windows / PowerShell:

```powershell
$tok = Get-Content "$env:APPDATA\Conclave\api.token"
Invoke-RestMethod -Uri http://127.0.0.1:8001/providers -Headers @{Authorization="Bearer $tok"} | ConvertTo-Json -Depth 10
```

Linux / Bash:

```bash
curl -s -H "Authorization: Bearer $(cat ~/.config/conclave/api.token)" http://127.0.0.1:8001/providers | python -m json.tool
```

Wenn `openai-responses` `api_key_available: false` zeigt, Key setzen und
Server neu starten:

Windows / PowerShell:

```powershell
$env:OPENAI_API_KEY="sk-..."
python -m conclave.cli.main desktop --port 8001
```

Linux / Bash:

```bash
export OPENAI_API_KEY="sk-..."
python -m conclave.cli.main desktop --port 8001
```

Zeigt `/providers` `true` und es kommt trotzdem 401, ist der Key selbst
ungültig.

### DeepSeek Liefert 400 Wegen Modellname

Die DeepSeek-API erwartet API-Model-IDs wie `deepseek-v4-flash` oder
`deepseek-v4-pro`. Produkt- oder Release-Namen wie `DeepSeek-V3` sind keine
sendbaren API-Identifier. Bestehende `DeepSeek-V3`-Agenten werden von Conclave
auf `deepseek-v4-flash` gemappt, neue Agenten sollten direkt eine der
angezeigten API-IDs verwenden.

### Agent Wird Ohne Nachricht Aufgerufen

Conclave erwartet vor einem Provider-Aufruf mindestens eine User-Nachricht.
Erst `conclave message ...`, dann `conclave invoke ...`.
