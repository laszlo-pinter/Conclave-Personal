# Release Notes: v0.8.0

The board becomes its own package with a versioned API, and Conclave gets a
built-in automatic reviewer. The board core (`conclave_board`, Apache-2.0) is
bundled with Conclave Personal and has extension points, PostgreSQL support for
several users and the API `/board/v1`. The reviewer reviews tickets moved to
`review` and starts with `conclave desktop` once it is configured.

## Upgrading

```bash
conclave backup
pip install --upgrade "conclave-personal[mcp]"
```

Optional, for the automatic reviewer:

```bash
pip install --upgrade "conclave-personal[mcp,reviewer]"
```

Check these points after the upgrade:

- **Update the server and the MCP clients together.** The new `conclave-mcp`
  talks to `/board/v1`, which a v0.7.0 server does not have. The other way
  round works: an older client still reaches a new server through the alias
  `/board`. Restart Claude Code, Claude Desktop and any other MCP client after
  the upgrade.
- **Migrations on the first start.** The board now has its own migration
  series. On the first start it takes over the six board migrations that ran up
  to v0.7.0 from `_migrations`, without running them again; `_migrations`
  itself stays unchanged. Make the backup before the upgrade.
- **`/board` is deprecated.** Its responses carry `Deprecation` and `Sunset`
  headers; the alias is removed after 1 March 2027. Move your own scripts to
  `/board/v1`. `GET /board/versions` (no token) lists the versions.
- **Agent budget for consultations.** Consultations requested by an agent now
  count towards the daily budget and the limit of concurrent runs from
  `[limits]`. If you let agents run many consultations, they may now get `429`.
- **License.** Conclave Personal is licensed under
  `PolyForm-Noncommercial-1.0.0 AND Apache-2.0`; the board core is Apache-2.0.

## Security

- Consultations count towards the agent budget and the limit of concurrent
  runs, like every other run started by an agent.
- The origin of runs is kept when they are loaded again.
- Texts written by others are labelled in the board tools of `conclave-mcp`
  with their origin and person (`from`, `person`, `title_from`,
  `description_from`). For title and description this is whoever wrote them
  last. The display name `author` is free text and marked as such.
- The automatic reviewer has no shell: it reads the named commits in a separate
  worktree with read-only tools and uses only the reviewer token.

## Board

- **Own package.** `conclave_board` holds the board: domain, service,
  storage, its own migration series and the API. It does not import Conclave
  Personal and needs no provider SDK.
- **API `/board/v1`.** Versioned API with OpenAPI description. Within v1 there
  are only additions; the CI checks for breaking changes. New fields in v1 are
  `assignee` and `actor_name` (the display name of an account, `null` in
  Personal).
- **PostgreSQL** uses a connection pool and real transactions. Rules of the
  kind "check, then write" run under a lock.
- **Extension points** for rules and roles (policy), assignees, events after
  each write, display names and additional migration series and routes.
- **Board tools.** The MCP board tools live in the board package and are shared
  by the MCP servers.
- **Waiting for a review.** `conclave board wait <ticket>` ends with one JSON
  line as soon as the review is decided (`--project` also ends on a pause or
  hint). In the UI, the button "Benachrichtigen" shows a desktop notification
  for review results.

## Reviewer

- **`conclave-reviewer`** (extra `[reviewer]`) reviews every ticket moved to
  `review`: it finds the commits named in the agent's comment, checks them out
  in a separate worktree and runs Claude Code (`claude -p`) without a shell,
  with read-only tools and the reviewer token. Several checkouts per project
  are supported.
- **Starts with `conclave desktop`** as soon as the section `[reviewer]` exists
  in `config.toml`. Without it, nothing happens. `conclave server` never starts
  it. The reviewer ends with the desktop, also after a crash.
- **Status.** The board shows "Reviewer aktiv" or "Reviewer aus".
  `conclave-reviewer status` shows whether it runs, the current ticket, the last
  result and the reviews of the last hour.
- **Hanging reviews.** On start the reviewer releases reviews that stayed
  `running` and reviews them again, and removes leftover worktrees.
- **Moving from a separate watcher.** `conclave-reviewer import-config <old
  config.toml>` takes over the settings; it shows the result before writing.
  It also records the old watcher's lock file: while the old watcher still runs,
  the reviewer does not start.

See [Working with the board](mit-dem-board-arbeiten.md) and the section
[Reviewer](referenz/konfiguration.md#reviewer) of the configuration reference.

## Fixes

- A malformed JSON body returns `400` instead of `500`.
- The workspace list skips broken entries instead of failing.
- A `Retry-After` from a provider is capped at 60 seconds.
- The UI retries the role check of the token up to three times on a short
  network error.
- A lock test that occasionally failed on slow Windows machines is stable.
- Documentation of the tokens and their files.

## Documentation

- [Working with the board](mit-dem-board-arbeiten.md): the built-in reviewer,
  `conclave board wait`.
- [Configuration](referenz/konfiguration.md): section `[reviewer]`.
- [API](referenz/api.md): `/board/v1`, `GET /board/versions`, the reviewer
  endpoints, `actor_name`.
- [CLI](referenz/cli.md): `board wait`, `conclave-reviewer`.

## Known limitations

- Going back to v0.7.0: restore the backup made before the upgrade.
  <!-- L2 (conclave#104): Ergebnis des Rückwegs hier eintragen. -->
- The reviewer needs Claude Code (`claude`) on the same machine.

## Verification

- `python -m pytest`, with and without `CONCLAVE_API_KEY`, including the
  Playwright browser tests
- PostgreSQL tests
- `bandit` and `pip-audit`
- Wheel and sdist built and checked

v0.8.0 remains alpha.
