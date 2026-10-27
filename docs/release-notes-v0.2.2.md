# Release Notes: v0.2.2

Conclave v0.2.2 fixes streaming of preset agents.

## Upgrading

```bash
pip install --upgrade "conclave-personal[mcp]"
```

Restart the Conclave server. No configuration change is needed.

## Fixes

- **Streaming works for all preset formats.** The "Stream" button and the
  streaming API only understood OpenAI Chat Completions chunks. Preset agents
  using the Anthropic, Gemini, OpenAI Responses or Ollama format received an
  empty answer when streamed (for example a Claude agent with the `anthropic`
  preset). Each provider format is now handled, including Gemini's
  `streamGenerateContent` endpoint and Ollama's line-based stream.
- **Token usage of streamed calls is correct.** Streamed calls of preset agents
  stored the token counts of the previous non-streamed call, or none. Usage is
  now reset per stream and read from the provider's stream events. OpenAI Chat
  Completions, DeepSeek and Qwen/DashScope request it with
  `stream_options.include_usage`. Runs recorded before v0.2.2 keep their values.

Normal calls, orchestration and auto-loop were not affected.

## Verification

- `python -m pytest` with tests per stream format (Anthropic, Gemini, OpenAI
  Responses, OpenAI Chat, Ollama) and an end-to-end Claude stream
- Streaming against the real Anthropic, OpenAI (Responses and Chat Completions)
  and Gemini APIs: text and token usage (manual)
- Wheel built and installed in a fresh environment

v0.2.2 remains alpha.
