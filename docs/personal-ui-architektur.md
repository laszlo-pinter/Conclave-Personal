# Personal UI Architektur

## Ziel

Die Conclave-UI wird fuer ein persoenliches Multi-Agent-Arbeitswerkzeug neu
geschnitten. Der bisherige Ansatz mit vielen Funktionen in einem Bedienraum
wird durch fuenf fachliche Arbeitsraeume ersetzt.

Die UI ist keine Enterprise-Konsole. Sie ist ein lokales Arbeitsstudio fuer
einzelne Nutzer.

## Globale Navigation

- Studio
- Agents
- Workspace
- Runs
- Settings

Globale Navigation trennt Arbeitsraeume. Lokale Navigation strukturiert nur
innerhalb eines Arbeitsraums.

## 1. Studio

### Zweck

Studio ist der primaere Arbeitsraum fuer aktive Conversations.

### Inhalte

- Conversation-Liste
- aktive Session
- Chat-Verlauf
- Participants
- Floor Control
- Invoke und Stream
- Orchestrierung
- Auto-Loop
- Conversation-Regeln

### Nicht im Studio

- Agent-Konfiguration im Detail
- globale Provider-Verwaltung
- Workspace-Dateiverwaltung
- Usage-Historie
- Backup- oder App-Einstellungen

## 2. Agents

### Zweck

Agents ist der Verwaltungsraum fuer wiederverwendbare KI-Teilnehmer.

### Inhalte

- Agentenliste
- Agent anlegen, bearbeiten, loeschen
- Rolle/System-Prompt
- Provider
- Modell
- API-Key-Status
- Verbindungstest
- Presets

### Rollen

Startrollen:

- Writer
- Reviewer
- Critic
- Researcher
- Planner
- Judge
- Custom

## 3. Workspace

### Zweck

Workspace ist der lokale Datenraum fuer Kontext, Notizen und Outputs.

### Inhalte

- Dateiuebersicht
- Textdateien lesen
- Datei hochladen oder Text ablegen
- `@workspace/...` Referenzen kopieren/einfuegen
- Output-Ordner anzeigen
- Sichtbarkeit fuer Agenten erklaeren

### Sicherheitsregeln

- Agenten duerfen nicht aus dem Workspace ausbrechen.
- Versteckte Ordner sind fuer Agenten unsichtbar.
- Grosse Dateien brauchen Limits oder explizite Bestaetigung.
- Kontext wird nicht automatisch vollstaendig geladen.

## 4. Runs

### Zweck

Runs macht Arbeitsschritte sichtbar, die ueber einzelne Chat-Messages
hinausgehen.

### Inhalte

- Invoke-Historie
- Orchestrierungslaeufe
- Auto-Loops
- Judge-Laeufe
- Status
- Dauer
- beteiligte Agenten
- Fehler
- Token-Usage

### Ziel

Der Nutzer soll sehen koennen, was gelaufen ist, was es gekostet hat und wo
ein Lauf fehlgeschlagen ist.

## 5. Settings

### Zweck

Settings buendelt lokale App-Konfiguration.

### Inhalte

- API-Keys
- lokaler Datenpfad
- Workspace-Pfad
- Theme
- Backup und Restore-Validierung
- lokaler Sicherheitsmodus
- Server-Port
- Desktop-/Browser-Startmodus

## Technische Zielstruktur

```text
static/js/
  core/
    api.js
    state.js
    router.js
    events.js
    render.js
  features/
    studio/
      conversations.js
      session.js
      participants.js
      floor.js
      orchestration.js
      autoloop.js
    agents/
      agents.js
      providers.js
      presets.js
    workspace/
      files.js
      editor.js
      references.js
    runs/
      runs.js
      usage.js
      judge.js
    settings/
      settings.js
      keys.js
      backup.js
```

## Migrationsreihenfolge

1. Globale Navigation auf die fuenf Personal-Bereiche umstellen.
2. Privacy-/DSGVO-Panel entfernen.
3. Agentenverwaltung aus dem Studio herausloesen.
4. Workspace als eigenen Bereich bauen.
5. Usage, Judge und Auto-Loop-Historie in Runs sammeln.
6. API-Key-Status, Datenpfade und Backup nach Settings verschieben.
7. Inline-Handler und globale UI-Zustaende schrittweise reduzieren.

## UX-Regeln

- Erste Ansicht ist Studio.
- Eine primaere Aufgabe pro Screen.
- Keine DSGVO-Begriffe in der Personal-UI.
- Agenten sind schnell testbar.
- Workspace-Referenzen sind sichtbar und kopierbar.
- Runs zeigen Zustand, Dauer, Agenten und Kosten.
- Fehler werden als handlungsnahe Meldungen dargestellt.
