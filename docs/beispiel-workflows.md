# Beispiel-Workflows

Diese Workflows zeigen typische Personal-Nutzung: ein Nutzer steuert mehrere
Agenten, entscheidet ueber Kontext und prueft Ergebnisse sichtbar in Runs.

## 1. Text Von Drei Agenten Reviewen Lassen

Ziel: Einen Text aus drei Perspektiven pruefen.

```powershell
conclave agent-new writer --name "Writer" --provider openai-responses --preset openai-responses --model gpt-5.6 --role Writer
conclave agent-new critic --name "Critic" --provider anthropic --preset anthropic --model claude-sonnet-4-20250514 --role Critic
conclave agent-new judge --name "Judge" --provider ollama --preset ollama --model llama3.1 --role Judge

$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "Review: Produkttext"
conclave add-participant $conv writer --name "Writer"
conclave add-participant $conv critic --name "Critic"
conclave add-participant $conv judge --name "Judge"
conclave message $conv "Prueft diesen Text auf Klarheit, Risiko und Ueberzeugungskraft: ..."
conclave orchestrate $conv writer critic judge
conclave runs --conversation-id $conv
```

## 2. Architekturentscheidung Diskutieren

Ziel: Eine technische Entscheidung strukturieren.

```powershell
$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "ADR: SQLite vs Postgres fuer Personal Release"
conclave add-participant $conv planner --name "Planner"
conclave add-participant $conv reviewer --name "Reviewer"
conclave message $conv "Vergleicht SQLite und Postgres fuer ein lokales Personal Tool. Liefert Empfehlung, Risiken und spaetere Migrationsoption."
conclave orchestrate-parallel $conv --groups planner reviewer
conclave message $conv "Fasse die Einwaende zu einer ADR-Entscheidung zusammen."
conclave invoke $conv planner
```

## 3. Datei Im Workspace Als Kontext Nutzen

Ziel: Eine lokale Datei bewusst in den Prompt geben.

```powershell
conclave workspace write notizen/release.md "Release-Kriterien: Tests gruen, Wheel sauber, Migration dokumentiert."

$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "Release-Check"
conclave add-participant $conv reviewer --name "Reviewer"
conclave message $conv "Nutze @workspace/notizen/release.md als Kontext. Was fehlt fuer den Release?"
conclave invoke $conv reviewer
```

Workspace-Dateien werden nicht automatisch importiert. Der Nutzer referenziert
sie explizit.

## 4. Judge-Agent Zur Qualitaetspruefung Verwenden

Ziel: Eine Antwort bewerten lassen, statt sie sofort zu uebernehmen.

```powershell
$conv = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv "Chain-of-Verification"
conclave add-participant $conv planner --name "Planner"
conclave add-participant $conv judge --name "Judge"
conclave message $conv "Erstelle einen knappen Plan fuer einen Windows/Linux Release-Smoke-Test."
conclave invoke $conv planner
conclave message $conv "Bewerte die letzte Antwort als Judge: Welche Annahmen sind unbewiesen?"
conclave invoke $conv judge
conclave runs --conversation-id $conv
```

## Hinweise

- `conclave desktop` ist der normale Einstieg.
- CLI-Kommandos sind gut fuer Debugging, Dokumentation und reproduzierbare
  Arbeitsmuster.
- Echte Provider-Calls benoetigen passende API-Keys oder lokale Ollama-Modelle.
