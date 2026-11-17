# Conclave Board

Board server for teams: tickets, review state, priority, initiatives and control
tickets, with a REST API and no user interface. Licensed under Apache-2.0.

The package is distributed internally (wheelhouse). Conclave Personal bundles it.

```bash
conclave-board serve --port 8200
```

On first start the configuration folder gets `secret.key` and the token files
`api.token` (human), `agent.token` and `reviewer.token`, readable only by the
user. PostgreSQL: `conclave-board serve --dsn postgresql://...` (extra `postgres`);
`CONCLAVE_BOARD_POOL_SIZE` sets the number of connections (default 10).

The server binds to `127.0.0.1` by default. Additional allowed `Host` headers
(comma-separated, optionally with port) go into `CONCLAVE_BOARD_ALLOWED_HOSTS`;
`localhost`, `127.0.0.1` and `[::1]` are always allowed.

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
- **Migrations:** `run_extension_migrations(conn, is_postgres, migrations,
  "<name>_migrations")` runs an extension's own series with its own tracking
  table, with the same transaction and lock rules as the board series.

The core never imports an extension.
