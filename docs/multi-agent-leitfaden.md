# Conclave — Leitfaden: Multi-Agent-Orchestrierung in der Praxis

**Zielgruppe:** Conclave-Nutzer die zum ersten Mal mit mehreren Agenten arbeiten
**Basis:** Empirische Beobachtungen aus 7 Durchläufen (01.–04.04.2026)

---

## Das Wichtigste zuerst: Token-Explosion ist real

Ohne Kürzung wächst der Kontext bei sequentieller Orchestrierung
quadratisch: Jeder Agent sieht alle vorherigen Nachrichten. Bei 100
Nachrichten mit ~300 Tokens Durchschnitt sind das am Ende ~30.000
Tokens pro Aufruf — nur für den Kontext.

**Was Conclave tatsächlich sendet:**

- **Agenten mit Preset** (Universal-Adapter) erhalten nur die erste
  User-Nachricht plus die letzten 24 Nachrichten
  (`CONCLAVE_MAX_MESSAGES`, Default 25). In der UI angelegte Agenten
  haben immer ein Preset, fallen also immer unter diese Kürzung.
- **Volle Historie** erhalten nur Agenten über die nativen Adapter:
  per CLI angelegte Agenten mit Provider `anthropic` oder `openai`
  ohne Preset.
- **Pro Agent einstellbar:** Das Feld „Max. Nachrichten“ (UI unter
  „Erweitert“, CLI `--max-messages`, API `max_messages`) überschreibt das
  für beide Adapter-Arten: leer = Standard wie oben, `0` = keine Kürzung,
  eine Zahl = höchstens so viele Nachrichten (die erste User-Nachricht
  bleibt als Anker erhalten).

**Sichtbar in der UI (ab v0.3.0):**

- Unter jeder Modellantwort steht ein **Kontext-Chip**, z. B.
  „Kontext: 25/80 Nachrichten · 2 Dateien · ca. 6.400 Token (abgerechnet
  6.912)“. Orange heißt: Nachrichten wurden ausgelassen. Ein Klick zeigt
  den ausgelassenen Bereich (mit Sprung dorthin), die Bausteine des
  System-Prompts, eingebundene und abgewiesene Dateien sowie geschätzte und
  abgerechnete Token.
- **Vor dem Aufruf** zeigt die Bedienleiste, was der nächste Aufruf senden
  würde („Nächster Aufruf: Agent sieht 25 von 80 Nachrichten“). Die Dialoge
  für Orchestrierung und Auto-Loop zeigen das pro Teilnehmer.
- Rot markiert ist ein großer Kontext ohne Kürzung (ab ca. 50.000 Token):
  Dort entstehen die Kosten.

Die Kürzung begrenzt den Kontext pro Aufruf, aber jede Antwort bleibt
eine bezahlte Ausgabe, und bis zum Erreichen des Fensters wächst der
Kontext weiter.

**Drei Agenten sind nicht 50% teurer als zwei. Sie sind 100% teurer.**
(Gilt ohne Kürzung; mit Kürzung wächst der Kontext nur bis zum Fenster.)

Jede zusätzliche Antwort vergrößert den Kontext für alle
folgenden Aufrufe. Das führt zu:
- API-Rate-Limits bei langen Sessions
- Abnehmender Antwortqualität (Kontext überflutet den Prompt)
- In den Durchläufen beobachteten Abbrüchen bei >30.000 Tokens pro
  Aufruf (Beobachtung beim jeweiligen Provider, kein Limit in Conclave)

---

## Fünf Setups, fünf Ergebnisse

### Setup 1: Zwei Agenten + aktiver Moderator

```
Mensch (aktiv) ←→ Claude + GPT
```

- **Nachrichten:** 154
- **Token-Limit:** Nicht erreicht
- **Ergebnis:** 4 substantielle Konzeptpapiere
- **Warum es funktioniert:** Der Mensch steuert aktiv — bremst,
  lenkt um, fordert Reflexion ein. Die Agenten reagieren auf
  den menschlichen Guard.

**Empfehlung:** Das beste Setup für kreative und konzeptionelle
Arbeit (Texte schreiben, Strategien entwickeln, Ideen strukturieren).

### Setup 2: Drei Agenten + passiver Moderator

```
Mensch (passiv) → Claude + GPT + Gemini
```

- **Nachrichten:** 117 (davon 64 Setup)
- **Token-Limit:** Abbruch beobachtet bei >30.000 Tokens (kein Limit in Conclave)
- **Ergebnis:** Substanzloser Plan ohne Bezug zur Realität

