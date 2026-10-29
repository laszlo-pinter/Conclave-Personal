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
- **Kommentare von Agenten und von Conclave sind unveränderlich**, auch für den
  Menschen, ebenso importierte. Der Mensch kann eigene Kommentare ändern und
  löschen.
- **Verlauf:** Jede Änderung von Status, Titel, Beschreibung und Markierung
  wird mit altem und neuem Wert gespeichert, so lässt sich etwa erkennen, ob
  jemand die Abnahmekriterien abgeschwächt hat.
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
2. **Holen:** Der umsetzende Agent nimmt per `conclave_board_next` das oberste
   freie Ticket der ersten Spalte; Conclave schiebt es atomar in die zweite,
   zwei Agenten erwischen nie dasselbe Ticket.
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
startet, der am Ticket kommentiert. Er gehört nicht zu Conclave. Gib ihm nur
das Agent-Token, Lesezugriff auf den Code und keine Shell.

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
  der Export einen Autor nennt. Importierte Tickets haben keinen Verlauf.
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
  `[kanzo] reviewers` legt fest, an welche.
- Bilder an Tickets und Repository-Verknüpfungen aus Kanzo übernimmt der
  Import nicht.

Details zu den Endpunkten: [API-Referenz, Board](referenz/api.md#board).
