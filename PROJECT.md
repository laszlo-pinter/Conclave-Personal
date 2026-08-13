# Conclave Personal

**Projekt-ID:** `conclave`
**Arbeitsbranch:** `personal-multiplatform`
**Phase:** Phase 13 - Release-Vorbereitung

## Ziel

Conclave Personal ist ein lokales, multiplattformfähiges
Multi-Agent-Arbeitswerkzeug für einzelne Nutzer.

Der Nutzer führt Conversations, lädt Agenten mit unterschiedlichen Rollen ein,
stellt Workspace-Dateien als Kontext bereit und startet strukturierte Läufe wie
Invoke, Parallel-Orchestrierung, Auto-Loop und Judge/Review.

Windows und Linux sind gleichwertige Zielplattformen. Docker bleibt optional,
ist aber nicht der primäre Nutzerpfad.

## Zielgruppe

- Einzelne Entwickler, Autoren, Analysten und Wissensarbeiter.
- Nutzer, die mehrere KI-Modelle oder Rollen bewusst koordinieren wollen.
- Nutzer, die lokale Datenhaltung und transparente Provider-Konfiguration
  bevorzugen.

## Kernflows

1. Agenten anlegen und Provider testen.
2. Conversation starten und Participants einladen.
3. Workspace-Dateien als Kontext referenzieren.
4. Agenten einzeln, parallel oder im Auto-Loop arbeiten lassen.
5. Judge-Agent für Review oder Chain-of-Verification nutzen.
6. Runs, Usage und Ergebnisse nachvollziehen.
7. Lokale Daten sichern und Backup-Archive validieren.

## Produktbereiche

- **Studio:** aktive Conversations, Messages, Floor, Invoke, Stream,
  Orchestrierung und Auto-Loop.
- **Agents:** Agenten, Rollen, Provider, Modelle, Presets und Tests.
- **Workspace:** lokale Dateien, Kontext, Notizen und Agent-Outputs.
- **Runs:** Laufhistorie, Judge-Ergebnisse, Fehler, Dauer und Usage.
- **Settings:** API-Keys, Datenpfade, Theme, Backup, lokaler Sicherheitsmodus.

## Nicht-Ziele

- Keine DSGVO-/Enterprise-Plattform.
- Kein Consent-Management pro Provider.
- Keine DPA-/AV-Vertragsverwaltung.
- Keine rollenbasierte Unternehmensadministration.
- Kein serverzentriertes Teamprodukt als Hauptfall.
- Kein Docker-Zwang für Endnutzer.

## Architekturprinzipien

- Der Nutzer ist die Steuerungsinstanz.
- Agenten sind Teilnehmer, keine Controller.
- Daten liegen standardmäßig lokal.
- Provider bleiben austauschbar.
- Der Core ist plattformneutral.
- Windows- und Linux-Integration sind Runtime-Adapter, nicht Produktkern.
- Workspace-Zugriffe bleiben explizit und begrenzt.
- Kosten und Läufe bleiben sichtbar.

## Aktueller Stand

Der Personal-Pfad ist lokal, desktop-first und auf einzelne Nutzer
ausgerichtet. Der aktuelle Release-Schnitt ist installierbar, CI-abgesichert
und mit Lizenz, Release Notes, Security-Hinweisen, Beispiel-Workflows,
Screenshots sowie expliziter SQLite-Migration veröffentlichungsnah
vorbereitet.

## Regeln

Dieses Repository ist für v0.1.1 selbstbeschreibend. Für Beiträge gelten:

- Personal-first: keine Enterprise-/DSGVO-Oberflächen wieder einführen.
- Keine Feature-Ausweitung während Release-Stabilisierung ohne konkreten
  Fehler- oder Release-Grund.
- Runtime-Pfade müssen Windows und Linux/XDG respektieren.
- Workspace-Zugriffe bleiben explizit, begrenzt und pfadgeschützt.
- Remote-Provider dürfen nicht als offline oder lokal dargestellt werden.
- Tests, Packaging und relevante Dokumentation gehören zur Definition of Done.
