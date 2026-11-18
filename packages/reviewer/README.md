# conclave-reviewer

Automatic reviewer for the Conclave board. It watches the `review` column and checks each new ticket in
a git worktree of the named commit with `claude -p`. It can only read: it has no shell, no write
access to the repository and sets nothing but the review result on the board.

- **Command:** `conclave-reviewer run | status | import-config`
- **Board access:** HTTP with a reviewer token (`cvr_`) and an MCP server that the reviewer hands to
  `claude` (`conclave-mcp --reviewer` in Conclave Personal, `conclave-board-mcp --reviewer` on a team
  server).
- **Depends on:** the board core `conclave-board` (file permissions). It imports nothing from
  Conclave Personal (`conclave`) and nothing from the team package, which import-linter checks.

Conclave Personal bundles this package; there `conclave desktop` starts the reviewer, and the old
module name `conclave.reviewer` still works.

## License

PolyForm Noncommercial 1.0.0, see `LICENSE`.

Any use beyond that license needs a separate license from the copyright holder, Laszlo Pinter. For
the company Laszlo Pinter has given such a license to, it applies. The note on it is kept in that
company's team repository. This is no legal advice.
