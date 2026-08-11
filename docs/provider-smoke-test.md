# Provider-Smoke-Test

Ziel: Nach Installation oder Checkout prüfen, ob Conclave lokale Runtime,
Agent-Konfiguration, Provider-Keys und Multi-Agent-Aufruf sauber verbindet.

Der Smoke-Test nutzt drei Remote-Provider:

- Claude über Anthropic
- Gemini über Google
- GPT über OpenAI Responses

Remote-Provider erhalten die für den Modellaufruf erforderlichen Prompt- und
Kontextdaten.

## 1. Projektumgebung Starten

Im Projektordner bleiben, nicht in `.venv` wechseln:

```powershell
cd "<pfad-zum-checkout>\Conclave-Personal"
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Wenn PowerShell die Aktivierung blockiert:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Fallback ohne Aktivierung:

```powershell
.\.venv\Scripts\python.exe -m conclave.cli.main --help
```

In allen folgenden CLI-Beispielen kann `conclave` durch
`python -m conclave.cli.main` ersetzt werden, wenn das Script-Kommando im PATH
noch nicht verfügbar ist.

## 2. API-Keys Setzen

Die Keys werden nur lokal im aktuellen Terminalprozess gesetzt:

```powershell
$env:ANTHROPIC_API_KEY="sk-ant-..."
$env:GEMINI_API_KEY="..."
$env:OPENAI_API_KEY="sk-..."
```

Conclave zeigt Provider als verfügbar, wenn ein Agent einen eigenen Key hat
oder ein Provider-Fallback über Environment Variable vorhanden ist.

## 3. Server/UI Starten

```powershell
python -m conclave.cli.main desktop --port 8001
```

Wenn das `conclave`-Kommando korrekt installiert und im PATH ist, geht auch:

```powershell
conclave desktop --port 8001
```

## 4. Provider-Verfügbarkeit Prüfen

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8001/providers | ConvertTo-Json -Depth 10
```

Erwartung:

- `anthropic` hat `api_key_available: true`
- `gemini` hat `api_key_available: true`
- `openai-responses` hat `api_key_available: true`

Wenn OpenAI `false` zeigt, wurde der Server ohne `OPENAI_API_KEY` gestartet.
Terminal-Variable setzen und Server neu starten.

## 5. Agenten Anlegen

```powershell
conclave agent-new Claude --name "Claude" --provider anthropic --preset anthropic --model claude-sonnet-5
conclave agent-new Gemini --name "Gemini" --provider gemini --preset gemini --model gemini-3.6-flash
conclave agent-new GPT --name "GPT" --provider openai-responses --preset openai-responses --model gpt-5.6-terra
```

Wenn die Agenten bereits existieren, stattdessen in der UI prüfen oder mit
`conclave agent-show <id>` kontrollieren.

## 6. Conversation Erstellen Und Alle Drei Modelle Testen

```powershell
$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "Provider-Smoke-Test"
conclave add-participant $conv Claude --name "Claude"
conclave add-participant $conv Gemini --name "Gemini"
conclave add-participant $conv GPT --name "GPT"
conclave message $conv "Antworte in einem Satz: Welcher Provider bist du und funktioniert der Conclave-Aufruf?"
conclave invoke $conv Claude
conclave invoke $conv Gemini
conclave invoke $conv GPT
conclave runs --conversation-id $conv
```

Erwartung:

- alle drei Invokes liefern eine Antwort
- `conclave runs --conversation-id $conv` zeigt drei erfolgreiche Runs
- die UI zeigt die drei Modellantworten in derselben Conversation

## Häufige Fehler

### `conclave` Wird Nicht Gefunden

Im Projektordner bleiben und entweder die venv aktivieren oder direkt Python
verwenden:

```powershell
.\.venv\Scripts\python.exe -m conclave.cli.main desktop --port 8001
```

### OpenAI Liefert 401

Der laufende Server wurde ohne gültigen OpenAI-Key gestartet. Prüfen:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8001/providers | ConvertTo-Json -Depth 10
```

Wenn `openai-responses` `api_key_available: false` zeigt:

```powershell
$env:OPENAI_API_KEY="sk-..."
python -m conclave.cli.main desktop --port 8001
```

### Agent Wird Ohne Nachricht Aufgerufen

Conclave erwartet vor einem Provider-Aufruf mindestens eine User-Nachricht.
Erst `conclave message ...`, dann `conclave invoke ...`.
