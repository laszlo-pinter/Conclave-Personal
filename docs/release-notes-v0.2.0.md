# Release Notes: v0.2.0

Conclave v0.2.0 is a security and robustness release based on the code review
of 2026-10-26. It closes a stored XSS in the
desktop UI, requires a token for the local API, ships all UI assets with the
package and makes the server safe under parallel requests. It also contains
breaking changes for API clients - read **Upgrading** before updating.

## Highlights

- Model output is sanitized before it is rendered in the browser.
- The local API always requires a token; the desktop UI logs in automatically.
- No external resources at runtime: fonts and libraries are part of the package,
  and every response carries a Content-Security-Policy.
- One SQLite connection per thread and a production WSGI server (waitress).
- The settings page shows the server log and lets you change the rate limit.

## Upgrading

```bash
pip install --upgrade conclave-personal
```

- **API token.** If `CONCLAVE_API_KEY` is not set, the server creates a random
  token on first start and stores it in `api.token` in the configuration
  directory (Windows: `%APPDATA%\Conclave\`, Linux: `~/.config/conclave/`;
  override with `CONCLAVE_API_TOKEN_FILE`). `conclave desktop` and
  `conclave web` open the browser with the token, `conclave-watch` and the MCP
  server read the token file automatically. Your own scripts must send
  `Authorization: Bearer <token>`.
- **POST requests** need `Content-Type: application/json` (an empty body is
  `{}`) or the header `X-Conclave-Client`; otherwise the API answers `415`.
- **Host header.** Only `localhost`, `127.0.0.1`, `[::1]` and entries from
  `CONCLAVE_ALLOWED_HOSTS` are accepted (`421` otherwise). Binding to a
  non-loopback address now requires `CONCLAVE_API_KEY` and
  `CONCLAVE_ALLOWED_HOSTS`.
- **`POST /restore`** only accepts a backup file name from the backup directory:
  `{"backup": "<name>"}` (see the new `GET /backups`). `backup_path` is no longer
  supported. The workspace is kept by default; clearing it requires
  `"replace_workspace": true` and `"confirm": "replace-workspace"`. The CLI
  command `conclave restore` still accepts any path and replaces the workspace
  unless `--keep-workspace` is given.
- **The UI only talks to the server it was loaded from** (`connect-src 'self'`).
  A different API URL in the key dialog is blocked by the browser.
- **PostgreSQL users:** the encryption key is now resolved like for SQLite
  (`CONCLAVE_SECRET_KEY`, `CONCLAVE_SECRET_KEY_FILE`, then the platform
  default) instead of `~/.conclave/secret.key`. Move that file or point
  `CONCLAVE_SECRET_KEY_FILE` at it, otherwise stored agent keys cannot be
  decrypted.
- **New dependency:** `waitress`.

## Security

- Model output is rendered through DOMPurify with a restrictive allowlist
  (text and structure only; no scripts, images, SVG, forms, `style`/`id`/event
  attributes). Links are limited to `http(s)`, `mailto` and `#` and open with
  `noopener noreferrer`. Without DOMPurify only escaped text is shown.
- All `innerHTML` sinks in the UI are audited and annotated; values from the API
  are escaped (including quotes in attributes). A test rejects new sinks
  without justification.
- marked, highlight.js, DOMPurify, Swagger UI and the Syne / DM Sans fonts are
  shipped with the package; Google Fonts, cdnjs and unpkg are no longer used.
  Versions, licenses and checksums are listed in `THIRD_PARTY.md`.
- Every response carries a Content-Security-Policy (no inline scripts, no
  `eval`, no `<style>` blocks, no framing), `Referrer-Policy: no-referrer` and
  a `Permissions-Policy`.
- Mandatory API token, Host allowlist (DNS rebinding) and CSRF protection for
  POST requests (see **Upgrading**). The token file is readable only by the
  current user.
- Restore via the API is limited to the backup directory.
- `context_files:` in the chat rules is now limited to the workspace: hidden
  paths and the agent read limit apply, like for `@workspace/` and `@read()`.
  Previously it could read files outside the workspace.
- `CONCLAVE_DEBUG` (Werkzeug debugger) is rejected in `production` mode and with
  a non-loopback `CONCLAVE_HOST`.
- `conclave-watch` only accepts `http(s)` API URLs.

## Robustness

- SQLite uses one connection per thread (WAL, `BEGIN IMMEDIATE`, busy timeout).
  Previously one connection was shared by all request threads, and parallel
  requests failed under load.
- `conclave-api`, `conclave server` and `conclave desktop` run on waitress.
  The Flask development server is only used with `--debug`
  (`conclave server`/`conclave desktop`) or `CONCLAVE_DEBUG`.
- Restoring a backup copies the database through the SQLite backup API into
  the live database instead of replacing the file, and rejects archives whose
  database fails the integrity check.
- On Windows a second server instance no longer starts silently on a port that
  is already in use; the server binds exclusively and exits with a clear error,
  and `conclave desktop` picks a free port instead.

## Settings page

- **Server log** with level filter (`GET /logs`). Successful `GET` requests
  (static files, UI polling) are logged at DEBUG, so warnings and errors stand
  out. `conclave-api` now also writes the log file.
- **Rate limit** (default `120 per minute` per route and client) is shown and
  editable. Changes take effect immediately and are saved to `[server]
  rate_limit` in `config.toml`; a value from `CONCLAVE_RATE_LIMIT` is shown
  read-only. `off` disables the limit; exceeded limits return JSON with status
  `429`.
- The runtime card shows the port the server is actually bound to.

## Bug fixes

- **Editing an agent no longer deletes its stored API key.** Saving an agent in
  the UI (or `conclave agent-edit`) without re-entering the key overwrote it
  with an empty value. The key is now kept unless a new one is entered;
  removing it requires `"clear_api_key": true`.
- `conclave agent-set-key` no longer drops the agent's preset, API URL and
  response path.
- API keys from environment variables are read leniently: surrounding
  whitespace and quotes (easily entered via the Windows environment dialog) are
  removed, with a one-time warning naming the variable.
- With a token configured, the UI page itself loads again (previously `GET /`
  and `/static/*` answered `401`).
- `conclave server`/`conclave desktop` ignored `[database] path` from
  `config.toml`; sequential orchestration in an unknown conversation returned
  502 (now 404).
- CLI commands and `conclave-api` used `/workspace` instead of the platform
  workspace (`~/Conclave/workspace`) when `CONCLAVE_WORKSPACE` was unset. All
  entry points now use the same default.
- Provider errors returned `500`; they now map to `429` (rate limit), `504`
  (timeout) and `502` (unavailable or other provider errors).
- Invoking an agent in an unknown conversation returned `502`; it now returns
  `404`.
- The MCP server reads the API token on every request, so the Conclave server
  may be started after the MCP client.
- The OpenAPI spec reports the package version.

## Removed

- `POST /guard/notify` and `GUARD_URL` (left over from the Docker setup).
- The unused role-based auth code (`RoleBasedAuthService`).

## New environment variables

| Variable | Purpose |
|---|---|
| `CONCLAVE_API_TOKEN_FILE` | Location of the generated API token |
| `CONCLAVE_ALLOWED_HOSTS` | Additional allowed `Host` headers |
| `CONCLAVE_RATE_LIMIT` | Rate limit (overrides `config.toml`) |
| `CONCLAVE_SERVER_THREADS` | waitress threads (default 16) |
| `CONCLAVE_LOG_DIR` | Directory of `conclave-server.log` |
| `CONCLAVE_CONFIG_FILE` | Location of `config.toml` |

## CI

- New `security` job: `pip-audit` for all dependencies and `bandit` for the
  source (medium severity and above).
- New `ui-browser` job runs the Playwright browser tests in Chromium.
- All GitHub Actions are pinned to commit SHAs.

## Verification

The v0.2.0 release surface was verified with:

- `python -m pytest` (1043 tests: 1041 passed, 2 skipped). The Playwright
  browser tests for XSS protection, CSP, token login and the settings page
  require `pip install -e ".[dev-all,dev-ui]"` and
  `python -m playwright install chromium`.
- 300 requests from 20 concurrent clients against waitress and werkzeug
  without errors
- `python -m build --sdist --wheel` and, manually, installation of the wheel in
  a fresh environment (`conclave --help`, `conclave-api` with token file and
  CSP)
- `pip-audit` (no known vulnerabilities) and `bandit` (no findings of medium
  severity or above), run locally; both also run in the CI job `security`
- A manual end-to-end test of `conclave desktop` with real Anthropic and OpenAI
  agents: conversations, streaming, auto-loop, markdown rendering, workspace
  files, backups, API docs, the settings page and login without token

Conclave still does not verify the truth of model answers. The human decides.
Always.

v0.2.0 remains alpha.
