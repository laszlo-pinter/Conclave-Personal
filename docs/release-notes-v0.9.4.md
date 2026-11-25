# Release Notes: v0.9.4

In this release an agent or a human can wait for a reply on a ticket:
`conclave board wait <ticket> --comments` ends on the first new comment of
someone else. Creating a ticket past the first column is now checked like
moving it there. The built-in reviewer can run `codex exec` instead of
`claude`, as an experiment.

## Upgrading

```bash
conclave backup
pip install --upgrade "conclave-personal[mcp,reviewer]"
```

Without the automatic reviewer:

```bash
pip install --upgrade "conclave-personal[mcp]"
```

`conclave backup` saves the SQLite database. If you run Conclave on
PostgreSQL, back up with `pg_dump` and keep a copy of `secret.key`.

For a reviewer against a remote board server, install the `conclave-reviewer`
wheel of this version.

- **No migration.** The database schema is unchanged.
- **Update the server and the MCP clients together**, as usual. Restart Claude
  Code, Claude Desktop and any other MCP client after the upgrade.

## Wait for a reply

```bash
conclave board wait <ticket> --comments
```

- The command ends on the first new comment at the ticket that does not come
  from the own access. It prints one JSON line with `"event": "comment"`, the
  comment's ID and its origin (`from`, `origin`, `person`), never its text. The
  agent reads the comment afterwards itself, as data.
- It also works on tickets in `done`, so a ticket in `done` can serve as a chat
  with an agent.
- Like the other forms of `board wait`, it ends with exit code 2 after
  `--timeout` minutes. `--comments` cannot be combined with `--project`.
- The waiting logic now lives in the board core (`conclave_board.wait`), so the
  team package uses the same code.

## Creating a ticket past the first column

A human could already create a ticket directly in a later column
(`status` on `POST /board/v1/tasks`). It is now checked like moving a ticket
there:

- Creating a ticket directly in the **last column** needs the right to
  approve. In Personal the human has that right, so nothing changes there.
  Agents still create tickets only in the first column.
- A board server with its own rules (the new hook
  `BoardPolicy.check_create`) applies them on create too. The check runs under
  the same lock as a move, after the first column only.
- Creating in the last column is recorded in the audit log as `create_done`,
  without the ticket's contents.

## Board API

All changes only extend `/board/v1`:

- `GET /auth/whoami` also returns `actor_id`, the account behind the token,
  where the server has accounts. Personal has none and answers as before.
- The change counter of `/changes` now also counts new comments, so a waiting
  client notices them.
- `POST /board/v1/tasks` with `status` set to the last column answers `403`
  without the right to approve.

## Reviewer: Codex as a second backend (experimental)

With `agent = "codex"` in `[reviewer]`, the built-in reviewer runs
`codex exec` read-only instead of `claude`. Claude stays the default.

- New keys: `agent`, `codex_exe`, `codex_model` and `codex_pass_env`.
- The system prompt and the request go over stdin. As with `claude`, no ticket
  text reaches the command line.
- Codex gets a clean environment: paths and system variables, `CODEX_HOME` and
  whatever `codex_pass_env` adds. It gets no `CONCLAVE_*` variables and no keys.
- **Run it only under a separate Windows account without credentials.** Codex
  always has a shell. `-s read-only` only blocks writes, and it can read
  whatever the account can read. The start log and `conclave-reviewer status`
  warn when the account can read the human or the agent token.
- The dry run and `status` show the Codex call and its version.

See [configuration](referenz/konfiguration.md#reviewer) for the details.

## Verification

- `python -m pytest`, including the Playwright browser tests
- PostgreSQL tests
- `bandit`, `pip-audit`, `import-linter` and the OpenAPI diff of `/board/v1`
- Wheel and sdist of Conclave Personal and the wheels of the board core and the
  reviewer built and checked
- Fresh installation from wheel and sdist with `[mcp,reviewer]` and a smoke
  test; upgrade from v0.9.3 on a copy of a real database
- The team package tested against this core and this reviewer

v0.9.4 remains alpha.
