# Conclave Board

Board server for teams: tickets, review state, priority, initiatives and control
tickets, with a REST API and no user interface. Licensed under Apache-2.0.

The package is distributed internally (wheelhouse). Conclave Personal bundles it.

```bash
conclave-board serve --port 8200
```

On first start the configuration folder gets `secret.key` and the token files
`api.token` (human), `agent.token` and `reviewer.token`, readable only by the
user. PostgreSQL: `conclave-board serve --dsn postgresql://...` (extra `postgres`).
