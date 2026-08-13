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

Windows / PowerShell:

```powershell
cd "<pfad-zum-checkout>\Conclave-Personal"
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
```

Linux / Bash:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="..."
export OPENAI_API_KEY="sk-..."
```

Conclave zeigt Provider als verfügbar, wenn ein Agent einen eigenen Key hat
oder ein Provider-Fallback über Environment Variable vorhanden ist.

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

Windows / PowerShell:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8001/providers | ConvertTo-Json -Depth 10
```

Linux / Bash:

```bash
curl -s http://127.0.0.1:8001/providers | python -m json.tool
```

Erwartung:

- `anthropic` hat `api_key_available: true`
- `gemini` hat `api_key_available: true`
- `openai-responses` hat `api_key_available: true`

Wenn OpenAI `false` zeigt, wurde der Server ohne `OPENAI_API_KEY` gestartet.
Terminal-Variable setzen und Server neu starten.

## 5. Agenten Anlegen

Windows / PowerShell und Linux / Bash:

```powershell
conclave agent-new Claude --name "Claude" --provider anthropic --preset anthropic --model "<anthropic-model>"
conclave agent-new Gemini --name "Gemini" --provider gemini --preset gemini --model "<gemini-model>"
conclave agent-new GPT --name "GPT" --provider openai-responses --preset openai-responses --model "<openai-model>"
```

Wenn die Agenten bereits existieren, stattdessen in der UI prüfen oder mit
`conclave agent-show <id>` kontrollieren.

Ersetze die Modell-Platzhalter durch Modelle, die in deinem jeweiligen
Provider-Account aktuell verfügbar sind.

## 6. Conversation Erstellen Und Alle Drei Modelle Testen

Windows / PowerShell:

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

Linux / Bash:

```bash
conv=$(conclave --json new | python -c "import sys,json; print(json.load(sys.stdin)['conversation_id'])")
conclave topic "$conv" "Provider-Smoke-Test"
conclave add-participant "$conv" Claude --name "Claude"
conclave add-participant "$conv" Gemini --name "Gemini"
conclave add-participant "$conv" GPT --name "GPT"
conclave message "$conv" "Antworte in einem Satz: Welcher Provider bist du und funktioniert der Conclave-Aufruf?"
conclave invoke "$conv" Claude
conclave invoke "$conv" Gemini
conclave invoke "$conv" GPT
conclave runs --conversation-id "$conv"
```

Erwartung:

- alle drei Invokes liefern eine Antwort
- `conclave runs --conversation-id $conv` zeigt drei erfolgreiche Runs
- die UI zeigt die drei Modellantworten in derselben Conversation

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

Der laufende Server wurde ohne gültigen OpenAI-Key gestartet. Prüfen:

Windows / PowerShell:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8001/providers | ConvertTo-Json -Depth 10
```

Linux / Bash:

```bash
curl -s http://127.0.0.1:8001/providers | python -m json.tool
```

Wenn `openai-responses` `api_key_available: false` zeigt:

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

### Agent Wird Ohne Nachricht Aufgerufen

Conclave erwartet vor einem Provider-Aufruf mindestens eine User-Nachricht.
Erst `conclave message ...`, dann `conclave invoke ...`.
