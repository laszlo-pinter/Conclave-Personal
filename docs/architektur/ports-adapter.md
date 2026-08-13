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
| ModelAdapter | Synchroner Provider-Aufruf | UniversalAdapter, AnthropicAdapter, OpenAIAdapter |
| StreamingModelAdapter | Synchroner Provider-Aufruf mit Token-Streaming | UniversalAdapter, AnthropicAdapter, OpenAIAdapter |
| AsyncModelAdapter | Async-Provider-Aufruf für parallele Orchestrierung | AnthropicAsyncAdapter, OpenAIAsyncAdapter, UniversalAdapter über Executor-Fallback |
| AsyncStreamingModelAdapter | Async-Streaming-Port | Providerabhängig |
| UnitOfWork | Transaktionsgrenze für Repositories | SQLiteUnitOfWork, PostgresUnitOfWork |

## Provider-Matrix

| Provider | Preset | ProviderProfile | Auth | Message-Format |
|----------|--------|-----------------|------|----------------|
| OpenAI Chat | openai | StandardProfile | Bearer | standard |
| OpenAI Responses | openai-responses | OpenAIResponsesProfile | Bearer | openai-responses |
| Anthropic | anthropic | AnthropicProfile | x-api-key + anthropic-version | anthropic |
| Ollama | ollama | StandardProfile | none | standard |
| Gemini | gemini | GeminiProfile | Query-Parameter | gemini |
| Mistral | mistral | StandardProfile | Bearer | standard |
| Qwen / DashScope | qwen-dashscope, qwen-dashscope-thinking | StandardProfile | Bearer | standard |
| DeepSeek | deepseek | StandardProfile | Bearer | standard |
| Custom | custom | StandardProfile | Bearer | standard |

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

## Backend-Matrix

| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| Conversations | SQLiteConversationRepository | PostgresConversationRepository |
| Messages | SQLiteMessageRepository | PostgresMessageRepository |
| Participants | SQLiteParticipantRepository | PostgresParticipantRepository |
| Agents | SQLiteAgentRepository | PostgresAgentRepository |
| Runs | SQLiteRunRepository | PostgresRunRepository |
| Audit/Usage | SQLiteAuditRepository | PostgresAuditRepository |
| Verschlüsselung | Optional über CryptoService | Optional über CryptoService |
| Schema-Migration | migrations.py im SQLite-Modus | migrations.py im Postgres-Modus |
| Empfohlen für v0.1.x | Lokaler Personal-Default | Fortgeschrittene/kompatible Setups |

## Adapter-Registry

`src/conclave/application/adapter_registry.py` verbindet Participants mit
Provider-Adaptern:

1. Der Builder lädt die lokale Agent-Konfiguration.
2. `_build_adapter_for_agent()` erzeugt native oder Universal-Adapter.
3. Adapter werden pro Agent gecacht.
4. Agent-CRUD invalidiert den Cache.
5. `get_for(participant_id)` liefert den Adapter für Invoke, Stream,
   Orchestrierung, Auto-Loop und Judge-Flows.
