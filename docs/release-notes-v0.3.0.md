# Release Notes: v0.3.0

Conclave v0.3.0 shows which context was actually sent to the provider with
every model call, and what the next call would send.

## Upgrading

```bash
pip install --upgrade "conclave-personal[mcp]"
```

Restart the Conclave server. The database is extended automatically
(migrations `007_context_reports` and `008_agent_max_messages`, SQLite and
PostgreSQL); existing data is kept. No configuration change is needed.

## New: context transparency

- **Context chip under every model answer**, for example
  "Kontext: 25/80 Nachrichten · 2 Dateien · ca. 6,400 Token (abgerechnet
  6,912)". It is highlighted when messages were omitted and red for large
  contexts without truncation (from about 50,000 tokens). A click shows the
  details: the omitted range with a jump to it, the anchor message, the
  effective limit, the parts of the system prompt, context files, files
  inserted with `@workspace/`, earlier `@read()` results, rejected files with
  the reason, estimated and billed tokens, and the number of attempts.
- **Preview before a call:** the input bar shows what the next call for the
  selected participant would send ("Nächster Aufruf: Agent sieht 25 von 80
  Nachrichten"). The orchestration and auto-loop dialogs show it per
  participant. The preview never calls the provider and stores nothing.
- **Per-agent message limit:** new agent field "Max. Nachrichten" (UI under
  "Erweitert", CLI `--max-messages`, API `max_messages`). Empty uses the global
  default (`CONCLAVE_MAX_MESSAGES`, preset agents only), `0` disables
  truncation, a number limits the messages per call while keeping the first
  user message as anchor. It applies to preset agents and native
  Anthropic/OpenAI agents. Editing an agent without the field keeps the stored
  value.
- **Stored reports:** every model call stores its context report (metadata
  only: counts, sequence numbers, file paths and sizes, never the prompt),
  linked to its run and answer. Failed calls keep their report too, which helps
  with "context too long" errors. Reports are deleted with the conversation
  and included in the conversation export (`context_reports`).
- **API:** model messages in `GET /conversations/<id>` and the invoke,
  orchestration, parallel-stream and auto-loop responses carry a compact
  `context` object. New endpoints:
  `GET /conversations/<id>/messages/<message_id>/context` (full report) and
  `GET /conversations/<id>/participants/<participant_id>/context-preview`.
  See the [API reference](referenz/api.md#kontext-reports).

## Behaviour changes

- **Native agents get the same system prompt as preset agents.** Agents with
  provider `anthropic` or `openai` without a preset previously received only
  their own prompt and the raw chat rules: `context_files:` were never loaded
  (the line went to the model verbatim) and the workspace hints explaining
  `@read()` and `@save()` were missing. They now get context files and
  workspace hints, so their system prompt is longer and costs more tokens per
  call.

## Fixes

- **Token counts of concurrent calls.** Usage was read from an adapter
  attribute after the call; two simultaneous calls of the same agent (for
  example in parallel orchestration) could swap their token counts. Usage is
  now returned with the answer.
- **Retries send the same request.** A retried call rebuilt the system prompt
  and context files on every attempt; now the request is built once and every
  attempt sends exactly that request.
- **A limit of 1 message** returned the whole history; it now sends the last
  message.

## For developers

- `ModelAdapter.complete()` returns `Completion(text, usage, report)`; streams
  end with a `Completion` without text. Adapters returning a plain `str` keep
  working (without usage). The adapter attribute `last_usage` is gone.
- New CI job `postgres` runs `tests/persistence` against PostgreSQL 16 (image
  pinned by digest), including the migration of a v0.2.3 database.

## Verification

- `python -m pytest` including Playwright browser tests (context chip, details,
  preview, no CSP violations) and the PostgreSQL tests against PostgreSQL 16.2
- Wheel built and installed in a fresh environment: server smoke test and
  `conclave-mcp` handshake
- `bandit`: no findings

v0.3.0 remains alpha.
