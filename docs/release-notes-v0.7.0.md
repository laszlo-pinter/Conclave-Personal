# Release Notes: v0.7.0

A hardening release with board improvements. Conclave now enforces stricter
defaults for agents, outgoing connections, files and backups, and the board
gets priorities, initiatives, a separate reviewer role and control tickets.
The UI follows the system's light or dark mode.

v0.7.0 also contains the changes prepared for v0.6.1, which was not published
separately ([Release Notes v0.6.1](release-notes-v0.6.1.md)).

## Upgrading

```bash
conclave backup
pip install --upgrade "conclave-personal[mcp]"
```

Restart the Conclave server and your MCP clients. On start, the database
migrations `013` to `020` run automatically, each in its own transaction. If a
migration fails, the server does not start and names the migration; the
database stays as it was.

Check these points after the upgrade:

- **Provider URLs.** Remote providers need `https`. `localhost` is only
  accepted for Ollama on its port (`CONCLAVE_OLLAMA_PORT`, default `11434`).
  An agent with a URL that is no longer accepted is skipped on start; calling
  it names the reason.
- **Proxy variables.** Requests to providers no longer use `HTTP_PROXY`,
  `HTTPS_PROXY` or `ALL_PROXY` from the environment.
- **Fallback keys** (`OPENAI_API_KEY` and so on) are only sent to the host and
  scheme of their preset. An agent with its own URL on another host, such as a
  gateway, needs its own key entered at the agent.
- **MCP clients** need the agent token. `conclave-mcp` refuses the human token
  and no longer reads `CONCLAVE_API_KEY`. `conclave token show --agent` prints
  the ready-made command.
- **UI login.** The token is kept per browser tab. An existing token is taken
  over once.
- **Agent limits.** `[limits]` sets token budgets per day, concurrent runs and
  a rate limit for agents. The defaults apply without configuration; see
  [Configuration](referenz/konfiguration.md#grenzen-für-agenten).
- **Consultation settings** move from `[kanzo]` to `[consultations]`
  (recommended, the old keys still work with a warning).

## Security

- **Migrations** run atomically and stop the start on failure instead of
  logging a warning and continuing.
- **Access.** The MCP server works only with the agent or reviewer token. The
  app refuses to start without authentication. IDs follow one rule in API and
  services, and path parts are encoded in MCP and UI. A route matrix in the
  tests records which access may call each route.
- **Outgoing connections** go only to public addresses, are checked on every
  request and connect to the checked address. Provider keys are sent in
  headers, not in URLs. Error texts sent to clients and written to the log
  contain neither provider URLs nor keys.
- **Workspace.** Agents create new files but do not overwrite existing ones
  (except under `agents/`). Files are written atomically. The workspace must not
  be or contain the configuration, data, log or backup folder. Reserved Windows
  names and short names are rejected in paths.
- **Directives.** `@workspace/` expansion has limits per message and per
  prompt. `@read()` in model answers is off by default and is enabled by the
  human per conversation.
- **Request sizes.** Requests are limited to 10 MB, board imports to 50 MB, and
  board fields have length limits.
- **Backup and restore** are atomic. A restore that is interrupted is rolled
  back on the next start. Backups are signed; a backup without proven origin is
  only restored after confirmation (`conclave restore --allow-foreign`).
- **Secrets and file permissions.** `secret.key` and the token files are created
  once and readable only by the user. On Windows, `%APPDATA%\Conclave` keeps
  only the user, SYSTEM and the administrators. Existing files with wider
  permissions are tightened on start with a warning. New: `conclave key rotate`
  re-encrypts all data with a new key.
- **Consultations** count their limit atomically and check "human only" again
  before posting.
- **Release chain.** Publishing runs only from a tag that matches the version,
  after the full CI, with pinned build tools and a check of the packages for
  forbidden files.

## Board

- **Priority.** The order of the first column is the priority. Only the human
  changes it; drag and drop is limited to the human access.
- **Claiming.** Agents leave the first column only through `next_task`, either
  the top ticket or a specific one (`conclave_board_next(task="api#12")`).
- **History.** Creating a ticket and every change of status, text, flags,
  priority, tags and position is stored with old and new value and origin.
- **Initiatives.** A project can group tickets into initiatives with their own
  numbers, e.g. `conclave/sich-3`. Managed by the human through
  `conclave board initiative`.
- **Reviewer role.** A separate reviewer token (`conclave token show --reviewer`,
  `conclave-mcp --reviewer`) is the only access that sets the review state.
  Yellow and red reviews send the ticket back to the top of the first column;
  after three red reviews in a row it becomes "human only".
- **Review state on cards.** Running, passed, rework, failed and stuck, each with
  symbol and text. A note above the columns lists tickets waiting for approval.
- **Control tickets.** The human can pause agents or send them a hint without
  ending their session; every board tool response carries it.

## UI

- **Light mode.** The UI follows the system setting. A switch in the sidebar
  (System, Light, Dark) overrides it and is remembered in the browser. Every
  visible text has a contrast of at least 4.5:1 in both modes.
- In dark mode, buttons in purple and red now use dark text for better
  contrast.

## Documentation

- [Security](sicherheit.md): access, file permissions, key rotation, outgoing
  connections, publishing.
- [Working with the board](mit-dem-board-arbeiten.md): priority, initiatives,
  review flow, control tickets.
- [Configuration](referenz/konfiguration.md): `[limits]`, `[consultations]`,
  reviewer token, `CONCLAVE_OLLAMA_PORT`.
- [CLI](referenz/cli.md): `board initiative`, `key rotate`,
  `token show --reviewer`, `restore --allow-foreign`.

## Verification

- `python -m pytest`, with and without `CONCLAVE_API_KEY`, including the
  Playwright browser tests
- PostgreSQL tests
- `bandit` and `pip-audit`
- Wheel and sdist built and checked

v0.7.0 remains alpha.
