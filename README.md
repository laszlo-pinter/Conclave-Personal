Dieses Projekt wurde ausschließlich von LLM-Modellen erstellt.

# Conclave Personal

Conclave Personal ist ein lokales Multi-Agent-Arbeitswerkzeug fuer einzelne
Nutzer. Es bringt mehrere KI-Modelle in eine gemeinsame, strukturierte
Conversation, gibt ihnen explizite Rollen und macht ihre Zusammenarbeit ueber
Runs nachvollziehbar.

Der Nutzer bleibt die Steuerungsinstanz. Agenten sind Teilnehmer, keine
Controller. Conversations, Workspace-Dateien, Agenten und Usage liegen
standardmaessig lokal.

> Status: v0.1.0 Alpha. Der Hauptpfad ist lokal, desktop-first und auf einzelne
> Nutzer unter Windows und Linux ausgerichtet.

![Conclave Studio](docs/assets/screenshots/conclave-studio-desktop.png)

## Wofuer Conclave da ist

Conclave ist nicht einfach eine weitere Chat-UI. Der Kern ist:

- Multiple models.
- Explicit roles.
- Structured collaboration.
- Traceable runs.
- Human control.
- Local-first workspace.

Praktisch heisst das:

- Multi-Agent-Conversations mit Writer, Critic, Reviewer, Planner, Researcher
  oder Judge fuehren.
- Agenten als Participants in konkrete Conversations einladen.
- Dateien aus einem lokalen Workspace gezielt als Kontext verwenden.
- Modelle einzeln, parallel oder in Auto-Loops arbeiten lassen.
- Judge-/Review-Laeufe fuer gegenseitige Pruefung nutzen.
- Runs, Token-Usage, Fehler und Ergebnisse nachvollziehen.
- Unter Windows und Linux lokal arbeiten.

## 60-Sekunden-Beispiel

```text
        ┌→ Writer
Prompt ─┼→ Critic ─→ Judge
        └→ Researcher
```

1. Conversation erstellen.
2. Agents als Participants hinzufuegen.
3. Rollen vergeben: Writer entwirft, Critic widerspricht, Judge bewertet.
4. Prompt senden.
5. Run beobachten.
6. Ergebnisse vergleichen und die naechste Runde bewusst starten.

Minimaler CLI-Flow:

```bash
conclave desktop
conclave agent-new writer --name "Writer" --provider "openai-responses" --preset "openai-responses" --model "gpt-5.6" --role "Writer" --api-key "..."
conclave agent-new judge --name "Judge" --provider "ollama" --preset "ollama" --model "llama3.1" --role "Judge"
CONV=$(conclave --json new | python -c "import sys,json; print(json.load(sys.stdin)['conversation_id'])")
conclave add-participant "$CONV" writer --name "Writer" --type model
conclave add-participant "$CONV" judge --name "Judge" --type model
conclave message "$CONV" "Entwirf eine knappe Produktpositionierung und lass sie pruefen."
conclave invoke "$CONV" writer
conclave invoke "$CONV" judge
conclave runs "$CONV"
```

## Produktbereiche

| Bereich | Zweck |
| --- | --- |
| Studio | Conversations, Messages, Participants, Floor, Invoke, Stream, Orchestrierung, Auto-Loop |
| Agents | Agenten, Rollen, Provider, Modelle, Presets, Verbindungstests |
| Workspace | Lokale Dateien, Kontext, Notizen, Outputs |
| Runs | Invoke-, Judge-, Auto-Loop- und Orchestrierungsverlauf, Usage, Fehler |
| Settings | API-Keys, Datenpfade, Theme, Backup, lokaler Sicherheitsmodus |

## Nicht-Ziele

- Keine DSGVO-/Enterprise-Plattform.
- Kein Consent-Management pro Provider.
- Keine DPA-/AV-Vertragsverwaltung.
- Keine rollenbasierte Unternehmensadministration.
- Kein Docker-Zwang fuer Endnutzer.