**Was schiefging:**
1. 55% der Nachrichten gingen für Setup drauf (Wer ist da?
   Funktioniert der Workspace? Wer hat welche Rolle?)
2. Harmonietrichter: Einer formuliert, zweiter stimmt zu,
   dritter fasst zusammen — fertig
3. Kein Agent widersprach, weil alle sich einig sein mussten
4. Der dritte Agent (PM) addierte keinen Inhalt, nur Token

**Empfehlung:** Vermeide dieses Setup. Drei Agenten in einer
Endlos-Conversation mit passiver Moderation ist der sicherste
Weg zu hohen Kosten bei null Ergebnis.

### Setup 3: Drei Agenten + AI-Moderator (kein Verifikator)

Conclave hat keine eingebaute Moderator-Rolle (Startrollen: Writer,
Reviewer, Critic, Researcher, Planner, Custom). "AI-Moderator" meint
hier einen externen Agenten (z.B. Claude Code), der Conclave über den
MCP-Server (`conclave_create_conversation`, `conclave_send_message`,
`conclave_orchestrate` …) steuert.

```
AI-Moderator → Claude + GPT + Gemini (parallel)
```

- **Nachrichten:** 4 pro Aufgabe
- **Token-Limit:** Nicht erreicht
- **Ergebnis:** Fabrizierte Befunde — auch mit Code im Kontext

**Was schiefging:**
- Die Agenten hatten den Quellcode im Kontext und haben trotzdem
  aus dem Trainingsvorwissen generiert statt den Code zu lesen
- Beispiele aus dem damaligen Durchlauf (historische Beobachtung,
  Codestand 04/2026; heute gibt es die Presets `openai` und
  `openai-responses` nebeneinander, eine docker-compose-Datei liegt
  nicht mehr im Repository): Angaben zur OpenAI-API und zu
  Postgres-Versionen wurden aus dem Vorwissen erfunden statt dem Code
  entnommen
- Alle drei Agenten zeigten dasselbe Verhalten

**Lektion:** Chat-Agents im API-Paradigma haben Code in diesem
Durchlauf nicht zuverlässig analysiert. Für Code-Aufgaben braucht man
einen Verifikator.

Hinweis: Die Beobachtung entstand ohne die heutigen
Workspace-Mechanismen. Agenten bekommen Dateien gezielt über
`@workspace/<pfad>` in der Nachricht oder über `context_files:` in den
Conversation-Regeln (lädt Workspace-Dateien in den System-Prompt) und
können selbst `@read(<pfad>)` und `@save(<pfad>)` verwenden. Es gelten
dieselben Grenzen: nur innerhalb des Workspace, keine versteckten
Pfade, Agent-Leselimit. `context_files:`, `@read()` und `@save()`
wertet nur der Universal-Adapter aus (Agenten mit Preset). Das ersetzt
keinen Verifikator, verbessert aber die Faktenbasis.

### Setup 4: Hybridmodell — Hypothesen + Verifikation

```
AI-Moderator → Claude + GPT + Gemini (Hypothesen, parallel)
                          ↓
                   Claude Code (Verifikation, Tool-Use)
                          ↓
               Claude + GPT + Gemini (Diskussion, sequentiell)
```

AI-Moderator und Verifikator sind keine Conclave-Rollen, sondern ein
externer Tool-Use-Agent (hier Claude Code), der Conclave über den
MCP-Server steuert und selbst Dateien öffnet.

- **Nachrichten:** 4 pro Aufgabe + Verifikationsrunde
- **Token-Limit:** Nicht erreicht
- **Ergebnis:** Ausführbarer Implementierungsplan

**Warum es funktioniert:**
1. Conversation-Segmentierung: Eine Conversation pro Aufgabe,
   Ergebnisse als Dokumente übergeben
2. Parallele Hypothesen: Kein Agent sieht den anderen → kein
   Anker-Effekt, kein Harmonietrichter
3. Verifikation durch Tool-Use-Agent: Öffnet Dateien, prüft
   Behauptungen, liefert Fakten mit Zeilennummern
4. Diskussion auf Faktenbasis: Erst nach Verifikation diskutieren
   die Agents — und widersprechen sich erstmals produktiv

**Empfehlung:** Das beste Setup für Code-Analyse, technische
Bewertungen und alles wo Fakten geprüft werden müssen.

### Setup 5: Web-Interface direkt (kein Conclave)

```
Mensch → Claude Web oder GPT Web (mit Datei-Upload)
```

- **Ergebnis Claude Web:** 6/6 korrekte Code-Befunde + sofortige
  Implementierung (33 Tests, 3 Fixes)
- **Ergebnis GPT Web:** 6/6 korrekte Befunde, breitere Analyse,
  tiefere architektonische Einsichten

