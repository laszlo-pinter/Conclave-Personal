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