## Plattformziel

Conclave Personal unterstuetzt Windows und Linux. Die CI-Matrix prueft Ubuntu
und Windows mit Python 3.11 und 3.12.

Der Anwendungskern bleibt plattformneutral. Betriebssystem-spezifisch sind nur
Start-, Installations- und Autostart-Adapter:

- Windows: Desktop-Start, optional User-Autostart oder NSSM-Service.
- Linux: Desktop-Start, optional `systemd --user` und `.desktop` Datei.
- Docker ist nicht Teil des v0.1.0-Endnutzerpfads.

## Installation

Nach der PyPI-Veroeffentlichung ist der Zielpfad:

### Windows

```powershell
pipx install conclave
conclave desktop
```

### Linux

```bash
pipx install conclave
conclave desktop
```

Vor der PyPI-Veroeffentlichung wird aus dem gebauten Wheel getestet:

```bash
python -m build --sdist --wheel
python -m venv .venv-smoke
.venv-smoke/Scripts/pip install dist/conclave-0.1.0-py3-none-any.whl
.venv-smoke/Scripts/conclave --help
```

Unter Linux entsprechend mit `.venv-smoke/bin/...`.

### Aus Einem Checkout

```bash
python -m pip install -e ".[dev-all]"
conclave desktop
```

Tests fuer Entwicklung:

```text
python -m pytest
```

Bestehende lokale SQLite-Daten kannst du explizit migrieren:

```bash
conclave migrate-personal --from /pfad/zur/alten/conclave.db --dry-run
conclave migrate-personal --from /pfad/zur/alten/conclave.db
```

## Provider Einrichten

Lege Agents mit Provider, Modell und optionaler Rolle an:

```bash
conclave agent-new reviewer \
  --name "Reviewer" \
  --provider "anthropic" \
  --preset "anthropic" \
  --model "claude-sonnet-4-20250514" \
  --role "Reviewer" \
  --api-key "..."
```

Ollama kann lokal ohne API-Key laufen:

```bash
conclave agent-new local-judge \
  --name "Local Judge" \
  --provider "ollama" \
  --preset "ollama" \
  --model "llama3.1" \
  --role "Judge"
```

## Lokaler Schnellstart

Der empfohlene Personal-CLI-Pfad ist:

```bash
conclave desktop
```

Technische Modi:

```bash
conclave server
conclave web
```

oder fuer direkte CLI-Flows:

```bash
conclave agent-new assistant \
  --name "Assistant" \
  --provider "openai-responses" \
  --preset "openai-responses" \
  --model "gpt-5.6" \
  --api-key "..."

ID=$(conclave --json new | python -c "import sys,json; print(json.load(sys.stdin)['conversation_id'])")
conclave add-participant "$ID" assistant --name "Assistant" --type model
conclave message "$ID" "Analysiere diese Idee aus drei Perspektiven."
conclave invoke "$ID" assistant
```

Auto-Loop und Judge-Workflows sind in den
[Beispiel-Workflows](docs/beispiel-workflows.md) beschrieben.

## Kernkonzepte

### Conversation

Ein lokaler Arbeitsraum mit Thema, Nachrichten, Regeln und Participants.

### Agent

Eine wiederverwendbare Provider-/Modell-/Rollen-Konfiguration.

### Participant

Ein Agent innerhalb einer konkreten Conversation.

### Workspace

Ein lokaler Ordner fuer Dateien, Notizen, Kontext und Outputs. Dateien werden
nicht automatisch als Kontext geladen. Der Nutzer referenziert sie explizit,
zum Beispiel mit `@workspace/notizen.md`.

### Run

Ein ausfuehrbarer Arbeitslauf: Invoke, Stream, Orchestrierung, Auto-Loop oder
Judge. Runs machen Status, Fehler, Dauer und Usage sichtbar.

## Zielarchitektur

