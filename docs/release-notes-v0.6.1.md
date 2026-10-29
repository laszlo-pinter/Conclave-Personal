# Release Notes: v0.6.1

A small follow-up to v0.6.0: consultation settings get their own section in
`config.toml`, and `conclave-mcp` names the board in Conclave as the place for
work packages.

## Upgrading

```bash
pip install --upgrade "conclave-personal[mcp]"
```

Restart the Conclave server and your MCP clients. No database migration.

If your `config.toml` sets consultation reviewers under `[kanzo]`, move them
(recommended, not required):

```toml
# before
[kanzo]
reviewers = ["gpt", "claude"]
max_per_hour = 3

# after
[consultations]
reviewers = ["gpt", "claude"]
max_per_hour = 3
```

`[kanzo] url` stays where it is; it is only needed for an external Kanzo
(`[board] source = "kanzo"`).

## Changed

- **`[consultations]`** holds `reviewers`, `max_per_hour` and
  `comment_max_chars`. The old keys under `[kanzo]` are still read when
  `[consultations]` does not set them; the server then logs a warning. A key
  set in both sections takes the `[consultations]` value and logs that the
  `[kanzo]` value is ignored. Errors
  in these values name the section they came from. Reviewers alone do not
  switch consultations to Kanzo; only `[kanzo] url`,
  `CONCLAVE_KANZO_URL` or `[board] source = "kanzo"` do (unchanged).
- **MCP instructions.** `conclave-mcp` now tells agents that the board in
  Conclave is the place for work packages and that tickets are not kept in a
  second board. The transition rule from v0.6.0 ("if another board is used,
  the one the human chose applies") is gone.

## Documentation

- README, example workflow 5 and the documentation index no longer refer to
  Kanzo as the board; Kanzo stays documented as import source and external
  option ([Working with the board](mit-dem-board-arbeiten.md)).
- Configuration, API reference and security page use `[consultations]`.

## Verification

- `python -m pytest`, with and without `CONCLAVE_API_KEY`
- Wheel and sdist built; fresh install of the wheel with `[mcp]`
- `pip-audit` and `bandit`

v0.6.1 remains alpha.
