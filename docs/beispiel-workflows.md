# Beispiel-Workflows

Diese Workflows zeigen typische Personal-Nutzung: ein Nutzer steuert mehrere
Agenten, entscheidet über Kontext und prüft Ergebnisse sichtbar in Runs.

## 1. Text Aus Mehreren Perspektiven Prüfen

Ziel: Einen Text aus zwei Perspektiven prüfen. Die Modelle liefern Hinweise;
die Entscheidung bleibt beim Nutzer.

```powershell
conclave agent-new writer --name "Writer" --provider openai-responses --preset openai-responses --model "<openai-model>" --role Writer
conclave agent-new critic --name "Critic" --provider anthropic --preset anthropic --model "<anthropic-model>" --role Critic

$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "Produkttext prüfen"
conclave add-participant $conv writer --name "Writer"
conclave add-participant $conv critic --name "Critic"
conclave message $conv "Prüft diesen Text auf Klarheit, Risiko und offene Annahmen. Keine Wahrheitsentscheidung treffen: ..."
conclave orchestrate $conv writer critic
conclave runs --conversation-id $conv
```

## 2. Architekturentscheidung Diskutieren

Ziel: Eine technische Entscheidung strukturieren.

Die Workflows 2–4 nutzen die Agenten `planner` und `reviewer`. Einmalig
anlegen, falls sie noch nicht existieren:

```powershell
conclave agent-new planner --name "Planner" --provider openai-responses --preset openai-responses --model "<openai-model>" --role Planner
conclave agent-new reviewer --name "Reviewer" --provider anthropic --preset anthropic --model "<anthropic-model>" --role Reviewer
```

```powershell
$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "ADR: SQLite vs Postgres für Personal Release"
conclave add-participant $conv planner --name "Planner"
conclave add-participant $conv reviewer --name "Reviewer"
conclave message $conv "Vergleicht SQLite und Postgres für ein lokales Personal Tool. Liefert Empfehlung, Risiken und spätere Migrationsoption."
conclave orchestrate-parallel $conv --groups planner,reviewer
conclave message $conv "Fasse die Einwände zu einer ADR-Entscheidung zusammen."
conclave invoke $conv planner
```

## 3. Datei Im Workspace Als Kontext Nutzen

Ziel: Eine lokale Datei bewusst in den Prompt geben.

```powershell
conclave workspace write notizen/release.md "Release-Kriterien: Tests grün, Wheel sauber, Migration dokumentiert."

$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "Release-Check"
conclave add-participant $conv reviewer --name "Reviewer"
conclave message $conv "Nutze @workspace/notizen/release.md als Kontext. Was fehlt für den Release?"
conclave invoke $conv reviewer
```

Workspace-Dateien werden nicht automatisch importiert. Der Nutzer referenziert
sie explizit.

`conclave workspace write` und `conclave invoke` nutzen denselben Workspace wie
die Desktop-App: `CONCLAVE_WORKSPACE`, sonst `~/Conclave/workspace`. Wurde der
Workspace-Pfad nur in den Settings der laufenden App geändert (gilt für diese
Server-Session), sieht die CLI ihn nicht; dann `CONCLAVE_WORKSPACE` im
CLI-Terminal auf denselben Pfad setzen.

## 4. Menschliche Entscheidung Nach Mehreren Antworten

Ziel: Mehrere Modellantworten sichtbar vergleichen, ohne die Entscheidung an
ein Modell auszulagern.

```powershell
$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "Release-Smoke-Test Perspektiven"
conclave add-participant $conv planner --name "Planner"
conclave add-participant $conv reviewer --name "Reviewer"
conclave message $conv "Erstelle einen knappen Plan für einen Windows/Linux Release-Smoke-Test."
conclave invoke $conv planner
conclave message $conv "Nenne nur Risiken, offene Annahmen und Punkte, die ich extern prüfen sollte."
conclave invoke $conv reviewer
conclave runs --conversation-id $conv
```

## 5. Zweitmeinung Zu Einem Kanzo-Ticket

Ziel: Ein Coding-Agent oder du selbst holt zu einem Ticket aus
[Kanzo](https://github.com/emanuele-em/kanzo) unabhängige Meinungen mehrerer
Modelle ein; sie landen als gekennzeichnete Kommentare im Ticket.

Einmalig in `config.toml` (Agent-IDs aus `conclave agents`):

```toml
[kanzo]
reviewers = ["gpt", "claude"]
```

Dann über die API (Token aus `api.token`):

```powershell
$h = @{ Authorization = "Bearer $(Get-Content $env:APPDATA\Conclave\api.token)" }
$c = Invoke-RestMethod -Method Post -Uri http://localhost:8000/consultations -Headers $h `
  -ContentType "application/json" -Body '{"task": "api#12", "question": "Ist der Fix richtig?"}'
Invoke-RestMethod -Uri "http://localhost:8000/consultations/$($c.id)" -Headers $h
```

Ein Coding-Agent mit dem Conclave-MCP-Server nutzt `conclave_consult` und
`conclave_get_consultation`. Die Antworten stehen danach im Kanzo-Board unter
dem Ticket, jeweils mit „Zweitmeinung von … über Conclave, nicht geprüft“.
Die vollständigen Antworten und ihre Kosten zeigt Conclave in der
Conversation `kanzo:api#12 · <id>`.

## Hinweise

- `conclave desktop` ist der normale Einstieg.
- CLI-Kommandos sind gut für Debugging, Dokumentation und reproduzierbare
  Arbeitsmuster.
- Conclave trifft keine Wahrheitsentscheidung. Der Nutzer prüft und entscheidet.
- Echte Provider-Calls benötigen passende API-Keys oder lokale Ollama-Modelle.
- Ersetze `<openai-model>` und `<anthropic-model>` durch Modelle, die in deinem
  Provider-Account aktuell verfügbar sind.
