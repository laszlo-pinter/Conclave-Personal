# Implementierungsplan: Conclave Personal Multiplattform

## Ziel

Conclave wird von einer unternehmens- und DSGVO-orientierten Plattform zu
einem persoenlichen, lokalen Multi-Agent-Arbeitswerkzeug umgebaut.

Das neue Produkt richtet sich an einzelne Nutzer, nicht an Unternehmen. Es
laeuft gleichwertig unter Windows und Linux, speichert Daten lokal, bindet
verschiedene KI-Provider ueber austauschbare Adapter an und bietet eine klare
Desktop-first Oberflaeche fuer Multi-Agent-Arbeit.

## Nicht-Ziele

- Keine DSGVO-/Enterprise-Plattform.
- Kein Consent-Management pro Provider.
- Keine DPA-/AV-Vertragsverwaltung.
- Keine rollenbasierte Unternehmensadministration.
- Kein serverzentriertes Teamprodukt als primaerer Use Case.
- Kein Docker-Zwang fuer Endnutzer.

## Produktprinzipien

1. Der Nutzer ist die einzige Steuerungsinstanz.
2. Agenten sind Teilnehmer, keine Controller.
3. Alle Daten liegen standardmaessig lokal.
4. Provider bleiben austauschbar.
5. Windows und Linux sind gleichwertige Zielplattformen.
6. Desktop-Betrieb ist der Hauptpfad, Browser/API bleiben technische Modi.
7. Workspace-Dateien sind expliziter Kontext, kein stiller Vollimport.
8. Kosten, Runs und Verlauf bleiben transparent.

## Zielarchitektur

### Hauptbereiche der App

Die neue UI besteht aus fuenf Arbeitsraeumen:

| Bereich | Zweck |
| --- | --- |
| Studio | Conversations fuehren, Participants steuern, Floor vergeben, Invoke/Stream/Auto-Loop starten |
| Agents | Agenten, Rollen, Provider, Modelle, Presets und Verbindungstests verwalten |
| Workspace | Dateien, Notizen, Kontextdokumente und Agent-Outputs verwalten |
| Runs | Orchestrierungen, Auto-Loops, Judge-Laeufe, Ergebnisse und Laufhistorie einsehen |
| Settings | API-Keys, Datenpfade, Theme, Backup, Import/Export, lokaler Sicherheitsmodus |

### Backend-Schichten

Die bestehende Schichtung bleibt erhalten, wird aber entschaerft:

```text
api/ + cli/ + desktop/
        |
application/
        |
domain/
        |
infrastructure/
```

Regeln:

- `domain/` importiert nur Python-Standardbibliothek.
- `application/` importiert `domain/` und application-interne Ports.
- `infrastructure/` implementiert Ports.
- `api/`, `cli/` und `desktop/` verdrahten die Anwendung.
- Logging wird nicht aus `infrastructure.log` direkt in `application/`
  importiert, sondern ueber einen neutralen Application-Port oder ein kleines
  `shared/logging`-Modul.

### Neues Kernmodell

| Modell | Bedeutung |
| --- | --- |
| Conversation | Arbeitsgespraech mit Thema, Regeln, Messages und Participants |
| Message | User- oder Agent-Beitrag |
| Agent | Wiederverwendbare Provider-/Rollen-Konfiguration |
| Participant | Agent in einer konkreten Conversation |
| Run | Einzelner Invoke, Stream, Orchestrierung, Auto-Loop oder Judge-Lauf |
| UsageRecord | Token, Provider, Modell, Dauer und Fehlerstatus |
| WorkspaceFile | Referenzierbare lokale Datei inklusive Metadaten |
| AppSettings | Lokale Konfiguration, Datenpfade, UI-Optionen |

`AuditEntry` wird entweder in `UsageRecord`/`RunLog` umbenannt oder intern
weiterverwendet, aber nicht mehr als Compliance-Audit in der Produktoberflaeche
praesentiert.

## Phase 0: Stabilisierung und Abzweig

### Ziel

Den aktuellen Enterprise-/DSGVO-Stand sichern und einen klaren Umbaupfad
eroeffnen.

### Aufgaben

- Aktuellen Stand als Branch oder Tag sichern:
  - `legacy-enterprise-dsgvo`
  - oder `v0-enterprise-archive`
