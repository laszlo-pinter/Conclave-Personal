# Release Notes: v0.5.0

Conclave v0.5.0 separates human and agent access. Agents get their own token
with restricted rights; the human-only check of consultations now depends on
the token instead of a field in the request. This closes the known gap from
v0.4.0, within the limit described under [Known limits](#known-limits).

## Upgrading

```bash
pip install --upgrade "conclave-personal[mcp]"
```

Restart the Conclave server. On start it

- creates a second token, `agent.token`, next to `api.token` in the
  configuration directory (unless `CONCLAVE_AGENT_KEY` is set),
- migrates the database (SQLite and PostgreSQL): `010_consultation_channels`
  renames stored channels `rest`/`mcp` to `human`/`agent`, `011_message_origin`
  adds `messages.origin` (existing messages stay `null`, meaning unknown).

Your existing `api.token` keeps working for the UI, the REST API and the CLI.

**Check your MCP setup.** `conclave-mcp` now uses only the agent token:

- Registered with `claude mcp add Conclave -s user -e CONCLAVE_API_URL=... -- conclave-mcp`
  (no token in the configuration): nothing to do. Restart the MCP client;
  `conclave-mcp` reads `agent.token` itself.
- `CONCLAVE_API_KEY` in the MCP `env` block: remove it. If the server runs with
  an explicit `CONCLAVE_AGENT_KEY`, put that value into the MCP `env` block
  instead. With the human token, `conclave-mcp` still works for old setups but
  prints a warning on stderr, because agents then have full access.

`conclave token show --agent` prints the token path and a ready-made
`claude mcp add` command (the value only with `--reveal`).

## New: separate human and agent access

- **Two tokens.** Human: `CONCLAVE_API_KEY` / `api.token`. Agent:
  `CONCLAVE_AGENT_KEY` / `agent.token`. New tokens start with `cvh_` and `cva_`;
  the role comes only from where the token is configured. An agent token equal
  to the human token gives no agent access. `GET /auth/whoami` returns the
  role.
- **Restricted agent access.** With the agent token only the routes the MCP
  tools need are allowed; everything else, including every `DELETE` and every
  new route, returns `403 {"type": "HumanOnly"}`. Agents cannot change
  settings, manage agents, see backups or logs, retry consultations, or add
  participants of type `user`.
- **Consultations.** The channel (`human`/`agent`) comes from the token. Tickets
  marked "human" in Kanzo are rejected for the agent token through the MCP tool
  and through direct REST calls alike.
- **Message origin.** Messages posted through the API carry `origin: human` or
  `origin: agent`; the UI marks agent messages "via agent". Models do not see
  the origin; their prompt and roles are unchanged.
- **MCP server.** Reads `CONCLAVE_AGENT_KEY` or `agent.token`, never
  `api.token`; checks its role once with `GET /auth/whoami` and warns for
  `human`. 16 tools: `conclave_delete_conversation` and
  `conclave_delete_file` are gone (deleting is for the human only).

## Documentation

- New page [Working with Kanzo](mit-kanzo-arbeiten.md) (German): how Kanzo
  and Conclave complement each other, setup with the agent token, an example
  flow from plan to `done`, and rules that proved useful.

## Breaking changes

- `conclave-mcp` no longer reads `api.token` (see Upgrading).
- `POST /consultations` rejects a `channel` field with
  `400 ChannelNotAllowed`. Stored and returned channel values are now
  `human`/`agent` instead of `rest`/`mcp`.
- `POST /conversations/<id>/participants` rejects a `type` other than `model`
  or `user` with `400` (before, any other value silently became `user`).
- The MCP tools `conclave_delete_conversation` and `conclave_delete_file` were
  removed.
- `CONCLAVE_AGENT_KEY` and `CONCLAVE_AGENT_TOKEN_FILE` are reserved: they are no
  longer read as agent definitions `CONCLAVE_AGENT_<ID>` (an agent seeded from
  them, with ID `KEY` or `TOKEN_FILE`, is no longer created).

## Known limits

See [security](sicherheit.md#mensch--und-agent-zugang):

- Agents run as the same operating-system user as Conclave. An agent with a
  shell can read `api.token` and then use the human access. Separate tokens are
  a hard boundary only together with a block in the agent host, for example
  `Read` deny rules and the sandbox in Claude Code. On native Windows, Claude
  Code runs commands without a sandbox, so `Read` deny rules there do not stop
  a script that opens the file itself.
- Messages written without a token (CLI, consultation prompts) have
  `origin: null`.
- If a database migration fails, the server logs a warning and keeps starting
  (unchanged behaviour); check the log after upgrading.

## Verification

- `python -m pytest`, including bundled security tests for the access
  separation (channel and other body fields on a human-only ticket, new and
  human-only routes, path tricks, altered and swapped tokens) and a browser
  test for the "via agent" label
- PostgreSQL tests against a real PostgreSQL (pgserver)
- Wheel and sdist built; fresh install of the wheel with `[mcp]`
- Upgrade of a database created by v0.4.0 from PyPI: migrations `010` and
  `011` ran, a stored channel `mcp` became `agent`, the old message has
  `origin: null`, the old `api.token` without prefix still works as human
  token, `agent.token` was created
- End-to-end run with the installed wheel, a real Conclave server and a
  scratch Kanzo board: `conclave-mcp` over stdio with the agent token (16
  tools, message `origin: agent`, consultation on a human-only ticket rejected
  with 403, no warning); the same ticket via direct REST with the agent token
  rejected (403, with `channel` 400, with an additional human `X-API-Key` still
  403), nothing stored and no comment; accepted with the human token;
  `conclave-mcp` with the human token prints the warning without the token
- `pip-audit` and `bandit`

v0.5.0 remains alpha.
