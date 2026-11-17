# Conclave Board

Board server for teams: tickets, review state, priority, initiatives and control
tickets, with a REST API and no user interface. Licensed under Apache-2.0.

The package is distributed internally (wheelhouse). Conclave Personal bundles it.

```bash
conclave-board-server serve --port 8200
```

On first start the configuration folder gets `secret.key` and the token files
`api.token` (human), `agent.token` and `reviewer.token`, readable only by the
user. PostgreSQL: `conclave-board-server serve --dsn postgresql://...` (extra `postgres`);
`CONCLAVE_BOARD_POOL_SIZE` sets the number of connections (default 10).

The server binds to `127.0.0.1` by default. Additional allowed `Host` headers
(comma-separated, optionally with port) go into `CONCLAVE_BOARD_ALLOWED_HOSTS`;
`localhost`, `127.0.0.1` and `[::1]` are always allowed.

Behind a proxy (T7): `X-Forwarded-For` and `X-Forwarded-Proto` count only on
connections from the addresses or networks in `CONCLAVE_BOARD_TRUSTED_PROXIES`
(comma-separated); from any other source they are dropped. The rate limit counts
per token (without a valid token per address); after 10 failed logins per minute
an address gets 429 until the minute ends. `create_board_app` takes
`trusted_proxies`, `auth_failure_limit` and `account_rate_limit` (requests per
`actor_id` across all its tokens, off by default).

## Extension points

Extensions (such as an internal team package) plug into the board without
changes to its rules:

- **Token check:** `create_board_app(board, auth_service)` takes any object with
  `authenticate(token) -> Principal | None`. A `Principal` may carry the account
  (`actor_id`, recorded as origin in history and comments) and the projects it
  may see (`projects`; other projects answer 404, lists and `next` skip them).
  Without them it behaves as before (three fixed tokens).
- **Routes:** `create_board_app(..., blueprints=[...])` adds Flask blueprints. They
  pass the same authentication and access layer; agent and reviewer tokens are
  not allowed on them (default deny).
- **Rules:** `BoardService(..., policy=...)` takes a `BoardPolicy`. It decides who
  may write, comment, approve (done, rank, delete, initiatives, removing "humans
  only"), release stuck tickets and create control tickets per scope (`mine`,
  `project`, `all`), which tickets `next` may hand out and whom it assigns, extra
  checks on status changes under a named lock (`locked_key`), and receives
  events (approval, rank, control, release) for an audit log. The default
  `PersonalPolicy` keeps the rules of Conclave Personal. The fixed rules for
  agents and the reviewer always apply.
- **Events:** `BoardService.add_listener(fn)` calls `fn(BoardEvent)` after every
  successful write: ticket or control ticket created, status changed, review
  result, assignee changed, comment written, hint acknowledged. An event carries
  no contents (no title, description or comment text), only reference, project,
  origin, account, time and small metadata such as old and new status
  (`conclave_board.application.events`). Listeners run in the request and must
  return quickly; an exception is logged and never fails the write.
- **Migrations:** `run_extension_migrations(conn, is_postgres, migrations,
  "<name>_migrations")` runs an extension's own series with its own tracking
  table, with the same transaction and lock rules as the board series.

The core never imports an extension.
