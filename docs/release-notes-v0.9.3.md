# Release Notes: v0.9.3

In this release the human can restart a review without moving the ticket. The
board page in Personal gets the compact toolbar of the board server. The test
suite no longer depends on the machine it runs on.

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
wheel of this version. Update the reviewer together with the server: a
reviewer before 0.9.3 does not review tickets in the new state `requested`.

- **No migration.** The database schema is unchanged. The new review state is
  stored in the existing column.
- **Update the server and the MCP clients together**, as usual. Restart Claude
  Code, Claude Desktop and any other MCP client after the upgrade.

## Restart a review

A ticket that is already in `review` used to be reviewed again only if it left
the column and came back after a pause. Now:

- **"Review neu starten"** in the task view restarts the review. The button is
  shown only to someone with the right to approve in the project, for a ticket
  in `review` that is not "nur für Menschen" and has no review running.
- The ticket stays in `review` and gets the new review state **`requested`**,
  shown as "↺ Review angefordert". The red counter is kept, because a request
  is not a result.
- The reviewer schedules each request once, even without a column change.
  `max_reviews_per_hour` still applies. On its first run it does not skip
  requested tickets.
- **Removing "nur für Menschen"** from a ticket in `review` now requests the
  review by itself. Before, the reviewer had skipped such a ticket as human-only
  and never came back to it.

## Board API

All changes only extend `/board/v1`:

- `POST /board/v1/projects/<slug>/tasks/<n>/review/request` with an empty body
  requests a review. It needs the right to approve; the agent and the reviewer
  get `403`. It answers `409` with `NotInReview`, `HumanOnlyTicket` or
  `ReviewRunning`.
- `review.state` can now also be `requested`. `review.at` is then the time of
  the request.
- `GET` on a task also returns `can_approve`: whether this access has the right
  to approve in the project.

## Board page in Personal

The board page in Personal has the same compact toolbar as the standalone board
page of the board server: the title, then project, search and "Erledigte
zeigen", then the actions. "Erledigte zeigen" moved from the sidebar into the
toolbar. Both pages share the styles in `board.css`.

## Configuration

Without a `config.toml`, the default SQLite path is now resolved when the
configuration is loaded, like the path of `config.toml` itself. Before, it was
fixed when the module was imported. The path is the same in normal use.

## Tests

The test suite is shielded from the machine. Before each test, a fixture removes:

- every `CONCLAVE_*` variable except `CONCLAVE_TEST_*`
- every provider key (`*_API_KEY`)
- `CLAUDE_CODE_OAUTH_TOKEN`

It also moves the user folders and data paths into the test directory, for
child processes too. Before, a machine with `CONCLAVE_DB_PROVIDER=postgres` made
a desktop test connect to the real database.

## Verification

- `python -m pytest`, including the Playwright browser tests, once with the
  Postgres variables of a real machine set and once without them. The real
  database was unchanged afterwards, counted before and after.
- PostgreSQL tests
- `bandit`, `pip-audit`, `import-linter` and the OpenAPI diff of `/board/v1`
- Wheel and sdist of Conclave Personal and the wheels of the board core and the
  reviewer built and checked
- Fresh installation from wheel and sdist with `[mcp,reviewer]` and a smoke
  test; upgrade from v0.9.2 on a copy of a real database
- The team package tested against this core and this reviewer

v0.9.3 remains alpha.
