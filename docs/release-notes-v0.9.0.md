# Release Notes: v0.9.0

The board gets its own page, and projects can be managed in the UI. The board
view moves into the board core and is available standalone under `/ui/board`;
a board mode shows only that page. The automatic reviewer becomes a package of
its own (`conclave_reviewer`), still bundled with Conclave Personal, and can
also review against a remote board server.

## Upgrading

```bash
conclave backup
pip install --upgrade "conclave-personal[mcp]"
```

With the automatic reviewer:

```bash
pip install --upgrade "conclave-personal[mcp,reviewer]"
```

Check these points after the upgrade:

- **No migration.** The database schema is unchanged.
- **Update the server and the MCP clients together**, as usual. Restart Claude
  Code, Claude Desktop and any other MCP client after the upgrade.
- **Reviewer.** Installation and configuration stay the same. The code now
  lives in the package `conclave_reviewer`; the module name
  `conclave.reviewer` and the command `conclave-reviewer` keep working.
  `conclave desktop` starts it as before.

## Board page

- **`/ui/board`:** the board as a page of its own, with the same view as the
  board tab in the Studio: columns, cards, ticket view, review status,
  approvals, control tickets and notifications. One compact toolbar holds
  project, search, "show done", the actions, language, appearance and sign-out.
- **Sign-in:** `conclave desktop` opens the page signed in. Otherwise the page
  asks for the human token; it is kept in the browser tab only. The hint names
  `conclave token show --reveal`.
- **Board mode:** `[ui] mode = "board"` in `config.toml` shows only the board
  page: `/` leads to `/ui/board`, the Studio is not served. The API, the MCP
  server and the agents work as before. The default stays `"studio"`.

## Projects in the UI

- **"Projects"** in the board toolbar (board page and Studio tab, human only):
  create projects with a short name and title, rename them, and delete empty
  ones. A project with tickets or initiatives cannot be deleted there.
- Agents see no project buttons; the API answers them with `403` as before.

## API

- **Additive:** `DELETE /board/v1/projects/<slug>?only_empty=true` deletes a
  project only if it has no tickets (including done tickets and control
  tickets) and no initiatives; otherwise `409 ProjectNotEmpty`. The check and
  the deletion happen in one step. Without the parameter the endpoint behaves
  as before. The OpenAPI descriptions are extended; there is no breaking change
  in `/board/v1`.

## Reviewer

- **Own package `conclave_reviewer`.** It imports nothing from Conclave
  Personal and depends only on the board core. Conclave Personal bundles it;
  installation stays `pip install "conclave-personal[mcp,reviewer]"`.
- **Stopping.** Ctrl+C and Ctrl+Break now also stop `claude` with its child
  processes and remove the worktrees when they arrive in the middle of a
  review, within about a second on Windows.
- **Remote board server (optional).** New keys in `[reviewer]` let the
  reviewer check against a board server with accounts instead of Conclave
  Personal: `server = "team"`, `server_url` (https), `ca_bundle` (only this CA
  is trusted; proxy and CA environment variables are ignored, redirects are not
  followed), the token from a file or the Windows Credential Manager
  (`reviewer_token_credential`), `data_dir`, `git fetch` before each review and
  a red review without `claude` when the named commit is not on the git server.
  `conclave-reviewer run|status --settings <file>` reads `[reviewer]` from a
  file of its own. Without these keys nothing changes.

See the section [Reviewer](referenz/konfiguration.md#reviewer) of the
configuration reference.

## Security

- The board page has no inline script or style and keeps the strict content
  security policy; values from the API reach the page only as text, Markdown
  only through DOMPurify.
- The token of the board page stays in the browser tab (`sessionStorage`).
- Deleting a project from the UI cannot remove tickets that an agent created a
  moment before: the server checks emptiness and deletes in one statement.
- With a remote board server the reviewer token never appears in a settings
  file, an MCP configuration or a command line, and the log contains no output
  of `claude`.

## Documentation

- [Configuration](referenz/konfiguration.md): section `[ui]` (board mode) and
  the new keys of `[reviewer]`.
- [API](referenz/api.md): `only_empty`.
- [CLI](referenz/cli.md): `conclave-reviewer --settings`.
- [Working with the board](mit-dem-board-arbeiten.md): creating projects in the
  UI.

## Known limitations

- **Going back to v0.8.0** works with the same database: there is no
  migration in v0.9.0.
- The reviewer needs Claude Code (`claude`) on the same machine.

## Verification

- `python -m pytest`, including the Playwright browser tests
- PostgreSQL tests
- `bandit`, `pip-audit` and `import-linter`
- Wheels of Conclave Personal, the board core and the reviewer built and
  checked; the reviewer wheel installed and started without Conclave Personal

v0.9.0 remains alpha.