- Neuen Arbeitsbranch anlegen:
  - `personal-multiplatform`
- Aktuellen Worktree bereinigen:
  - `__pycache__/` aus Git entfernen, falls getrackt
  - `src/conclave.egg-info/` aus Git entfernen, falls getrackt
  - `migration-extras.tgz` pruefen und vermutlich entfernen oder dokumentieren
  - `workspace/` als lokale Laufzeitdaten behandeln
- Testumgebung reparieren:
  - `cryptography` und Dev-Abhaengigkeiten installieren
  - `python -m pytest tests/ -q` als Baseline ausfuehren

### Akzeptanzkriterien

- Alter Stand ist wiederherstellbar.
- Neuer Branch existiert.
- Repo enthaelt keine generierten Python-Cache-Artefakte.
- Baseline-Teststatus ist dokumentiert.

## Phase 1: Produktziel und Dokumentation neu schneiden

### Ziel

Das Projekt bekommt eine neue oeffentliche Identitaet als Personal Tool.

### Aufgaben

- `PROJECT.md` neu formulieren:
  - Produktname
  - Zielgruppe
  - Hauptflows
  - Nicht-Ziele
  - Plattformen
- README in zwei Ebenen aufteilen:
  - Nutzer-Quickstart
  - Entwickler-Setup
- DSGVO-Dokumente archivieren:
  - nach `docs/legacy-enterprise/`
  - oder aus dem Personal-Branch entfernen
- Doku-Index umbauen:
  - Personal-Nutzung
  - Architektur
  - Desktop-Betrieb
  - Provider
  - Workspace
  - Releases
- UI-Zielarchitektur aus `workspace/ui_architecture.md` uebernehmen und fuer
  Personal anpassen:
  - Studio
  - Agents
  - Workspace
  - Runs
  - Settings

### Akzeptanzkriterien

- README beschreibt nicht mehr primaer DSGVO, DPA oder Unternehmen.
- Dokumentation nennt Windows und Linux als gleichwertige Ziele.
- Neue UI-Informationsarchitektur ist dokumentiert.

## Phase 2: DSGVO-/Enterprise-Code entfernen

### Ziel

Alle Enterprise-Compliance-Funktionen aus dem Personal-Produkt entfernen,
ohne den Kernfluss Conversation -> Agent -> Antwort zu beschaedigen.

### Entfernen oder archivieren

Domain:

- `domain/consent.py`
- `domain/dpa.py`
- DSGVO-spezifische Fehler aus `domain/errors.py`

Application:

- `compliance_service.py`
- `transfer_policy.py`
- DSGVO-spezifische Methoden in Services

Infrastructure:

- Consent-Repositories
- DPA-Repositories
- DSGVO-Migrationen, sofern nicht mehr benoetigt

API:

- `/dpa`
- `/conversations/<id>/consent`
- `/audit` als Compliance-Endpunkt
- `/admin/purge` in der bisherigen Retention-/DSGVO-Form

CLI:

- `consent-grant`
- `consent-revoke`
- `dpa-register`
- `dpa-list`
- DSGVO-Export-Kommandos als Compliance-Funktion

Tests:

- `tests/privacy/`
- DSGVO-spezifische API-/CLI-/Application-Tests

### Behalten oder umdeuten

- Verschluesselung fuer API-Keys bleibt.
- Message-Verschluesselung kann als lokale Sicherheitsoption bleiben.
- Usage/Audit-Daten werden zu persoenlicher Run- und Kostenhistorie.
- Export bleibt als persoenlicher Backup-/Datenexport, nicht als Art.-15-Flow.

### Akzeptanzkriterien

- Keine UI-Navigation fuer DSGVO, Consent oder DPA.
- Keine API-Route fuer Consent/DPA.
- Keine CLI-Hilfe mit DSGVO-Kommandos.
- Tests pruefen Personal-Flows statt Compliance-Flows.

## Phase 3: Personal-Domain einfuehren

### Ziel

Die Sprache im Code soll dem neuen Produkt entsprechen.

### Aufgaben

