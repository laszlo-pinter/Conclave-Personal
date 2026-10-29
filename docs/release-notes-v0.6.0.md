# Release Notes: v0.6.0

Conclave v0.6.0 has its own board for work packages: projects, tickets with
status, comments, tickets for humans only and `next_task` for agents, in the
web UI, the REST API and `conclave-mcp`. Who comments or changes a ticket
comes from the token, so the board enforces what used to be an agreement:
only the human moves tickets to `done`. Consultations now read tickets from
this board by default; an external Kanzo stays possible.

## Upgrading

```bash
pip install --upgrade "conclave-personal[mcp]"
```

Restart the Conclave server. On start it migrates the database (SQLite and
PostgreSQL): `012_board` adds the board tables. Existing data is not changed.

- **SQLite 3.35 or newer is required** (for `UPDATE … RETURNING`). Python 3.11
  and 3.12 usually ship a newer version; check with
  `python -c "import sqlite3; print(sqlite3.sqlite_version)"`. With an older
  SQLite the server does not start and says so.
- **Consultations change their source.** Without `[board] source`,
  consultations now read tickets from the own board, unless a Kanzo address is
  set explicitly (`[kanzo] url` in `config.toml` or `CONCLAVE_KANZO_URL`). If
  you use consultations with Kanzo on the default address, add

  ```toml
  [board]
  source = "kanzo"
  ```

  Consultations stored before the upgrade keep the source `kanzo`; while the
  source is `internal`, `GET /consultations?source_ref=…` lists only those
  with source `board`.
- **MCP clients:** restart them to see the six new board tools. The MCP setup
  itself is unchanged (agent token, see v0.5.0).

### Moving a Kanzo board

```bash
kanzo export -f json -o board.json
curl -X POST http://localhost:8000/board/import \
  -H "Authorization: Bearer <human token>" -H "Content-Type: application/json" \
  --data-binary @board.json
```

PowerShell:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/board/import `
  -Headers @{Authorization = "Bearer <human token>"} -ContentType "application/json" `
  -InFile board.json
```

- Set `[board] statuses` to Kanzo's columns first if you changed them there;
  unknown statuses reject the whole import.
- The whole export is checked before anything is written (`400
  ImportFormatError`); at most 50 MB (`413 ImportTooLarge`).
- Ticket numbers are kept (`conclave#7` stays `conclave#7`).
- Importing again skips existing tickets (`tasks_skipped`, `skipped_refs`). It
  does **not** add new comments to tickets imported before.
- Imported comments have no proven origin (`origin: null`, shown as
  "unknown"), even if the export names an author. Imported tickets have no
  history. Images and repository links are not imported.

## New: the board

- **Web UI.** A new "Board" area: columns from `[board] statuses`, cards with
  reference, title, tags and the human-only marker, drag and drop between and
  within columns, a ticket view (Markdown description, comments with origin,
  history, status, human-only switch, new comment), new ticket, search,
  project filter, "show done" and live refresh when an agent changes
  something.
- **Rules from the token.** Comments and history carry `origin` (`human`,
  `agent`, `system` for Conclave itself, `null` for imported) and `actor_id`,
  set by the server. With the agent token:
  - no moving to or out of the last column, done tickets are read-only (except
    for comments), no creating done tickets,
  - human-only tickets are read-only and never handed out by `next_task`; the
    marker can be set but not removed,
  - no deleting, no project management, no import.
  Comments from agents, from Conclave and imported ones are immutable; the
  human can edit and delete their own.
- **History.** Every change of status, title, description and the human-only
  marker is stored with its full old and new value, origin and time.
- **`next_task`** moves the top free ticket of the first column to the second
  atomically; two agents never get the same ticket.
- **REST API** under `/board` (18 routes), see the
  [API reference](referenz/api.md#board). `PATCH` on a ticket takes `title`,
  `description`, `tags`, `status`, `human` and `index` (position in the
  column).
- **MCP.** Six tools: `conclave_board_list`, `conclave_board_get`,
  `conclave_board_next`, `conclave_board_create`, `conclave_board_update`,
  `conclave_board_comment`. Their answers mark ticket texts as data, not
  instructions. The server instructions describe the workflow.
- **Storage.** Titles, descriptions, tags, comments and history values are
  encrypted like messages. With SQLite, board data is part of the normal
  backup (`POST /backup`).
- **Configuration.** `[board] statuses` (default `todo`, `doing`, `review`,
  `done`) and `[board] source` (`internal` or `kanzo`), see
  [configuration](referenz/konfiguration.md#board).

## Changed: consultations

- Tickets come from the own board by default (see Upgrading). Answers are
  written as comments with origin `system`, shown as "second opinion (model)",
  also when a human asked. The conversation is named `board:<ticket> · <id>`.
- In the own board a comment cannot pretend to be a Conclave answer: an agent
  comment named like Conclave does not count as a delivery and appears in the
  prompt with its origin.
- The human-only check is unchanged: the agent token is rejected through MCP
  and through direct REST calls (`403 HumanOnlyTicket`).

## Fixed

- The OpenAPI spec missed `PATCH` routes (the generator only knew `GET`,
  `POST`, `PUT` and `DELETE`); the CORS preflight now allows `PATCH` for
  configured origins.

## Documentation

- [Working with the board](mit-dem-board-arbeiten.md) (German) replaces
  "Working with Kanzo": rules, setup, the UI, an example flow, the Kanzo import
  and Kanzo as an external board.
- [Security](sicherheit.md#board), [API reference](referenz/api.md#board) and
  [configuration](referenz/konfiguration.md#board) describe the board.
- The board is a separate implementation; Conclave contains no code from
  Kanzo.

## Breaking changes

- Consultations without `[board] source` and without an explicit Kanzo
  address read from the own board instead of Kanzo (see Upgrading).
- SQLite older than 3.35 is no longer supported.
- `conclave-mcp` has 22 tools instead of 16.

## Known limits

- The [limit of the same operating-system user](sicherheit.md#grenze-gleicher-betriebssystem-benutzer)
  from v0.5.0 applies to the board too: an agent that can read `api.token`
  can use the human access and move tickets to `done`.
- Renaming a column in `[board] statuses` does not change stored tickets;
  tickets with a status that is no longer configured are hidden in the UI
  until the column is back.
- Search runs in memory, because ticket texts are encrypted; it is meant for
  boards of personal size.
- If a database migration fails, the server logs a warning and keeps starting
  (unchanged behaviour); check the log after upgrading.

## Verification

- `python -m pytest`, with and without `CONCLAVE_API_KEY`, including bundled
  security tests for the board (every rule against the agent token, origin
  fields in the body, hostile imports, parallel `next_task` over REST, ticket
  texts with instructions), the consultation tests against Kanzo and against
  the own board, and browser tests for the board area (display, drag and drop,
  filtered Markdown, origin labels, live refresh)
- PostgreSQL tests against a real PostgreSQL (pgserver)
- Wheel and sdist built; fresh install of the wheel with `[mcp]`
- Upgrade of a database created by v0.5.1 from PyPI: migration `012_board`
  ran, conversations, messages, agents and consultations kept
- End-to-end run with the installed wheel and a real Conclave server:
  `conclave-mcp` over stdio with the agent token took a ticket with
  `next_task`, commented, moved it to `review`; moving it to `done` was
  rejected; a Kanzo export was imported with the human token
- `pip-audit` and `bandit`

v0.6.0 remains alpha.
