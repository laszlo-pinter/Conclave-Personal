# Ports & Adapter

## Ports

Definiert in `src/conclave/application/ports.py` als `typing.Protocol` mit
`@runtime_checkable`. Infrastructure-Adapter implementieren diese Protocols
implizit über strukturelles Subtyping.

| Protocol | Zweck | Implementierungen |
|----------|-------|-------------------|
| ConversationRepository | Conversations speichern, laden, listen, löschen | SQLiteConversationRepository, PostgresConversationRepository |
| MessageRepository | Messages speichern und je Conversation laden | SQLiteMessageRepository, PostgresMessageRepository |
| ParticipantRepository | Conversation-Participants speichern, laden, löschen | SQLiteParticipantRepository, PostgresParticipantRepository |
| AgentRepository | Agent-Konfigurationen speichern, laden, löschen | SQLiteAgentRepository, PostgresAgentRepository |
| AuditRepository | Technische Provider-Aufrufe und Usage protokollieren | SQLiteAuditRepository, PostgresAuditRepository |
| RunRepository | Personal-Runs und optionale Usage-Daten persistieren | SQLiteRunRepository, PostgresRunRepository |
| ToolEventRepository | Tool-Events (`workspace.read`/`workspace.save`) speichern und je Conversation bzw. Message laden | SQLiteToolEventRepository, PostgresToolEventRepository |
| ModelAdapter | Synchroner Provider-Aufruf | UniversalAdapter, AnthropicAdapter, OpenAIAdapter |
| StreamingModelAdapter | Synchroner Provider-Aufruf mit Token-Streaming | UniversalAdapter, AnthropicAdapter, OpenAIAdapter |
| AsyncModelAdapter | Async-Provider-Aufruf | AsyncAnthropicAdapter, AsyncOpenAIAdapter (derzeit nicht verdrahtet) |
| AsyncStreamingModelAdapter | Async-Streaming-Port | AsyncAnthropicAdapter, AsyncOpenAIAdapter (derzeit nicht verdrahtet) |
| UnitOfWork | Transaktionsgrenze für Repositories | SQLiteUnitOfWork, PostgresUnitOfWork |

Die Async-Adapter werden von `cli/bootstrap.py` nicht gebaut. Die parallele
Orchestrierung nutzt die synchronen Adapter und legt jeden Aufruf per
`asyncio.to_thread()` in einen Worker-Thread
(`ConversationFlowService.async_complete_participant()`). `ResilientAdapter`
umhüllt jeden gebauten Adapter und implementiert `complete` (mit Retry) und
`stream` (ohne Retry).

## Provider-Matrix

| Provider | Preset | ProviderProfile | Auth | Message-Format |
|----------|--------|-----------------|------|----------------|
| OpenAI Chat | openai | StandardProfile | Bearer | standard |
| OpenAI Chat ohne Thinking | openai-no-thinking | StandardProfile | Bearer | standard (+ `disable_thinking: true` im Body) |
| OpenAI Responses | openai-responses | OpenAIResponsesProfile | Bearer | openai-responses |
| Anthropic | anthropic | AnthropicProfile (gewählt über `auth_format: x-api-key`) | `X-API-Key` + `anthropic-version` (nur wenn ein Key gesetzt ist) | standard |
| Ollama | ollama | StandardProfile | none | standard |
| Gemini | gemini | GeminiProfile | Query-Parameter | gemini |
| Mistral | mistral | StandardProfile | Bearer | standard |
| Qwen / DashScope | qwen-dashscope, qwen-dashscope-thinking | StandardProfile | Bearer | standard |
| DeepSeek | deepseek | StandardProfile | Bearer | standard |
| Custom | custom | StandardProfile | Bearer | standard |

Das Preset `custom` hat keine `api_url` und `requires_api_key: False`. Ohne
eigene `api_url` am Agenten wird kein Adapter gebaut (`AdapterNotFound`).
Bei `StandardProfile`, `OpenAIResponsesProfile` und `GeminiProfile` wird der
Key ebenfalls nur gesendet, wenn einer gesetzt ist.

Agents mit Provider `anthropic` oder `openai` ohne `preset` und ohne `api_url`
nutzen statt des UniversalAdapter die nativen SDK-Adapter `AnthropicAdapter`
bzw. `OpenAIAdapter`.

## ProviderProfiles

Definiert in `src/conclave/infrastructure/universal/profiles.py`. Profiles
kapseln Provider-Eigenheiten:

```python
ProviderProfile.build_url(base_url, model, api_key)
ProviderProfile.build_headers(api_key)
ProviderProfile.build_body(messages, model, system)
ProviderProfile.extract_response(data, response_path)
```

Aktuelle Implementierungen: `StandardProfile`, `AnthropicProfile`,
`OpenAIResponsesProfile`, `GeminiProfile`.

## ResilientAdapter

Wrapper in `src/conclave/infrastructure/universal/resilient.py`:

- Retry bei 429 und 5xx.
- Exponentielles Backoff.
- `Retry-After`-Header und providerabhängige Retry-Hinweise.
- Kein Retry bei permanenten Client-Fehlern wie 400, 401 oder 403.
- Domain-Errors: `ProviderTimeout`, `ProviderRateLimit`, `ProviderUnavailable`.
- Gemappt werden nur httpx-Fehler (UniversalAdapter). Fehler der nativen
  SDK-Adapter laufen ohne Retry und ohne Mapping durch.
- Die API übersetzt die Domain-Errors in HTTP-Status: `ProviderRateLimit` →
  429, `ProviderTimeout` → 504, `ProviderUnavailable` und andere
  `ProviderError` → 502.
- Streaming (`stream`) wird ohne Retry an den inneren Adapter durchgereicht.

## Backend-Matrix

| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| Conversations | SQLiteConversationRepository | PostgresConversationRepository |
| Messages | SQLiteMessageRepository | PostgresMessageRepository |
| Participants | SQLiteParticipantRepository | PostgresParticipantRepository |
| Agents | SQLiteAgentRepository | PostgresAgentRepository |
| Runs | SQLiteRunRepository | PostgresRunRepository |
| Audit/Usage | SQLiteAuditRepository | PostgresAuditRepository |
| Tool-Events | SQLiteToolEventRepository | PostgresToolEventRepository |
| Verschlüsselung | Immer aktiv über CryptoService (Key aus `CONCLAVE_SECRET_KEY`, sonst Key-Datei, sonst neu erzeugt) | Wie SQLite |
| Schema-Migration | migrations.py im SQLite-Modus | migrations.py im Postgres-Modus |
| Einsatz | Lokaler Personal-Default; CLI-Subkommandos nutzen immer SQLite | Fortgeschrittene/kompatible Setups (nur `conclave server`, `desktop`, `conclave-api`) |

## Adapter-Registry

`src/conclave/application/adapter_registry.py` verbindet Participants mit
Provider-Adaptern:

1. Der Builder lädt die lokale Agent-Konfiguration.
2. `cli/bootstrap.py:_build_adapter_for_agent()` erzeugt native oder
   Universal-Adapter und umhüllt sie mit `ResilientAdapter`.
3. Adapter werden pro Agent gecacht (vorhandene Agents schon beim Start).
4. Anlegen, Ändern und Löschen eines Agents über die API leert den Cache;
   `agent-test` baut den Adapter des getesteten Agents neu.
5. `get_for(participant_id)` liefert den Adapter für Invoke, Stream,
   Orchestrierung und Auto-Loop.