**Warum es funktioniert:** Web-Interfaces haben Extended Thinking,
Memory/Kontextrekonstruktion und konservativere Kalibrierung.
Sie weigern sich eher, Vermutungen als Fakten auszugeben.

**Empfehlung:** Für Einzelaufgaben (Security Audit, Architektur-Review)
ist das Web-Interface oft besser als Conclave — weil es den Code
tatsächlich liest. Conclave glänzt bei der Orchestrierung
mehrerer Perspektiven und bei Diskussionen.

---

## Praktische Regeln

### 1. Conversation-Segmentierung

**Nie eine Endlos-Conversation für mehrere Aufgaben.**

Es gibt keinen importierbaren Python-Client. Die Beispiele in diesem
Abschnitt sind Pseudocode für die MCP-Tools des Conclave-MCP-Servers
(`conclave_create_conversation(topic)`,
`conclave_send_message(conversation_id, content)`,
`conclave_orchestrate(conversation_id, sequence, parallel)`); daneben
steht jeweils die CLI-Entsprechung.

```python
# Pseudocode (MCP-Tools)
# SCHLECHT: Alles in einer Conversation
conv = conclave_create_conversation(topic="Refactoring")
# ... 117 Nachrichten später: Token-Limit, substanzloses Ergebnis

# GUT: Eine Conversation pro Aufgabe
conv1 = conclave_create_conversation(topic="Aufgabe 1: Bestandsaufnahme")
# ... 4 Nachrichten, Ergebnis als Dokument speichern
conv2 = conclave_create_conversation(topic="Aufgabe 2: Risikobewertung")
# ... 4 Nachrichten, baut auf Ergebnis von Aufgabe 1 auf
```

CLI:

```powershell
$conv1 = (conclave --json new | ConvertFrom-Json).conversation_id
conclave topic $conv1 "Aufgabe 1: Bestandsaufnahme"
```

### 2. Parallel für Analyse, sequentiell für Diskussion

```python
# Pseudocode (MCP-Tool conclave_orchestrate)
# ANALYSE: Jeder liest unabhängig
result = conclave_orchestrate(conversation_id=conv_id,
                              sequence=["Claude", "GPT", "Gemini"],
                              parallel=True)

# DISKUSSION: Jeder sieht die Vorgänger
result = conclave_orchestrate(conversation_id=conv_id,
                              sequence=["Claude", "GPT", "Gemini"],
                              parallel=False)
```

CLI:

```powershell
# ANALYSE: eine Gruppe, gleichzeitig ausgeführt
conclave orchestrate-parallel $conv --groups Claude,GPT,Gemini

# DISKUSSION: der Reihe nach
conclave orchestrate $conv Claude GPT Gemini
```

Paralleler Modus verhindert den Anker-Effekt: Der erste Agent
beeinflusst nicht, was die anderen sagen.

### 3. Zwei Agenten reichen fast immer

Der dritte Agent hat in keinem Durchlauf einen eigenständigen
Erkenntnisbeitrag geliefert, der die Token-Kosten rechtfertigt.

**Zwei Agenten mit verschiedenen Rollen** (z.B. Claude als Architekt,
GPT als Entwickler) produzieren bessere Ergebnisse als drei
Agenten die sich gegenseitig bestätigen.

Wenn du drei brauchst, gib dem dritten eine klar abgegrenzte
Aufgabe (z.B. "fasse zusammen und priorisiere"), nicht eine
Doppelrolle die mit den anderen überlappt.

### 4. Belegpflicht einführen

```
SCHLECHT: "Die Persistenzschicht hat Lücken."
GUT:      "In conversation_repository.py fehlt Error-Handling
           bei save() — kein try/except um den DB-Aufruf."
```

Die Belegpflicht verhindert Fabrikation nicht, aber sie macht
sie sichtbar. Ohne Belegpflicht sind erfundene und echte Befunde
nicht unterscheidbar.

### 5. Hypothesen statt Fakten fordern

```
SCHLECHT: "Nenne Befunde über den Code."
GUT:      "Formuliere Vermutungen. Schreibe 'ich vermute'
           statt 'es ist so'. Für jede Vermutung: formuliere
           eine Prüffrage."
```

Im Hypothesen-Modus lag GPT bei 100%, Claude bei 17%.
Im Fakten-Modus lagen alle bei ~0%. Das Wort "ich vermute"
ändert den Generierungsmodus des Modells fundamental.

### 6. Antwortlänge begrenzen

```
PROMPT: "Maximale Antwortlänge: 15 Zeilen. Zustimmung ohne
         neuen Inhalt = 'Einverstanden.' Ein Wort."
```

