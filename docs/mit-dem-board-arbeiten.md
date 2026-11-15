# Mit dem Board arbeiten

Seit v0.6.0 hat Conclave ein eigenes Board für Arbeitspakete: Projekte,
Tickets mit Status, Kommentare, Tickets „nur für Menschen“ und `next_task` für
Agenten. Es steht in der UI (Bereich „Board“), in der REST-API und in
`conclave-mcp`. Das Board hält fest, **was** zu tun ist und wer gerade woran
arbeitet; Conclave bringt mehrere Modelle zu einer Frage zusammen und macht
Kontext und Kosten sichtbar. Beides liegt in derselben Datenbank, unter
demselben Backup und denselben Sicherheitsregeln.

Das Board ist eine eigene Umsetzung. Funktionsumfang und Arbeitsweise sind an
[Kanzo](https://github.com/emanuele-em/kanzo) angelehnt; Conclave enthält
keinen Code aus Kanzo (AGPL-3.0). Ein externes Kanzo lässt sich weiter für
Consultations nutzen, siehe [Kanzo als externes Board](#kanzo-als-externes-board).

## Wer macht was

| | Board | Conclave |
|---|---|---|
| Aufgabe | Arbeitspakete planen und abarbeiten | Modelle befragen, vergleichen, diskutieren lassen |
| Einheit | Ticket (`projekt#nummer`) mit Status, Kommentaren und Verlauf | Conversation mit Teilnehmern und Nachrichten |
| Agenten | holen sich Arbeit per `next_task`, kommentieren, schieben nach `review` | rufen Modelle auf, holen Zweitmeinungen (`conclave_consult`) |
| Mensch | setzt Ziele, entscheidet, schiebt nach `done` | gibt frei, sieht Kosten und Kontext, verwaltet Agents und Keys |

## Herkunft statt Absprache

Wer schreibt, ergibt sich aus dem Token, nicht aus einem Feld der Anfrage:

- Kommentare und Verlauf tragen die Herkunft `human` (Mensch-Token), `agent`
  (Agent-Token), `system` (von Conclave selbst, z. B. Antworten aus
  Consultations, angezeigt als „Zweitmeinung (Modell)“) oder keine
  (importiert, angezeigt als „unbekannt“). Ein Anzeigename kommt höchstens
  dazu.
- **Nach `done` schiebt nur der Mensch.** Agenten können Tickets nicht nach
  `done` oder aus `done` schieben und erledigte Tickets nur lesen und
  kommentieren.
- **Tickets „nur für Menschen“** gibt `next_task` nie an Agenten; Agenten
  können sie nur lesen. Agenten dürfen die Markierung setzen, aber nicht
  entfernen.
- **Priorität setzt der Mensch:** Die Reihenfolge der ersten Spalte ist die
  Priorität (`rank`). Neue Tickets kommen ans Ende, so bleibt die Reihenfolge
  des Plans erhalten. Umsortieren (Drag & Drop in der ersten Spalte, `index`
  oder `rank`) darf nur der Mensch; Agenten bekommen `403`. Kommt ein Ticket
  zurück in die erste Spalte, steht es wieder an seiner Prioritätsstelle. In den
  anderen Spalten zählt der Arbeitsstand: wer ankommt, steht hinten.
- **Übernehmen statt Überspringen:** Aus der ersten Spalte kommt ein Agent nur
  über `next_task` heraus (oberstes oder bestimmtes Ticket); jede andere
  Statusänderung aus der ersten Spalte ergibt `403`, auch `todo → doing`. Der
  Rückweg `review → doing` geht.
- **Kommentare von Agenten und von Conclave sind unveränderlich**, auch für den
  Menschen, ebenso importierte. Der Mensch kann eigene Kommentare ändern und
  löschen.
- **Verlauf:** Das Anlegen und jede Änderung von Status, Titel, Beschreibung,
  Markierung, Priorität, Tags und Position wird mit altem und neuem Wert und
  Herkunft gespeichert, so lässt sich etwa erkennen, ob jemand die
  Abnahmekriterien abgeschwächt hat. Bearbeitete und gelöschte Kommentare
  stehen ebenfalls im Verlauf. Jedes Ticket zeigt, wer es angelegt hat
  (`created_by`); Agenten legen Tickets nur in der ersten Spalte an.
- **Projekt-Verlauf:** Anlegen, Umbenennen und gelöschte Tickets eines Projekts
  (`GET /board/projects/<slug>/history`).
- **Gleichzeitig ändern:** Wer beim Ändern die gelesene `version` mitgibt,
  überschreibt keine Änderung, die inzwischen ein anderer gemacht hat (`409`).
- Löschen, Projekte verwalten und der Import sind dem Menschen vorbehalten.

Die Grenze aus [Sicherheit](sicherheit.md#grenze-gleicher-betriebssystem-benutzer)
gilt auch hier: Ein Agent, der `api.token` lesen kann, hat den Mensch-Zugang.

## Einrichtung

1. **Conclave** starten (`conclave server --port 8000`).
2. **Spalten** (optional) in `config.toml`; Standard sind `todo`, `doing`,
   `review`, `done`. Neue Tickets landen in der ersten Spalte, die letzte gilt
   als erledigt:

   ```toml
   [board]
   statuses = ["todo", "doing", "review", "done"]
   ```

3. **Projekt anlegen** (Mensch-Token), z. B.:

   ```bash
   curl -X POST http://localhost:8000/board/projects \
     -H "Authorization: Bearer <Mensch-Token>" -H "Content-Type: application/json" \
     -d '{"slug": "api", "name": "API"}'
   ```

   oder bestehende Tickets [aus Kanzo importieren](#import-aus-kanzo).
4. **Agent-Host** (z. B. Claude Code) mit `conclave-mcp` verbinden:

   ```bash
   claude mcp add Conclave -s user -e CONCLAVE_API_URL=http://localhost:8000 -- conclave-mcp
   ```

   `conclave-mcp` nutzt das Agent-Token (`agent.token`); den passenden Befehl
   zeigt `conclave token show --agent`. Das Mensch-Token gehört nie in eine
   Agent-Konfiguration, siehe [Sicherheit](sicherheit.md#mensch--und-agent-zugang).

Agenten bekommen sechs Tools: `conclave_board_list`, `conclave_board_get`,
`conclave_board_next`, `conclave_board_create`, `conclave_board_update` und
`conclave_board_comment`. Ihre Antworten kennzeichnen Ticket-Texte als Daten,
nicht als Anweisungen.

## In der UI

Der Bereich „Board“ zeigt die Spalten aus `config.toml` mit Karten (Referenz,
Titel, Tags, Markierung „nur für Menschen“). Karten lassen sich per Drag & Drop
in eine andere Spalte und innerhalb der Spalte verschieben. Ein Klick öffnet
das Ticket: Beschreibung (Markdown, gefiltert wie Modellantworten),
Kommentare mit Herkunft, Verlauf, Status, Markierung und ein Feld für neue
Kommentare. Dazu kommen ein neues Ticket, die Suche, die Projektauswahl und
der Schalter „Erledigte zeigen“. Ändert ein Agent etwas, zieht die UI nach
wenigen Sekunden nach.

## Ein Ablauf als Beispiel

1. **Plan:** Mensch und Agent schreiben einen Plan. Jedes Arbeitspaket wird ein
   Ticket mit Ziel, Ausgangslage, Inhalt und Abnahme. Offene Entscheidungen
   werden eigene Tickets „nur für Menschen“.
2. **Übernehmen:** Vor der Arbeit übernimmt der Agent das Ticket, mit
   `conclave_board_next` das oberste freie der ersten Spalte oder mit
   `conclave_board_next(task="api#12")` genau dieses. Conclave schiebt es atomar
   in die zweite Spalte; zwei Agenten erwischen nie dasselbe Ticket, und das
   Board zeigt, woran gearbeitet wird.
3. **Umsetzen:** Der Agent arbeitet, testet und schreibt Branch, Commits und
   Testergebnis als Kommentar ans Ticket. Dann schiebt er es nach `review`.
4. **Zweitmeinung:** Mit `conclave_consult` holt er Meinungen mehrerer Modelle
   ein. Conclave liest das Ticket selbst und schreibt jede Antwort als
   Kommentar mit Herkunft `system` zurück; die vollständigen Antworten, der
   Kontext und die Kosten stehen in der Conversation `board:<ticket> · <id>`.
5. **Abschluss:** Der Mensch liest Kommentare und Reviews, gibt frei und schiebt
   nach `done`. Korrekturen aus einem Review werden neue Tickets.

Ein automatischer Reviewer lässt sich anschließen: ein eigener Prozess, der
das Board beobachtet und bei jedem Ticket in `review` einen Review-Agenten
startet. Er gehört nicht zu Conclave. Gib ihm das Reviewer-Token
(`conclave token show --reviewer`), den MCP-Server `conclave-mcp --reviewer`,
Lesezugriff auf den Code und keine Shell.

**Review-Ablauf:**

1. Kommt ein Ticket nach `review`, steht sein Review-Status auf `none`.
2. Der Reviewer setzt beim Start `running` und am Ende das Ergebnis mit dem
   Review als Kommentar, in einem Aufruf (`conclave_board_review`):
   - **grün** (`passed`): nichts offen. Das Ticket bleibt in `review`, bis der
     Mensch es nach `done` schiebt.
   - **gelb** (`rework`): die Abnahme ist erfüllt, aber Punkte sind offen.
   - **rot** (`failed`): Tests rot, Abnahme nicht erfüllt oder falscher Ansatz.
3. Bei gelb und rot schiebt Conclave das Ticket zurück in die erste Spalte,
   dort vor alle anderen. `conclave_board_next` liefert es als Nächstes, mit
   dem Review-Kommentar (`last_review`).
4. Nach dem dritten roten Review in Folge wird das Ticket „nur für Menschen“;
   dann entscheidet der Mensch.

Den Review-Status setzt nur der Reviewer-Zugang. Ein Agent, der Code schreibt,
kann sich also nicht selbst grün geben, solange er das Reviewer-Token nicht
lesen kann.

**Arbeitsweise des umsetzenden Agenten**, die sich mit dem Review bewährt hat:

1. Tickets nur über `conclave_board_next` holen; nach `review` schiebt er
   selbst, mit Branch, Commits und Testergebnis als Kommentar. Der Reviewer
   prüft genau die genannten Commits.
2. Nicht auf den Menschen warten: grün ist keine Freigabe.
3. Höchstens ein offenes Review: Steht ein eigenes Ticket noch ohne Ergebnis in
   `review`, wartet der Agent mit dem nächsten (er arbeitet aber weiter).
4. Gelb unterbricht nicht: erst das aktuelle Ticket fertig, dann das gelbe.
5. Rot stoppt: am nächsten sauberen Punkt (Commit) anhalten, das am aktuellen
   Ticket vermerken und das rote Ticket nehmen.
6. Punkt für Punkt antworten: „B1 behoben (`abc1234`), V1 umgesetzt,
   V2 abgelehnt: …“.

## Import aus Kanzo

Ein Kanzo-Board lässt sich übernehmen. Kanzo exportiert, Conclave importiert
(Mensch-Token):

```bash
kanzo export -f json -o board.json            # optional -p <projekt>
curl -X POST http://localhost:8000/board/import \
  -H "Authorization: Bearer <Mensch-Token>" -H "Content-Type: application/json" \
  --data-binary @board.json
```

In PowerShell:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/board/import `
  -Headers @{Authorization = "Bearer <Mensch-Token>"} -ContentType "application/json" `
  -InFile board.json
```

- Conclave prüft den ganzen Export, bevor es schreibt; ist etwas falsch, wird
  nichts übernommen (`400 ImportFormatError`). Höchstens 50 MB (`413`).
- Ticket-Nummern bleiben erhalten (`conclave#7` bleibt `conclave#7`); neue
  Tickets bekommen danach die nächste freie Nummer.
- Ein zweiter Import überspringt vorhandene Tickets (`tasks_skipped`,
  `skipped_refs`). Neue Kommentare zu einem schon importierten Ticket werden
  **nicht** nachgetragen.
- Importierte Kommentare haben keine belegte Herkunft („unbekannt“), auch wenn
  der Export einen Autor nennt. Importierte Tickets haben als Verlauf nur den
  Eintrag „Angelegt“ (Herkunft: wer importiert hat, Wert `import`).
- Status, die in `[board] statuses` fehlen, lehnt der Import ab; die Spalten
  vorher passend einstellen.

## Kanzo als externes Board

Consultations lesen Tickets standardmäßig aus dem eigenen Board. Für ein
externes Kanzo:

```toml
[board]
source = "kanzo"

[kanzo]
url = "http://localhost:4242/mcp"

[consultations]
reviewers = ["gpt", "claude"]
```

Ist `[kanzo] url` (oder `CONCLAVE_KANZO_URL`) gesetzt und `[board] source`
nicht, gilt ebenfalls Kanzo. Kanzo hat keine Anmeldung: Dort ist der Autor
eines Kommentars frei wählbar, und die Kennzeichnung von Conclave-Kommentaren
ist kein Herkunftsnachweis. Im eigenen Board kommt die Herkunft aus dem Token.

## Regeln, die sich bewährt haben

- **Ein Kommentar ist keine Freigabe.** Schritte nach außen oder schwer
  umkehrbare Schritte (Push, Veröffentlichung, Löschen, Nutzung von
  Provider-Keys) fragt der Agent direkt beim Menschen, nicht über das Board.
- **Entscheidungen als Tickets „nur für Menschen“.** So holt sie kein Agent per
  `next_task`, und die Antwort steht am Ticket.
- **Tickets enthalten, was ein Reviewer braucht:** Ziel, Abnahme und die
  betroffenen Teile des Plans, damit niemand fremde Dateien lesen muss.

## Grenzen

- Agenten laufen unter demselben Benutzer wie Conclave. Die Trennung von
  Mensch- und Agent-Zugang ist nur zusammen mit einer Sperre im Agent-Host
  eine harte Grenze, siehe
  [Sicherheit](sicherheit.md#grenze-gleicher-betriebssystem-benutzer).
- Der Ticket-Inhalt geht bei einer Consultation an die Provider der Reviewer;
  `[consultations] reviewers` legt fest, an welche.
- Bilder an Tickets und Repository-Verknüpfungen aus Kanzo übernimmt der
  Import nicht.

Details zu den Endpunkten: [API-Referenz, Board](referenz/api.md#board).
