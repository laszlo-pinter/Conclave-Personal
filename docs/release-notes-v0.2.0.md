# Release Notes: v0.2.0 (draft)

Conclave v0.2.0 is a security release based on the review of 2026-10-26
(`docs/refactoring-plan.md`). It contains breaking changes for API clients.

## Breaking changes

- **The local API always requires a token.** If `CONCLAVE_API_KEY` is not set,
  the server creates a random token on first start and stores it in `api.token`
  in the configuration directory (`CONCLAVE_API_TOKEN_FILE` overrides the path).
  `conclave desktop` and `conclave web` pass it to the browser in the URL
  fragment. `conclave-watch` and the MCP server read the token file
  automatically when `CONCLAVE_API_KEY` is empty. Other scripts must send
  `Authorization: Bearer <token>`.
- **POST requests need `Content-Type: application/json`** (an empty body is
  `{}`) or the header `X-Conclave-Client`. Otherwise the API answers `415`.
- **The `Host` header is checked.** Only `localhost`, `127.0.0.1`, `[::1]` and
  entries from `CONCLAVE_ALLOWED_HOSTS` are accepted; other hosts get `421`.
  Binding to a non-loopback address requires `CONCLAVE_ALLOWED_HOSTS`.
- **The UI only talks to the server it was loaded from** (`connect-src 'self'`).
- **`POST /restore` only accepts a backup file name** from the backup directory
  (`{"backup": "<name>"}`, see the new `GET /backups`). `backup_path` is no
  longer supported. The workspace is kept by default; clearing it requires
  `"replace_workspace": true` and `"confirm": "replace-workspace"`. The CLI
  restore command still accepts any path.

## Security fixes

- Model output is sanitized with DOMPurify before it is rendered (stored XSS).
- All HTML sinks in the UI are audited; values from the API are escaped.
- The UI no longer loads anything from Google Fonts, cdnjs or unpkg. marked,
  highlight.js, DOMPurify, Swagger UI and the fonts are shipped with the package
  (`THIRD_PARTY.md`).
- Every response carries a Content-Security-Policy, `Referrer-Policy` and
  `Permissions-Policy`.
- With a token configured, the UI page itself loads again (previously `GET /`
  and `/static/*` answered `401`).