- Neues Modell `Run` einfuehren:
  - `id`
  - `conversation_id`
  - `kind`: `invoke`, `stream`, `orchestrate`, `auto_loop`, `judge`
  - `participants`
  - `started_at`
  - `finished_at`
  - `status`
  - `error`
  - `usage`
- `UsageRecord` aus Audit-Daten ableiten oder neu anlegen.
- `RunRepository` als Port definieren.
- SQLite-Schema um `runs` und `usage_records` erweitern.
- Bestehendes `AuditRepository` entweder:
  - in `UsageRepository` umbenennen
  - oder intern behalten und nach aussen anders benennen
- Retention durch einfache lokale Aufraeumregeln ersetzen:
  - "alte Runs loeschen"
  - "Conversation archivieren"
  - "Workspace output bereinigen"

### Akzeptanzkriterien

- Jeder Agent-Aufruf erzeugt einen Run- oder Usage-Eintrag.
- UI kann Runs unabhaengig vom Chatverlauf anzeigen.
- Fehler in Agent-Aufrufen sind im Run sichtbar.

## Phase 4: API fuer Personal-Produkt neu schneiden

### Ziel

Die HTTP-API wird kleiner, klarer und produktnah.

### Ziel-Endpoints

Conversations:

- `GET /conversations`
- `POST /conversations`
- `GET /conversations/<id>`
- `DELETE /conversations/<id>`
- `POST /conversations/<id>/topic`
- `GET /conversations/<id>/rules`
- `POST /conversations/<id>/rules`

Messages und Participants:

- `POST /conversations/<id>/messages`
- `POST /conversations/<id>/participants`
- `DELETE /conversations/<id>/participants/<pid>`
- `POST /conversations/<id>/participants/<pid>/invoke`
- `GET /conversations/<id>/participants/<pid>/stream`

Orchestrierung:

- `POST /conversations/<id>/orchestrate`
- `POST /conversations/<id>/orchestrate-parallel`
- `POST /conversations/<id>/auto-loop`
- `POST /conversations/<id>/judge`

Agents und Provider:

- `GET /agents`
- `POST /agents`
- `GET /agents/<id>`
- `PUT /agents/<id>`
- `DELETE /agents/<id>`
- `POST /agents/<id>/test`
- `GET /presets`
- `GET /providers`

Workspace:

- `GET /workspace`
- `GET /workspace/<path>`
- `POST /workspace/<path>`
- `DELETE /workspace/<path>`

Runs und Usage:

- `GET /runs`
- `GET /runs/<id>`
- `GET /usage`
- `GET /usage/conversations`

Settings und Betrieb:

- `GET /settings`
- `PUT /settings`
- `GET /health`
- `POST /backup`
- `POST /restore`

### Akzeptanzkriterien

- OpenAPI-Spec enthaelt keine Enterprise-/DSGVO-Endpunkte.
- API-Doku wird aus der Spec generiert.
- Drift-Test prueft Spec gegen Flask-Routen.

## Phase 5: CLI neu ausrichten

### Ziel

CLI wird ein persoenliches Steuerungs- und Debug-Werkzeug.

### Ziel-Kommandos

```text
conclave desktop
conclave server
conclave web

conclave new
conclave list
conclave show <conversation_id>
conclave message <conversation_id> <text>
conclave invoke <conversation_id> <agent_id>
conclave orchestrate <conversation_id> <agent_id>...
conclave auto-loop <conversation_id> <agent_id>...

conclave agents
conclave agent-new
conclave agent-edit
conclave agent-delete
conclave agent-test

conclave workspace list
conclave workspace read <path>
conclave workspace write <path>

conclave runs
conclave usage
conclave backup
```

### Akzeptanzkriterien

- `conclave --help` zeigt keine DSGVO-Kommandos.
- `conclave desktop` funktioniert auf Windows und Linux.
- `conclave server` startet nur das lokale Backend.

## Phase 6: Multiplattform-Runtime

### Ziel

Windows und Linux erhalten denselben Anwendungskern und passende native
Start-/Installationswege.

### Plattformneutrale Runtime

Neues Modul:

```text
src/conclave/runtime/
  __init__.py
  paths.py
  process.py
  desktop.py
  browser.py
  platform_info.py
```

Aufgaben:

