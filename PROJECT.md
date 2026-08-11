# Conclave Personal

**Projekt-ID:** `conclave`
**Arbeitsbranch:** `personal-multiplatform`
**Phase:** Phase 13 - Release-Vorbereitung

## Ziel

Conclave Personal ist ein lokales, multiplattformfaehiges
Multi-Agent-Arbeitswerkzeug fuer einzelne Nutzer.

Der Nutzer fuehrt Conversations, laedt Agenten mit unterschiedlichen Rollen ein,
stellt Workspace-Dateien als Kontext bereit und startet strukturierte Laeufe wie
Invoke, Parallel-Orchestrierung, Auto-Loop und Judge/Review.

Windows und Linux sind gleichwertige Zielplattformen. Docker bleibt optional,
ist aber nicht der primaere Nutzerpfad.

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
5. Judge-Agent fuer Review oder Chain-of-Verification nutzen.
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
- Kein Docker-Zwang fuer Endnutzer.

## Architekturprinzipien

- Der Nutzer ist die Steuerungsinstanz.
- Agenten sind Teilnehmer, keine Controller.
- Daten liegen standardmaessig lokal.
- Provider bleiben austauschbar.
- Der Core ist plattformneutral.
- Windows- und Linux-Integration sind Runtime-Adapter, nicht Produktkern.
- Workspace-Zugriffe bleiben explizit und begrenzt.
- Kosten und Laeufe bleiben sichtbar.

## Aktueller Stand

Der Personal-Pfad ist lokal, desktop-first und auf einzelne Nutzer
ausgerichtet. Der aktuelle Release-Schnitt ist installierbar, CI-abgesichert
und mit Lizenz, Release Notes, Security-Hinweisen, Beispiel-Workflows,
Screenshots sowie expliziter SQLite-Migration veroeffentlichungsnah
vorbereitet.

## Regeln

Dieses Repository ist fuer v0.1.0 selbstbeschreibend. Fuer Beitraege gelten:

- Personal-first: keine Enterprise-/DSGVO-Oberflaechen wieder einfuehren.
- Keine Feature-Ausweitung waehrend Release-Stabilisierung ohne konkreten
  Fehler- oder Release-Grund.
- Runtime-Pfade muessen Windows und Linux/XDG respektieren.
- Workspace-Zugriffe bleiben explizit, begrenzt und pfadgeschuetzt.
- Remote-Provider duerfen nicht als offline oder lokal dargestellt werden.
- Tests, Packaging und relevante Dokumentation gehoeren zur Definition of Done.

Weiterfuehrende allgemeine Regeln koennen extern gepflegt sein, sind fuer die
lokale Arbeit an Conclave v0.1.0 aber nicht erforderlich:
[`governance/RULES.md`](https://github.com/laszlo-pinter/governance/blob/main/RULES.md).