Das eliminiert Zeremonie ("Brillant! Ich stimme vollkommen zu
und möchte hinzufügen...") und spart Token. Wenn ein Agent
nur 15 Zeilen hat, muss er sich entscheiden ob er sie für
Höflichkeit oder für Inhalt verwendet.

### 7. Setup nicht in der Conversation verhandeln

Rollen, Regeln, Workspace-Pfade — alles was sich nicht ändert
gehört in den ersten Prompt oder in die Chat-Rules, nicht in
eine Verhandlung mit den Agenten.

```python
# Pseudocode (MCP-Tool conclave_send_message; CLI: conclave message $conv "...")
# GUT: Alles in einer Nachricht
conclave_send_message(conversation_id=conv_id, content="""
Rollen: Claude=Architekt, GPT=Entwickler. Feststehend.
Regel: Max 15 Zeilen. Belegpflicht. Kein Fliesstext.
Aufgabe: [konkrete Aufgabe]
Beginnt jetzt.
""")

# SCHLECHT: Rollen diskutieren lassen
conclave_send_message(conversation_id=conv_id, content="Wer möchte welche Rolle?")
# → 20 Nachrichten Verhandlung, 0 Ergebnis
```

---

## Token-Budget Rechner

Die folgende Rechnung gilt **ohne Kürzung**, also für Agenten mit
voller Historie (native Adapter). Agenten mit Preset erhalten pro
Aufruf höchstens die erste User-Nachricht plus die letzten 24
Nachrichten (`CONCLAVE_MAX_MESSAGES`, Default 25); bei ~300 Tokens
pro Nachricht liegt der Kontext dort also bei höchstens ~7.500 Tokens
zuzüglich System-Prompt. Die tatsächlichen Werte pro Aufruf zeigt der
Kontext-Chip unter jeder Antwort.

| Agenten | Nachrichten | ~Tokens/Nachricht | Kontext bei letztem Aufruf | Gesamt-Session |
|---------|-------------|-------------------|---------------------------|----------------|
| 2 | 20 | 300 | ~6.000 | ~60.000 |
| 2 | 50 | 300 | ~15.000 | ~375.000 |
| 3 | 20 | 300 | ~6.000 | ~90.000 |
| 3 | 50 | 300 | ~15.000 | ~562.000 |
| 3 | 100 | 300 | ~30.000 | ~1.500.000 |

**Conversation-Segmentierung reduziert das drastisch:**

| Agenten | 4 Aufgaben x 4 Nachrichten | Kontext max | Gesamt |
|---------|---------------------------|-------------|--------|
| 3 | 16 | ~1.200 | ~10.000 |

Faktor 150x weniger Tokens für bessere Ergebnisse.

---

## Wann Conclave, wann nicht

| Aufgabe | Empfehlung |
|---------|-----------|
| Texte schreiben/überarbeiten | Conclave (2 Agenten, aktiver Moderator) |
| Code analysieren | Web-Interface oder Hybridmodell mit Verifikator |
| Strategie diskutieren | Conclave (2 Agenten, aktiver Moderator) |
| Implementierungsplan | Hybridmodell (Hypothesen + Verifikation) |
| Security Audit | Web-Interface direkt (Claude oder GPT) |
| Architektur-Review | Web-Interface direkt, dann Conclave für Diskussion |
| Schnelle Einzelfrage | Kein Conclave nötig |

---

## Die vier Achsen

Wenn du ein Conclave-Setup planst, entscheide entlang dieser Achsen:

1. **Chat vs. Tool-Use:** Brauche ich Faktenverifikation? → Verifikator einbinden
2. **Fakten vs. Hypothesen:** Sollen die Agents behaupten oder vermuten? → "Ich vermute" erzwingt bessere Kalibrierung
3. **Einzel vs. Hybrid:** Reicht ein Agent, oder brauche ich Perspektivenvielfalt? → Zwei Agenten mit verschiedenen Rollen
4. **API vs. Web:** Muss der Agent Code lesen? → In den Durchläufen war das Web-Interface zuverlässiger; in Conclave Dateien gezielt per `@workspace/`, `context_files:` oder `@read()` bereitstellen

> Chat-Agents können nicht lesen, aber sie können fragen.
> (Beobachtung aus den Durchläufen ohne `@workspace/`, `@read()` und `context_files:`.)
> Tool-Use-Agents können lesen, aber sie brauchen Fragen.
> Web-Agents mit Extended Thinking können beides —
> wenn man ihnen erlaubt, "ich weiss es nicht" zu sagen.
> Die Einbettung ist alles.
