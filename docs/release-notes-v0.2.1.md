# Release Notes: v0.2.1

Conclave v0.2.1 moves the MCP server (`conclave-mcp`) to the MCP Python SDK
2.x. With v0.2.0 and earlier, a fresh `pip install "conclave-personal[mcp]"`
pulled in `mcp` 2.x, and the MCP server did not start (`FastMCP` was renamed
to `MCPServer` in the SDK).

## Upgrading

```bash
pip install --upgrade "conclave-personal[mcp]"
```

Restart your MCP client (for example open a new Claude Code session) so it
starts the new MCP server. No configuration change is needed; the tool names
and parameters are unchanged.

## Changes

- The MCP server uses `MCPServer` from the MCP Python SDK 2.x and reports the
  Conclave package version to the client.
- The `mcp` extra requires `mcp>=2,<3` (previously `mcp>=1.0` without an upper
  bound).
- Errors from the Conclave API are returned to the model as tool errors with
  Conclave's own message (for example `Conclave-API 401: ...` with a hint to
  check the token, or "server not reachable") instead of a generic HTTP error.
- Tool results are JSON text, as before.

## Tests and CI

- New tests start the MCP server through the real MCP client: in process,
  against a running Conclave server (token from `api.token`), with a wrong
  token, with an unreachable server, and over stdio like Claude Code.
- The `dev-all` extra installs `mcp`, so the CI runs these tests on Windows and
  Linux with Python 3.11 and 3.12. Previously no test imported the MCP server.

## Verification

- `python -m pytest` with `mcp` 2.3.0 and with the browser tests
- Wheel built and installed in a fresh environment; `conclave-mcp` handshake
  and tool listing over stdio

v0.2.1 remains alpha.
