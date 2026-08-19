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

```powershell
$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "ADR: SQLite vs Postgres für Personal Release"
conclave add-participant $conv planner --name "Planner"
conclave add-participant $conv reviewer --name "Reviewer"
conclave message $conv "Vergleicht SQLite und Postgres für ein lokales Personal Tool. Liefert Empfehlung, Risiken und spätere Migrationsoption."
conclave orchestrate-parallel $conv --groups planner reviewer
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

## Hinweise

- `conclave desktop` ist der normale Einstieg.
- CLI-Kommandos sind gut für Debugging, Dokumentation und reproduzierbare
  Arbeitsmuster.
- Conclave trifft keine Wahrheitsentscheidung. Der Nutzer prüft und entscheidet.
- Echte Provider-Calls benötigen passende API-Keys oder lokale Ollama-Modelle.
- Ersetze `<openai-model>` und `<anthropic-model>` durch Modelle, die in deinem
  Provider-Account aktuell verfügbar sind.
