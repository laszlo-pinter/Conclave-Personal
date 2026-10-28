# Mit Kanzo arbeiten

[Kanzo](https://github.com/emanuele-em/kanzo) ist ein lokales Kanban-Board für
Menschen und Agenten. Conclave und Kanzo ergänzen sich: Kanzo hält fest,
**was** zu tun ist und wer gerade woran arbeitet; Conclave bringt mehrere
Modelle zu einer Frage zusammen und macht Kontext und Kosten sichtbar. Beide
laufen lokal und sprechen über MCP miteinander. Conclave enthält keinen Code
aus Kanzo (AGPL-3.0).

## Wer macht was

| | Kanzo | Conclave |
|---|---|---|
| Aufgabe | Arbeitspakete planen und abarbeiten | Modelle befragen, vergleichen, diskutieren lassen |
| Einheit | Ticket (`projekt#nummer`) mit Status und Kommentaren | Conversation mit Teilnehmern und Nachrichten |
| Agenten | holen sich Arbeit per `next_task`, kommentieren, schieben nach `review` | rufen Modelle auf, holen Zweitmeinungen (`conclave_consult`) |
| Mensch | setzt Ziele, entscheidet, schiebt nach `done` | gibt frei, sieht Kosten und Kontext, verwaltet Agents und Keys |

Tickets mit Kanzos Markierung „nur für Menschen“ (`human`) überspringt
`next_task` von selbst. Conclave lehnt Consultations zu solchen Tickets für das
Agent-Token ab, über MCP wie über direkte REST-Aufrufe.

## Einrichtung

1. **Kanzo** installieren und starten (`kanzo`, Board unter
   `http://localhost:4242`). Damit Conclave das Board erreicht, muss Kanzos
   MCP-Endpunkt per HTTP aktiv sein (`mcp_http`, Standard: an).
2. **Conclave** starten (`conclave server --port 8000`) und in `config.toml`
   eintragen, welche Agents Ticket-Inhalte sehen dürfen:

   ```toml
   [kanzo]
   url = "http://localhost:4242/mcp"   # Standard
   reviewers = ["gpt", "claude"]       # Agent-IDs aus Conclave
   ```

3. **Agent-Host** (z. B. Claude Code) mit beiden MCP-Servern verbinden:

   ```bash
   claude mcp add kanzo -s user -- kanzo mcp
   claude mcp add Conclave -s user -e CONCLAVE_API_URL=http://localhost:8000 -- conclave-mcp
   ```

   `conclave-mcp` nutzt das Agent-Token (`agent.token`); den passenden Befehl
   zeigt `conclave token show --agent`. Das Mensch-Token gehört nie in eine
   Agent-Konfiguration, siehe [Sicherheit](sicherheit.md#mensch--und-agent-zugang).

   In Claude Desktop stehen beide Einträge in `claude_desktop_config.json`
   unter `mcpServers`; Claude Desktop vor dem Bearbeiten ganz beenden, sonst
   überschreibt es die Datei beim Schließen.

## Ein Ablauf als Beispiel

1. **Plan:** Mensch und Agent schreiben einen Plan. Jedes Arbeitspaket wird ein
   Ticket mit Ziel, Ausgangslage, Inhalt und Abnahme. Offene Entscheidungen
   werden eigene Tickets „nur für Menschen“.
2. **Holen:** Der umsetzende Agent nimmt per `next_task` das oberste Ticket aus
   `todo`; Kanzo schiebt es atomar nach `doing`, zwei Agenten erwischen nie
   dasselbe Ticket.
3. **Umsetzen:** Der Agent arbeitet, testet und schreibt Branch, Commits und
   Testergebnis als Kommentar ans Ticket. Dann schiebt er es nach `review`.
4. **Zweitmeinung:** Mit `conclave_consult` (oder `POST /consultations`) holt er
   Meinungen mehrerer Modelle ein. Conclave liest das Ticket selbst und schreibt
   jede Antwort als gekennzeichneten Kommentar zurück; die vollständigen
   Antworten, der Kontext und die Kosten stehen in der Conversation
   `kanzo:<ticket> · <id>`.
5. **Abschluss:** Der Mensch liest Kommentare und Reviews, gibt frei und schiebt
   nach `done`. Korrekturen aus einem Review werden neue Tickets.

Ein automatischer Reviewer lässt sich anschließen: ein eigener Prozess, der das
Board beobachtet und bei jedem Ticket in `review` einen Review-Agenten startet,
der am Ticket kommentiert. Er gehört nicht zu Conclave oder Kanzo. Gib ihm nur
Lesezugriff auf den Code und das Kommentieren in Kanzo, keine Shell und nicht
die Freigaben deines eigenen Agent-Hosts.

## Regeln, die sich bewährt haben

- **Ein Kommentar ist keine Freigabe.** Kanzo hat keine Anmeldung; den Autor
  eines Kommentars kann jeder setzen. Schritte nach außen oder schwer
  umkehrbare Schritte (Push, Veröffentlichung, Löschen, Nutzung von
  Provider-Keys) fragt der Agent direkt beim Menschen, nicht über das Board.
- **Entscheidungen als Tickets „nur für Menschen“.** So holt sie kein Agent per
  `next_task`, und die Antwort steht am Ticket.
- **Nach `done` schiebt der Mensch.** Agenten schieben höchstens nach `review`.
- **Tickets enthalten, was ein Reviewer braucht:** Ziel, Abnahme und die
  betroffenen Teile des Plans, damit niemand fremde Dateien lesen muss.
- **Interne Pläne gehören nicht ins Board-Repository,** wenn es per
  `kanzo sync` mit einem geteilten Git-Remote abgeglichen wird.

## Grenzen

- Die Kennzeichnung von Conclave-Kommentaren ist kein Herkunftsnachweis
  (Kanzo hat keine Anmeldung).
- Agenten laufen unter demselben Benutzer wie Conclave und Kanzo. Die Trennung
  von Mensch- und Agent-Zugang ist nur zusammen mit einer Sperre im Agent-Host
  eine harte Grenze, siehe
  [Sicherheit](sicherheit.md#grenze-gleicher-betriebssystem-benutzer).
- Der Ticket-Inhalt geht bei einer Consultation an die Provider der Reviewer;
  `[kanzo] reviewers` legt fest, an welche.

Details zu den Endpunkten: [API-Referenz, Consultations](referenz/api.md#consultations).
