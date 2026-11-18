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

## Team server

On a team server the reviewer runs with its own settings file instead of Personal's `config.toml`:

```text
conclave-reviewer run --settings C:\ProgramData\Conclave\reviewer.toml
```

```toml
[reviewer]
server = "team"
server_url = "https://board.intern"                  # https; http only for this machine
ca_bundle = 'C:\ProgramData\Conclave\company-ca.pem' # only this CA is trusted
reviewer_token_credential = "ConclaveReviewer"       # or reviewer_token_file (readable by the service account only)
data_dir = 'C:\ProgramData\Conclave\reviewer'
[reviewer.projects]
api = ['D:\checkouts\api']
```

- **Token:** the reviewer token (`cvr_`) of a service account, limited to its projects. It comes from
  the Windows Credential Manager of the service account (`cmdkey /generic:ConclaveReviewer /user:reviewer /pass`)
  or from a file only that account can read. It never appears in the settings file or on a command line.
- **TLS:** requests to the board use only `ca_bundle` (no system store, no `SSL_CERT_FILE`), ignore proxy
  variables and do not follow redirects. The MCP server gets the same CA.
- **MCP:** `conclave-board-mcp --reviewer` from the team package, with the same three tools as in Personal.
- **Git:** before each review the reviewer runs `git fetch` in the checkouts. A commit named in the ticket
  that is not on the git server gives a red review without running `claude` ("Commits nicht im Git-Server").

## License

PolyForm Noncommercial 1.0.0, see `LICENSE`.

Any use beyond that license needs a separate license from the copyright holder, Laszlo Pinter. For
the company Laszlo Pinter has given such a license to, it applies. The note on it is kept in that
company's team repository. This is no legal advice.