- Plattform erkennen mit `sys.platform` und `platform`.
- Datenpfade zentral bestimmen.
- Backend-Prozess starten und stoppen.
- Freien Port finden, falls `8000` belegt ist.
- UI im Desktopfenster oder Browser oeffnen.
- Logs in plattformkonformen Ordner schreiben.

### Datenpfade

Windows:

- Config: `%APPDATA%\Conclave`
- Daten: `%LOCALAPPDATA%\Conclave`
- Logs: `%LOCALAPPDATA%\Conclave\logs`
- Workspace: `%USERPROFILE%\Conclave\workspace` oder konfigurierbar

Linux:

- Config: `$XDG_CONFIG_HOME/conclave` oder `~/.config/conclave`
- Daten: `$XDG_DATA_HOME/conclave` oder `~/.local/share/conclave`
- Logs: `$XDG_STATE_HOME/conclave/logs` oder `~/.local/state/conclave/logs`
- Workspace: `~/Conclave/workspace` oder konfigurierbar

### Windows-Integration

Scripts:

```text
scripts/windows/
  start_desktop.ps1
  start_server.ps1
  install_user_startup.ps1
  install_service_nssm.ps1
  uninstall_service_nssm.ps1
```

NSSM bleibt optional. Fuer normale Nutzer ist ein User-Startup oder direkter
Desktop-Start vorzuziehen.

### Linux-Integration

Scripts:

```text
scripts/linux/
  start_desktop.sh
  start_server.sh
  install_user_service.sh
  uninstall_user_service.sh
  conclave.desktop
  conclave.service
```

Empfehlung:

- `systemd --user` fuer Autostart.
- `.desktop` Datei fuer App-Menue.
- Keine root-Pflicht fuer normale Installation.

### Akzeptanzkriterien

- `conclave desktop` startet unter Windows.
- `conclave desktop` startet unter Linux.
- Datenpfade werden nicht hart im Code verdrahtet.
- Windows-spezifische Skripte liegen nicht mehr direkt im Haupt-Scripts-Ordner.

## Phase 7: UI-Umbau

### Ziel

Die UI bildet die neue Personal-Informationsarchitektur ab und loest den
aktuellen Tab-/Panel-Monolithen schrittweise auf.

### Zielstruktur

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

### Umbau-Reihenfolge

1. Globale Navigation einfuehren:
   - Studio
   - Agents
   - Workspace
   - Runs
   - Settings
2. DSGVO-/Privacy-Panel entfernen.
3. Agentenverwaltung aus dem Studio herausloesen.
4. Workspace als eigenen Arbeitsraum bauen.
5. Usage und Auto-Loop/Judge-Historie in Runs verschieben.
6. API-Key- und Betriebszustand nach Settings verschieben.
7. Inline-Handler und globale Zustandsvariablen reduzieren.
8. Gemeinsame UI-Komponenten fuer Tabellen, Listen, Dialoge und Status-Chips
   einfuehren.

### UX-Regeln

- Studio ist immer sofort arbeitsfaehig.
- Eine primaere Aufgabe pro Screen.
- Kein DSGVO-Vokabular in der Personal-UI.
- Agenten koennen schnell getestet werden.
- Workspace-Dateien sind klar referenzierbar.
- Runs zeigen Status, Dauer, beteiligte Agenten und Usage.

### Akzeptanzkriterien

- Erste Ansicht ist Studio, keine Landingpage.
- Agent-CRUD ist nicht mehr im Chat-Hauptscreen.
- Workspace ist eigener Bereich.
- Runs/Usage sind eigener Bereich.
- Settings enthaelt lokale Pfade und API-Key-Status.

## Phase 8: Provider und Agenten

### Ziel

Provider-Anbindung bleibt eine Kernstaerke, wird aber fuer Einzelnutzer
einfacher und verstaendlicher.

### Aufgaben

- Presets bereinigen und aktuell halten:
  - OpenAI
  - Anthropic
  - Gemini
  - Mistral
  - Ollama
  - DeepSeek
  - Qwen/DashScope
  - Custom
- Provider-Test vereinheitlichen:
  - Auth vorhanden
  - Endpoint erreichbar
  - Modell antwortet
  - Latenz messen
- Agent-Rollen einfuehren:
  - Writer
  - Reviewer
  - Critic
  - Researcher
  - Planner
  - Judge
  - Custom
