# Conclave Personal

Conclave Personal is a local multi-agent workspace for individual users. It
brings multiple AI models into one structured conversation, gives them explicit
roles, and makes their collaboration traceable through runs.

The user remains the control point. Agents are participants, not controllers.
Conversations, workspace files, agents, and usage data are stored locally by
default.

Conclave does not verify the truth of model answers. It does not decide which
answer is correct. It gives users a structured workspace for comparing model
outputs, tracking runs, and deliberately choosing the next step. The human
decides. Always.

> Status: v0.2.2 Alpha. The primary path is local, desktop-first, and designed
> for individual users on Windows and Linux.

![Conclave Studio](https://raw.githubusercontent.com/laszlo-pinter/Conclave-Personal/main/docs/assets/screenshots/conclave-studio-desktop.png)

## What Conclave Is For

Conclave is not just another chat UI. Its core is:

- Multiple models.
- Explicit roles.
- Structured collaboration.
- Traceable runs.
- Human control.
- Local-first workspace.

In practice, this means:

- Run multi-agent conversations with Writer, Critic, Reviewer, Planner,
  Researcher, or custom roles.
- Invite agents as participants into specific conversations.
- Use local workspace files explicitly as context.
- Let models work one by one, in parallel, or in auto-loops.
- Compare different model outputs without treating model agreement as truth.
- Inspect runs, token usage, errors, and results.
- Work locally on Windows and Linux.
- Switch the desktop UI between German and English.

## Human Decision Boundary

Conclave is a tool, not an arbiter. Agent outputs can be useful, wrong,
incomplete, overconfident, or mutually reinforcing. Conclave can make those
outputs visible and traceable, but it does not certify factual correctness.

The user decides what to trust, what to verify externally, and what to do next.

## 60-Second Example

```text
          -> Writer
Prompt ---+-> Critic
          -> Researcher
```

1. Create a conversation.
2. Add agents as participants.
3. Give each agent a role and a system prompt: Writer drafts, Critic
   challenges, Researcher adds context. The behavior comes from the system
   prompt; the desktop UI generates it from the selected role, the CLI stores
   the role only as a label.
4. Send a prompt.
5. Watch the run.
6. Compare the results and deliberately start the next round.

Minimal CLI flow:

```bash
conclave desktop
conclave agent-new writer --name "Writer" --provider "openai-responses" --preset "openai-responses" --model "<openai-model>" --role writer --system-prompt "You are Writer. Draft clear, structured text." --api-key "..."
conclave agent-new critic --name "Critic" --provider "ollama" --preset "ollama" --model "llama3.1" --role critic --system-prompt "You are Critic. Find weaknesses, risks, and blind spots."
CONV=$(conclave --json new | python -c "import sys,json; print(json.load(sys.stdin)['conversation_id'])")
conclave add-participant "$CONV" writer --name "Writer" --type model
conclave add-participant "$CONV" critic --name "Critic" --type model
conclave message "$CONV" "Draft a concise product positioning and list risks or open assumptions."
conclave invoke "$CONV" writer
conclave invoke "$CONV" critic
conclave runs --conversation-id "$CONV"
```

## Product Areas

| Area | Purpose |
| --- | --- |
| Studio | Conversations, messages, participants, floor control, invoke, stream, orchestration, auto-loop |
| Agents | Agents, roles, providers, models, presets, connection tests |
| Workspace | Local files, context, notes, outputs |
| Runs | Invoke, auto-loop, orchestration history, usage, and errors |
| Settings | Runtime info, workspace path, API access token, provider key status, backup creation (restore via CLI/API), rate limit, server log. The language switch is in the sidebar footer. |

## Non-Goals

- No GDPR or enterprise platform.
- No consent management per provider.
- No DPA or legal contract management.
- No role-based enterprise administration.
- No Docker requirement for end users.

## Platform Target

Conclave Personal supports Windows and Linux. The CI matrix checks Ubuntu and
Windows with Python 3.11 and 3.12.

The application core stays platform-neutral. Only startup, installation, and
autostart adapters are OS-specific:

- Windows: desktop launch, optional user autostart or NSSM service.
- Linux: desktop launch, optional `systemd --user` and `.desktop` file.
- There is no Docker setup; the user path is a local installation.

## Installation

The published package is `conclave-personal`. The installed command remains
`conclave`.

### Windows

```powershell
pip install conclave-personal
conclave desktop
```

### Linux

```bash
pip install conclave-personal
conclave desktop
```

### From A Checkout

```bash
python -m pip install -e ".[dev-all]"
conclave desktop
```

Development tests:

```text
python -m pytest
```

Existing local SQLite data can be migrated explicitly:

```bash
conclave migrate-personal --from /path/to/old/conclave.db --dry-run
conclave migrate-personal --from /path/to/old/conclave.db
```

## Provider Setup

Create agents with a provider, model, and system prompt. The role (lowercase
IDs such as `writer`, `critic`, `reviewer`, `researcher`, `planner`) is stored
as a label; in the CLI it does not generate a prompt. The desktop UI fills in a
system prompt from the selected role.

```bash
conclave agent-new reviewer \
  --name "Reviewer" \
  --provider "anthropic" \
  --preset "anthropic" \
  --model "<anthropic-model>" \
  --role reviewer \
  --system-prompt "You are Reviewer. Check logic, completeness, and effect." \
  --api-key "..."
```

Ollama can run locally without an API key:

```bash
conclave agent-new local-critic \
  --name "Local Critic" \
  --provider "ollama" \
  --preset "ollama" \
  --model "llama3.1" \
  --role critic \
  --system-prompt "You are Local Critic. Find weaknesses, risks, and blind spots."
```

The [provider smoke test](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/provider-smoke-test.md) describes a reproducible
end-to-end check with Claude, Gemini, GPT, and DeepSeek.

## Local Quickstart

The recommended personal CLI path is:

```bash
conclave desktop
```

Technical modes:

```bash
conclave server
conclave web
```

Direct CLI flow:

```bash
conclave agent-new assistant \
  --name "Assistant" \
  --provider "openai-responses" \
  --preset "openai-responses" \
  --model "<openai-model>" \
  --api-key "..."

ID=$(conclave --json new | python -c "import sys,json; print(json.load(sys.stdin)['conversation_id'])")
conclave add-participant "$ID" assistant --name "Assistant" --type model
conclave message "$ID" "Analyze this idea from three perspectives."
conclave invoke "$ID" assistant
```

Auto-loop and multi-agent workflows are described in the
[example workflows](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/beispiel-workflows.md).

## MCP Server

Conclave includes an MCP server for Claude Desktop, Claude Code, and other
Anthropic-compatible MCP clients. It exposes Conclave conversations, agents,
messages, orchestration, workspace files, and usage as local tools.

Install with MCP support (this installs the MCP Python SDK 2.x):

```bash
pip install "conclave-personal[mcp]"
```

Start Conclave locally:

```bash
conclave server --host 127.0.0.1 --port 8000
```

In Claude Code, register it with one command (use the full path to
`conclave-mcp` if its scripts folder is not on `PATH`):

```bash
claude mcp add Conclave -s user -e CONCLAVE_API_URL=http://localhost:8000 -- conclave-mcp
```

Other MCP clients use a configuration like this:

```json
{
  "mcpServers": {
    "conclave": {
      "command": "conclave-mcp",
      "env": {
        "CONCLAVE_API_URL": "http://localhost:8000"
      }
    }
  }
}
```

The MCP server talks to `CONCLAVE_API_URL` (default `http://localhost:8000`).
`conclave desktop` picks another free port if 8000 is busy, so start the server
with a fixed port (`conclave server --port 8000` or
`conclave desktop --port 8000`) or set `CONCLAVE_API_URL` to the actual address.

The local API always requires a token. Without `CONCLAVE_API_KEY`, the server
creates one on first start (`api.token` in the configuration directory) and the
MCP server reads it from there on every request, so the server may also be
started after the MCP client. If the server uses an explicit
`CONCLAVE_API_KEY`, set the same value in the MCP `env` block.

Tool results are returned as JSON text. Errors from the Conclave API (for
example a missing token or an unreachable server) are reported to the model as
tool errors with Conclave's own message.

## Core Concepts

### Conversation

A local workspace with a topic, messages, rules, and participants.

### Agent

A reusable provider, model, and role configuration.

### Participant

An agent inside a specific conversation.

### Workspace

A local folder for files, notes, context, and outputs: `CONCLAVE_WORKSPACE`,
otherwise `~/Conclave/workspace`. Files are not listed or loaded as context
automatically: users reference them with `@workspace/...` (for example
`@workspace/notes.md`), agents can request specific files with `@read(...)`,
and a `context_files:` line in the conversation rules adds workspace files to
the system prompt.

### Run

An executable work step: invoke, stream, orchestration, or auto-loop.
Runs expose status, errors, duration, and usage.

## Architecture

```text
src/conclave/
  domain/          pure domain models
  application/     services, orchestration, ports
  infrastructure/  providers, databases, crypto, runtime adapters
  api/             local HTTP API
  cli/             command line
  runtime/         platform-neutral desktop/server launch logic

src/conclave/assets/
  conclave-ui.html installed UI resource
  static/js/       api, i18n, state, utils, main, swagger-init
  static/js/features/
                   agents, auth, autoloop, conversations, export, floor,
                   messages, participants, runs, settings, speech, usage,
                   workspace
  static/css/      stylesheets
  static/vendor/   bundled libraries and fonts (no CDN at runtime)
  scripts/         Windows and Linux startup/service scripts
```

## Providers

Conclave is provider-agnostic. It distinguishes between tested primary paths
and compatible presets.

### First-class / Tested

These paths are covered by local tests, API contracts, or adapter tests:

- OpenAI Responses
- OpenAI Chat Completions
- Anthropic
- Ollama

### Built-in Preset / Compatible / Experimental

These presets are built in, but behavior can vary by provider API, model, and
account:

- Gemini
- Mistral
- DeepSeek
- Qwen / DashScope
- Custom/OpenAI-compatible endpoints

API keys stay local and are stored encrypted in the local database for agents.
Ollama can work without an API key.

## Local-first, Not Offline-only

Conclave stores workspace files, configuration, agents, conversations, and run
history locally. When a remote provider such as OpenAI, Anthropic, Gemini,
Mistral, DeepSeek, or DashScope is used, the prompt and context data required
for that model call is sent to that provider. With Ollama or compatible local
endpoints, processing can happen fully locally.

## Security

Conclave binds the local API to `127.0.0.1` by default. The local API always
requires a token; without `CONCLAVE_API_KEY` one is generated and stored in
`api.token`. In `production` mode, `CONCLAVE_API_KEY` and an encryption key
(`CONCLAVE_SECRET_KEY`, or an existing key file / `CONCLAVE_SECRET_KEY_FILE`)
must be set explicitly. Workspace access stays inside the configured workspace
root, and hidden paths are not read as agent context.

More details: [Security for Conclave Personal](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/sicherheit.md).

## Documentation

Important documents:

- [Multi-agent guide](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/multi-agent-leitfaden.md)
- [Example workflows](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/beispiel-workflows.md)
- [Security](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/sicherheit.md)
- [Configuration](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/referenz/konfiguration.md)
- [Release Notes v0.2.2](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.2.2.md)
- [Release Notes v0.2.1](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.2.1.md)
- [Release Notes v0.2.0](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.2.0.md)
- [Release Notes v0.1.20](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.20.md)
- [Release Notes v0.1.19](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.19.md)
- [Release Notes v0.1.18](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.18.md)
- [Release Notes v0.1.17](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.17.md)
- [Release Notes v0.1.16](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.16.md)
- [Release Notes v0.1.5](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.5.md)
- [Release Notes v0.1.4](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.4.md)
- [Release Notes v0.1.3](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.3.md)
- [Release Notes v0.1.2](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.2.md)
- [Release Notes v0.1.1](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.1.md)
- [Release Notes v0.1.0](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/release-notes-v0.1.0.md)
- [Documentation index](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/docs/index.md)

## Known Limitations

v0.2.2 remains alpha. Known limitations:

- Provider compatibility varies by API, model, account, and region.
- Remote providers receive the data required for the model call.
- Desktop mode starts the local web application in a browser.
- Advanced multi-agent orchestration is partly experimental.
- There is no native Windows installer, AppImage, or `.deb` package yet.

## Release Verification

CI runs the jobs `test` (Ubuntu and Windows, Python 3.11 and 3.12),
`ui-browser` (Playwright browser tests in Chromium), `security` (`pip-audit`,
`bandit`) and `build` (sdist and wheel, artifact inspection).

The v0.2.2 surface was verified with these checks (v0.2.2 changes only streaming
of preset agents; the other checks were run for v0.2.0 and v0.2.1):

- `python -m pytest` (the Playwright browser tests for XSS protection, CSP,
  token login and the settings page only run with the browser test setup
  below)
- `python -m build --sdist --wheel`
- Installation from the built wheel in a fresh environment (manual).
- `conclave --help`
- `conclave-api` from the installed wheel (token file, CSP header, `/health`)
- `conclave-mcp` from the installed wheel: MCP handshake and tool listing over
  stdio (MCP Python SDK 2.x); MCP tests run in CI
- Streaming of preset agents against the real Anthropic, OpenAI (Responses and
  Chat Completions) and Gemini APIs: text and token usage (manual)
- `conclave desktop` end-to-end with real providers (manual)
- `pip-audit` and `bandit` (run manually for this release, also in CI)
- Artifact inspection without workspace data, databases, keys, logs, and old
  enterprise/GDPR paths.

Development install for the browser tests:

```bash
python -m pip install -e ".[dev-all,dev-ui]"
python -m playwright install chromium
python -m pytest tests/ui
```

## Origin

This project was created exclusively by LLM models.

## License

PolyForm Noncommercial License 1.0.0. See [LICENSE](https://github.com/laszlo-pinter/Conclave-Personal/blob/main/LICENSE).

Free for noncommercial use.
