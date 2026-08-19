# Release Notes: v0.1.17

Conclave v0.1.17 tightens the local Personal release around restore, orchestration
stability, and the human decision boundary.

## Highlights

- Backup restore now writes data back instead of only validating archives.
- Restore creates a pre-restore backup automatically before changing local data.
- Restore archives are checked against unsafe paths, absolute paths, symlinks,
  and oversized payloads before files are written.
- Auto-loop orchestration now supports optional rotating response order.
- Advanced orchestration inputs are normalized before execution.
- Judge-style agent roles and answer-review wording were removed from the
  public surface.
- The README states clearly that Conclave does not verify factual correctness.

## Restore

`conclave restore` and `POST /restore` can restore the local SQLite database
and workspace files from a Conclave ZIP backup.

By default, workspace files from the backup replace the current workspace
contents. The CLI flag `--keep-workspace` merges restored files into the
existing workspace instead.

## Auto-loop Rotation

Auto-loop keeps the previous static order by default.

For rotating order:

```bash
conclave auto-loop conv-1 a b c --rotation round-robin
```

The sequence rotates per round:

```text
Round 1: a, b, c
Round 2: b, c, a
Round 3: c, a, b
```

The API accepts:

```json
{
  "sequence": ["a", "b", "c"],
  "stop_signal": "@done",
  "max_rounds": 6,
  "rotation": "round_robin"
}
```

## Stability

Auto-loop, sequential orchestration, and parallel orchestration now reject
invalid inputs consistently:

- empty participant lists
- empty participant IDs
- too many participants
- invalid `max_rounds`
- invalid or empty stop signals
- unsupported rotation modes

## UI Code

The packaged desktop UI keeps the same product shape, but the frontend code is
cleaner:

- old duplicated root-level UI assets were removed
- installed UI assets live under `src/conclave/assets`
- inline event handlers were replaced with delegated UI actions
- dynamic UI attributes are escaped more defensively

## Human Decision Boundary

Conclave remains a tool. It can make model outputs visible, comparable, and
traceable, but it does not certify factual correctness and does not decide
which answer is true.

The human decides. Always.

## Verification

The v0.1.17 release surface was verified locally with:

- `python -m pytest`
- OpenAPI regeneration
- distribution metadata checks

v0.1.17 remains alpha.