- System-Prompts als Presets speicherbar machen.
- Lokale Modelle via Ollama als First-Class-Pfad behandeln.

### Akzeptanzkriterien

- Ein neuer Nutzer kann ohne CLI einen Agenten anlegen und testen.
- Ollama funktioniert ohne API-Key.
- Custom Provider bleiben moeglich.
- Provider-Fehler sind nutzerverstaendlich.

## Phase 9: Workspace und lokale Sicherheit

### Ziel

Der Workspace wird zum persoenlichen Arbeitsraum fuer Kontext, Outputs und
Notizen, ohne unkontrollierte Dateizugriffe.

### Aufgaben

- Workspace-Pfad in Settings konfigurierbar machen.
- Versteckte Ordner weiter fuer Agenten unsichtbar halten.
- Workspace-API und Agent-Directives angleichen:
  - Entscheiden, ob UI/API versteckte Dateien sehen darf.
  - Agenten duerfen sie nicht sehen.
- Dateigroessenlimit fuer `@workspace` und `@read` einfuehren.
- Optionales Kontext-Budget pro Agent oder Conversation.
- Output-Ordner fuer `@save` klar anzeigen.
- Export/Backup fuer Conversations und Workspace anbieten.

### Akzeptanzkriterien

- Agenten koennen nicht aus dem Workspace ausbrechen.
- Grosse Dateien werden nicht versehentlich komplett in Prompts geladen.
- Nutzer sieht, welche Dateien als Kontext verwendet werden.

## Phase 10: Packaging und Distribution

### Ziel

Conclave kann auf Windows und Linux veroeffentlicht und installiert werden.

### Kurzfristige Distribution

- `pipx install conclave`
- `conclave desktop`
- ZIP/TAR mit Scripts und README

### Mittelfristige Distribution

Windows:

- Portable ZIP
- Optional Installer
- Optional Startmenue-Eintrag

Linux:

- `.tar.gz`
- `.desktop` Datei
- Optional AppImage
- Optional `.deb`

### Packaging-Pruefungen

- Keine `.env` im Artefakt.
- Keine lokalen Workspace-Daten.
- Keine `__pycache__`.
- Keine `egg-info`.
- Keine privaten Logs.
- README mit klarer Installation je Plattform.

### Akzeptanzkriterien

- Frische Windows-Maschine kann Conclave starten.
- Frische Linux-Maschine kann Conclave starten.
- Release-Artefakte enthalten keine lokalen Nutzerdaten.

## Phase 11: Teststrategie

### Ziel

Die Testsuite wird auf das Personal-Produkt ausgerichtet und laeuft unter
Windows und Linux.

### Testmatrix

- Windows latest
- Ubuntu latest
- Python 3.11
- Python 3.12

### Neue Testbereiche

Domain:

- Conversation
- Agent
- Participant
- Run
- UsageRecord

Application:

- Invoke
- Stream
- Orchestrate
- Auto-Loop
- Judge
- Workspace-Referenzen
- Run-Erfassung

Infrastructure:

- SQLite-Schema
- Verschluesselung
- Provider-Profile
- UniversalAdapter
- ResilientAdapter
- Runtime-Pfade fuer Windows/Linux

API:

- Conversations
- Agents
- Workspace
- Runs
- Usage
- Settings
- OpenAPI-Drift

CLI:

- `desktop`
- `server`
- `web`
- Agent-Kommandos
- Workspace-Kommandos
- Backup

### Entfernte Tests

- DPA
- Consent
- DSGVO-Lifecycle
- Privacy-Regression im bisherigen Sinn
- RBAC, falls nicht mehr Bestandteil des Produkts

### Akzeptanzkriterien

- `python -m pytest tests/ -q` laeuft lokal.
- CI laeuft auf Windows und Linux.
- Kein Test macht echte Provider-Calls.

## Phase 12: Migration aus bestehenden Installationen

### Ziel

Bestehende lokale Daten koennen soweit sinnvoll uebernommen werden.

### Strategie

- Keine automatische Enterprise-zu-Personal-Migration beim ersten Start ohne
  Backup.
- Migration explizit ueber Kommando:

```text
conclave migrate-personal --from <old-db> --backup
```

### Uebernehmen

