# Release Notes: v0.2.3

Conclave v0.2.3 fixes chat rules that were not saved with the default SQLite
database.

## Upgrading

```bash
pip install --upgrade "conclave-personal[mcp]"
```

Restart the Conclave server. No configuration change is needed.

**Please set your chat rules again.** Rules entered before v0.2.3 were never
written to the SQLite database, so there is nothing to restore. Open the
conversation, click "Rules" and enter them once more.

## Fixes

- **Chat rules are saved with SQLite.** The SQLite conversation repository did
  not write or read the `rules` column. Setting rules in the UI or via
  `POST /conversations/<id>/rules` reported success, but the rules were gone
  on the next load. Models therefore never received the chat rules, and
  `context_files:` lines had no effect. The PostgreSQL backend was not
  affected.

## Verification

- `python -m pytest`, including a regression test for saving, loading and
  clearing rules with SQLite
- Wheel built and installed in a fresh environment

v0.2.3 remains alpha.
