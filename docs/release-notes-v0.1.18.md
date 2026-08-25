# Release Notes: v0.1.18

Conclave v0.1.18 is a focused stability patch for local Personal usage. It
improves cleanup, provider diagnostics, DeepSeek support, server logs, and a
small UI visibility issue.

## Highlights

- Conversation deletion now removes dependent runs, usage records, and audit
  entries before deleting the conversation.
- SQLite and Postgres delete paths now persist conversation deletion reliably.
- Server startup now writes Conclave logs to the runtime log directory.
- Windows CLI output falls back to ASCII symbols when the console cannot encode
  checkmark or cross characters.
- DeepSeek agents now receive `DEEPSEEK_API_KEY` through the same preset-based
  adapter path used by real participant invokes.
- The agent connection test now uses the same adapter registry path as normal
  conversation invokes and invalidates stale cached adapters first.
- DeepSeek provider errors now include the provider response body for easier
  diagnosis.
- `httpx` is now a base runtime dependency because the universal provider
  adapter imports it directly.
- DeepSeek model selection now exposes API identifiers such as
  `deepseek-v4-flash` and `deepseek-v4-pro`.
- Existing `DeepSeek-V3` agent configs are mapped to `deepseek-v4-flash` for
  compatibility.
- Desktop UI scrollbars are lighter and easier to see.

## Runtime Logs

Server and desktop startup now announce and write to:

```text
<local runtime data>/Conclave/logs/conclave-server.log
```

On Windows this is normally:

```text
%LOCALAPPDATA%\Conclave\logs\conclave-server.log
```

## DeepSeek

DeepSeek should be configured with:

```text
provider: deepseek
preset: deepseek
model: deepseek-v4-flash
```

`DeepSeek-V3` is treated as a compatibility alias and is mapped internally to
`deepseek-v4-flash`.

## Verification

The v0.1.18 release surface was verified locally with:

- `python -m pytest`
- provider preset tests
- adapter error handling tests
- UI surface tests
- distribution build checks

v0.1.18 remains alpha.
