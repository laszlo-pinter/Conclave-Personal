# Release Notes: v0.9.2

A small release of the automatic reviewer. It no longer puts any text from a
ticket on the command line of `claude`, so a review starts whatever the ticket
title contains. The documentation now matches the code again.

## Upgrading

```bash
conclave backup
pip install --upgrade "conclave-personal[mcp,reviewer]"
```

Without the automatic reviewer:

```bash
pip install --upgrade "conclave-personal[mcp]"
```

For a reviewer against a remote board server, install the `conclave-reviewer`
wheel of this version.

- **No migration.** The database schema is unchanged.
- **Update the server and the MCP clients together**, as usual. Restart Claude
  Code, Claude Desktop and any other MCP client after the upgrade.

## Reviewer

- **The review request goes to `claude -p` over stdin**, no longer as an
  argument. It no longer contains the ticket title. The title is text from
  someone else, and the reviewer reads the ticket itself with
  `conclave_board_get`.
- **The system prompt comes from a file:** `review-prompt.md` in the data folder
  of the reviewer, readable only by the user, via `--append-system-prompt-file`.
- **Why:** If `claude` is a `.cmd` or `.bat` file (an npm installation on
  Windows), `cmd.exe` runs it and cuts its command line at the first line break.
  Every switch after the request was then lost, including `--restricted` and the
  tool limits, and `%VAR%` in a title was expanded. With the native `claude.exe`
  titles arrived unchanged, but the request was still built from ticket text.
- The command line now holds only fixed switches, tool names and paths. An
  argument with a line break is refused before `claude` starts.
- The dry run (`conclave-reviewer run --dry-run`) logs the command line, the
  request for stdin and the size of the system prompt separately.

## Documentation

The documentation was checked against the code of v0.9.1 and corrected. This
includes the agent token rights in the API reference, `conclave desktop --port`
(only the preferred port), `CONCLAVE_API_URL`, the reviewer against a remote
board server, `reviewer.token` in the deny example for Claude Code, and the
routes `/board/v1/stuck` and `…/release`.

## API

No change in `/board/v1`. The OpenAPI files only carry the new version.

## Verification

- `python -m pytest`, including the Playwright browser tests
- PostgreSQL tests
- `bandit`, `pip-audit` and `import-linter`
- Wheel and sdist of Conclave Personal and the wheels of the board core and the
  reviewer built and checked
- Fresh installation from wheel and sdist with `[mcp,reviewer]` and a smoke
  test; upgrade from v0.9.1 on a copy of a real database
- One call of the new command line with the real `claude`, the request over
  stdin and the system prompt from the file

v0.9.2 remains alpha.
