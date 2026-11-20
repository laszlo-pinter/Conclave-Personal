# Release Notes: v0.9.1

A small release of the board core. It adds an extension point that lets a board
policy order the tickets `next` hands out. Conclave Personal behaves as before.

## Upgrading

```bash
conclave backup
pip install --upgrade "conclave-personal[mcp]"
```

With the automatic reviewer:

```bash
pip install --upgrade "conclave-personal[mcp,reviewer]"
```

- **No migration.** The database schema is unchanged.
- **Update the server and the MCP clients together**, as usual. Restart Claude
  Code, Claude Desktop and any other MCP client after the upgrade.

## Board core

- **New extension point `BoardPolicy.next_group(principal, task)`** and
  `next_groups(principal, tasks)` for all candidates in one call. `next`
  without a given ticket orders the first column by rework from the review
  first, then by this group (smaller first), then in board order. Within a
  group the board order stays; rework always comes first. The default puts all
  tickets in one group, so the order in Conclave Personal is unchanged.
- `next` now asks the policy for the groups once per call and only for tickets
  it may hand out at all (not "humans only", no control tickets, visible
  projects). Rights are still checked ticket by ticket until one fits.

## API

No change in `/board/v1`. The OpenAPI files only carry the new version.

## Verification

- `python -m pytest`, including the Playwright browser tests
- PostgreSQL tests
- `bandit`, `pip-audit` and `import-linter`
- Wheel and sdist of Conclave Personal and the wheels of the board core and the
  reviewer built and checked
- Fresh installation from wheel and sdist with `[mcp,reviewer]` and a smoke
  test; upgrade from v0.9.0 on a copy of a real database

v0.9.1 remains alpha.