- Conversations
- Messages
- Agents
- Participants
- Provider-Konfigurationen
- Usage/Audit als Run-/Usage-Historie, soweit passend

### Nicht uebernehmen

- Consent
- DPA
- TransferPolicy-Einstellungen
- Enterprise-Rollen
- Legal-/Compliance-Records

### Akzeptanzkriterien

- Migration legt vorher ein Backup an.
- Migration ist idempotent oder bricht klar ab.
- Nutzer erhaelt einen Bericht, was uebernommen und was ignoriert wurde.

## Phase 13: Release-Vorbereitung

### Ziel

Das Projekt ist oeffentlich verstaendlich, installierbar und wartbar.

### Aufgaben

- README neu schreiben:
  - Was ist Conclave?
  - Warum Multi-Agent?
  - Quickstart Windows
  - Quickstart Linux
  - Provider einrichten
  - Workspace verwenden
  - Auto-Loop und Judge verwenden
- Screenshots oder kurze GIFs erzeugen.
- Beispiel-Workflows dokumentieren:
  - Text von drei Agenten reviewen lassen
  - Architekturentscheidung diskutieren
  - Datei im Workspace als Kontext nutzen
  - Judge-Agent zur Qualitaetspruefung verwenden
- Lizenz festlegen.
- Security-Hinweise fuer lokale API ergaenzen.
- Release-Checkliste erstellen.

### Release-Checkliste

- Tests gruen auf Windows und Linux.
- Keine lokalen Secrets.
- Keine lokalen Workspace-Dateien.
- Keine generierten Cache-Artefakte.
- OpenAPI aktuell.
- CLI-Hilfe aktuell.
- README aktuell.
- Installationspfade getestet.

## Risiken und Entscheidungen

### Risiko: Zu viel Umbau auf einmal

Massnahme:

- In vertikalen Schnitten arbeiten.
- Zuerst DSGVO entfernen, dann UI neu schneiden.
- Nach jeder Phase Tests reparieren.

### Risiko: Desktop-Packaging frisst Zeit

Massnahme:

- Erst `pipx install` und `conclave desktop`.
- Installer/AppImage spaeter.

### Risiko: Windows- und Linux-Pfade divergieren

Massnahme:

- Zentrales Runtime-Modul fuer Pfade.
- Tests fuer Pfadlogik mit simulierten Plattformen.

### Risiko: Workspace wird unsicher oder unuebersichtlich

Massnahme:

- Harte Workspace-Grenze.
- Dateigroessenlimits.
- Sichtbarkeit von Kontextdateien in der UI.

### Risiko: Entfernen von DSGVO-Code zerbricht Nebeneffekte

Massnahme:

- Erst API-/CLI-Oberflaeche entfernen.
- Dann Services und Repositories.
- Danach Schema bereinigen.
- Tests nach jedem Schritt.

## Empfohlene Ticket-Schnitte

1. Repo-Hygiene und Baseline-Tests.
2. Neues Produktziel und README-Entwurf.
3. DSGVO-Routen und CLI-Kommandos entfernen.
4. DSGVO-Domain/Application/Repository-Code entfernen.
5. Run-/Usage-Modell einfuehren.
6. API-Spec fuer Personal aktualisieren.
7. Runtime-Pfade Windows/Linux einfuehren.
8. `conclave desktop/server/web` implementieren.
9. UI-Navigation auf Studio/Agents/Workspace/Runs/Settings umbauen.
10. Workspace-Limits und Sichtbarkeitsregeln haerten.
11. CI-Matrix Windows/Linux.
12. Release-Artefakt und oeffentliche README.

## Minimaler erster Meilenstein

Der erste veroeffentlichbare Personal-Meilenstein ist erreicht, wenn:

- Conclave unter Windows und Linux lokal startet.
- Ein Nutzer Agenten anlegen und testen kann.
- Eine Conversation mit mehreren Agenten gefuehrt werden kann.
- Auto-Loop und Judge funktionieren.
- Workspace-Dateien als Kontext referenziert werden koennen.
- Usage sichtbar ist.
- Keine DSGVO-/DPA-/Consent-Funktionen mehr in UI, API oder CLI sichtbar sind.
- Tests unter Windows und Linux laufen.

