# Release Notes: v0.4.0

Conclave v0.4.0 adds consultations: a second opinion from several models on a
ticket from a [Kanzo](https://github.com/emanuele-em/kanzo) board, posted back
to the ticket as labelled comments.

## Upgrading

```bash
pip install --upgrade "conclave-personal[mcp]"
```

Restart the Conclave server. The database is extended automatically
(migration `009_consultations`, SQLite and PostgreSQL). Consultations stay off
until you list reviewers in `config.toml`:

```toml
[kanzo]
url = "http://localhost:4242/mcp"   # default
reviewers = ["gpt", "claude"]       # agent IDs that may see ticket content
```

The server needs the `[mcp]` extra to reach Kanzo.

## New: consultations

- **Ask for a second opinion** with `POST /consultations`
  (`{"task": "api#12", "question": "..."}`) or, for coding agents, the MCP tool
  `conclave_consult`. Conclave reads the ticket itself, asks the reviewers in
  parallel and posts each answer as a comment ending with
  "— Zweitmeinung von GPT (openai, gpt-5.6) über Conclave, nicht geprüft".
  The full answers, context reports and costs are in the conversation
  `kanzo:<task> · <id>`.
- **Status and retry:** `GET /consultations/<id>` (status, reviewers with
  provider and model, deliveries), `GET /consultations?source_ref=...`,
  `POST /consultations/<id>/retry` (deliver again without model calls;
  `rerun: true` asks the models again). MCP tool `conclave_get_consultation`.
- **Background worker:** consultations run in a server thread. After a restart,
  interrupted consultations are marked `interrupted`; stored answers that were
  not delivered yet are delivered automatically, models are never called again
  automatically.
- **Limits:** reviewers only from `[kanzo] reviewers`, at most
  `max_per_hour` (default 3) consultations per ticket and hour, comments
  truncated to `comment_max_chars` (default 2,000) before the closing line.

## Security

Ticket content is untrusted. Conclave puts it into a data block with a random
delimiter, does not insert `@workspace/` files and does not execute
`@save`/`@read` from reviewer answers, and only calls Kanzo's `get_task` and
`add_comment`. Earlier Conclave comments are left out unless
`include_previous: true`. Tickets marked "human" in Kanzo are rejected when
asked through the MCP tool. The Kanzo address comes only from `config.toml`.

Known limits, see [security](sicherheit.md#consultations-kanzo):

- The label of a comment is not proof of origin: Kanzo has no login, anyone can
  write the same author and closing line.
- The human-only check covers agents using the MCP tools; an agent that can read
  `api.token` can call the REST API directly.

## Verification

- `python -m pytest` with tests against an in-process fake Kanzo that
  reproduces Kanzo's output format, including an injection ticket answered by a
  worst-case reviewer, restart behaviour and claim races (SQLite threads and
  PostgreSQL connections)
- Kanzo adapter checked against a real Kanzo
- End-to-end run with a real Kanzo and real models (Anthropic preset, OpenAI
  native): REST and MCP consultations, human-only ticket via MCP rejected, limit,
  injection ticket without effect, server stopped mid-run and restarted (manual)
- Wheel built and installed in a fresh environment

v0.4.0 remains alpha.
