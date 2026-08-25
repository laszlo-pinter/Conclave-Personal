# Release Notes: v0.1.19

Conclave v0.1.19 adds the first provenance layer for deterministic workspace
tool actions. It records what the backend actually did when an agent uses
workspace read/write directives.

Conclave still does not verify the truth of model answers. The human decides.
This release validates backend actions, not factual correctness.

## Highlights

- `@save(...)` now creates a `workspace.save` tool event with status, message
  link, participant link, relative output path, byte count, and error metadata.
- `@read(...)` now creates a `workspace.read` tool event while preserving the
  visible file-content behavior.
- Tool events are persisted in SQLite and Postgres through a dedicated
  `tool_events` table.
- Conversation deletion now removes related tool events together with the
  conversation.
- The desktop UI renders tool events as separate message rows and hides raw
  `[tool_event:<id>]` markers.
- `GET /conversations/<conversation_id>/tool-events` exposes recorded tool
  events through the local API.
- Conversation export now includes tool events globally and per message.
- Runtime logs now include sanitized `tool_event.record` entries for persisted
  workspace tool events.
- OpenAPI output and API reference documentation now include the tool-event
  endpoint.

## Provenance Scope

This release tracks deterministic backend actions:

- which tool was executed
- which participant triggered it
- which message references it
- whether it succeeded or failed
- which relative workspace path was affected

It does not claim that an agent's answer is true. It only records whether
Conclave performed the local read/write action the message refers to.

## Verification

The v0.1.19 release surface was verified locally with:

- `python -m pytest`
- workspace directive tests
- API and OpenAPI contract tests
- export tests
- logging tests
- distribution configuration checks

v0.1.19 remains alpha.