```text
src/conclave/
  domain/          reine Fachmodelle
  application/     Services, Orchestrierung, Ports
  infrastructure/  Provider, Datenbanken, Crypto, Runtime-Adapter
  api/             lokale HTTP-API
  cli/             Kommandozeile
  runtime/         plattformneutrale Desktop-/Server-Startlogik

static/
  js/core/         API, State, Router, Events
  js/features/     Studio, Agents, Workspace, Runs, Settings
```

## Provider

Conclave bleibt provideragnostisch. v0.1.0 unterscheidet bewusst zwischen
getesteten Hauptpfaden und kompatiblen Presets.

### First-class / getestet

Diese Pfade sind durch lokale Tests, API-Vertraege oder konkrete Adaptertests
abgesichert:

- OpenAI Responses
- OpenAI Chat Completions
- Anthropic
- Ollama

### Built-in preset / kompatibel / experimentell

Diese Presets sind eingebaut, koennen aber je nach Provider-API, Modell und
Account variieren:

- Gemini
- Mistral
- DeepSeek
- Qwen / DashScope
- Custom/OpenAI-compatible Endpoints

API-Keys bleiben lokal gespeichert und werden bei Agenten verschluesselt in der
lokalen Datenbank abgelegt. Ollama kann ohne API-Key funktionieren.

## Local-first, Nicht Offline-only

Conclave speichert Workspace, Konfiguration, Agenten, Conversations und
Run-Historie lokal. Wenn ein Remote-Provider wie OpenAI, Anthropic, Gemini,
Mistral, DeepSeek oder DashScope genutzt wird, werden die fuer den jeweiligen
Modellaufruf erforderlichen Prompt-/Kontextdaten an diesen Provider
uebertragen. Bei Ollama oder lokalen kompatiblen Endpunkten kann die
Verarbeitung vollstaendig lokal erfolgen.

## Sicherheit

Conclave bindet die lokale API standardmaessig an `127.0.0.1`. Fuer den
`production`-Modus muss ein lokaler API-Key gesetzt sein. Workspace-Zugriffe
bleiben im konfigurierten Workspace-Root und versteckte Pfade werden nicht als
Agent-Kontext gelesen.

Mehr Details: [Sicherheit fuer Conclave Personal](docs/sicherheit.md).

## Dokumentation

Wichtige Dokumente:

- [Multi-Agent-Leitfaden](docs/multi-agent-leitfaden.md)
- [Beispiel-Workflows](docs/beispiel-workflows.md)
- [Sicherheit](docs/sicherheit.md)
- [Konfiguration](docs/referenz/konfiguration.md)
- [Release Notes v0.1.0](docs/release-notes-v0.1.0.md)
- [Dokumentationsindex](docs/index.md)

## Known Limitations

v0.1.0 bleibt bewusst Alpha. Bekannte Einschraenkungen:

- Backup-Erstellung ist vorhanden; Restore validiert aktuell nur und schreibt
  noch keine Daten zurueck.
- Provider-Kompatibilitaet variiert nach API, Modell, Account und Region.
- Remote-Provider erhalten die fuer den Modellaufruf benoetigten Daten.
- Desktop-Modus startet die lokale Web-Anwendung im Browser.
- Erweiterte Multi-Agent-Orchestrierung ist in Teilen experimentell.
- Es gibt noch keinen nativen Windows-Installer, kein AppImage und kein `.deb`.

## Release-Verifikation

Der v0.1.0-Schnitt wird vor Veroeffentlichung mit diesen lokalen Checks
verifiziert:

- `python -m pytest`
- `python -m build --sdist --wheel`
- Installation aus dem gebauten Wheel in einer frischen Umgebung.
- `conclave --help`
- `conclave desktop`
- Artefaktpruefung ohne Workspace-Daten, Datenbanken, Keys, Logs und alte
  Enterprise-/DSGVO-Pfade.

## Lizenz

PolyForm Noncommercial License 1.0.0. Siehe [LICENSE](LICENSE).

Free for noncommercial use. Commercial use requires a separate license.
Commercial licensing: coming soon.
