# Ports & Adapter

## Ports (Interfaces)

Definiert in `src/conclave/application/ports.py` als `typing.Protocol` mit `@runtime_checkable`.

| Protocol | Methoden | Implementierungen |
|----------|----------|-------------------|
| ConversationRepository | save, load, list_all, delete | SQLiteConversationRepository, PostgresConversationRepository |
| MessageRepository | save, list_by_conversation_id | SQLiteMessageRepository, PostgresMessageRepository |
| ParticipantRepository | save, list_by_conversation_id, delete_by_conversation | SQLiteParticipantRepository, PostgresParticipantRepository |
| AgentRepository | save, get, list_all, delete | SQLiteAgentRepository, PostgresAgentRepository |
| AuditRepository | save, list_by_conversation, list_by_date_range | SQLiteAuditRepository, PostgresAuditRepository |
| ModelAdapter | provider, complete() | UniversalAdapter, AnthropicAdapter, OpenAIAdapter |
| StreamingModelAdapter | + stream() | UniversalAdapter, AnthropicAdapter, OpenAIAdapter |
| UnitOfWork | conversations, messages, participants, __enter__, __exit__ | SQLiteUnitOfWork, PostgresUnitOfWork |

## Provider-Matrix

| Provider | Preset | ProviderProfile | Auth | Message-Format |
|----------|--------|----------------|------|----------------|
| Anthropic | anthropic | AnthropicProfile | x-api-key + anthropic-version | standard (system als Top-Level) |
| OpenAI Chat | openai | StandardProfile | Bearer | standard |
| OpenAI Responses | openai-responses | OpenAIResponsesProfile | Bearer | openai-responses (input statt messages) |
| Gemini | gemini | GeminiProfile | Query-Parameter | gemini (contents + systemInstruction) |
| Mistral | mistral | StandardProfile | Bearer | standard |
| Ollama | ollama | StandardProfile | none | standard |
| Custom | custom | StandardProfile | Bearer | standard |

## ProviderProfiles

Definiert in `infrastructure/universal/profiles.py`. Kapseln Provider-Eigenheiten:

```
ProviderProfile (Protocol):
    build_url(base_url, model, api_key) → (url, query_params)
    build_headers(api_key) → dict
    build_body(messages, model, system) → dict
    extract_response(data, response_path) → str | None
```

4 Implementierungen: StandardProfile, AnthropicProfile, OpenAIResponsesProfile, GeminiProfile.

## ResilientAdapter

Wrapper in `infrastructure/universal/resilient.py`:

- Retry bei 429 (Rate Limit) und 5xx (Server Error)
- Exponentielles Backoff (Default: 2^attempt Sekunden)
- Retry-After Header + Body-Parsing (Gemini: "retry in Xs")
- Kein Retry bei 400/401/403 (permanente Fehler)
- Domain-Errors: ProviderTimeout, ProviderRateLimit, ProviderUnavailable

## Backend-Matrix

| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| Conversations | SQLiteConversationRepository | PostgresConversationRepository |
| Messages | SQLiteMessageRepository | PostgresMessageRepository |
| Verschlüsselung | Optional (CryptoService) | Optional (CryptoService) |
| Schema-Migration | migrations.py (SQLite-Modus) | migrations.py (Postgres-Modus) |
| Autocommit | Nein (explizit commit) | Ja (conn.autocommit=True) |
| Empfohlen für | Entwicklung, Tests | Production (Docker) |

## Adapter-Registry

`application/adapter_registry.py` — Lazy Builder:

1. Beim Start: Alle Agents aus DB → Adapter bauen → Cache
2. Bei CRUD: `invalidate()` → Cache leeren
3. Bei Zugriff: `get_for(participant_id)` → Cache oder Builder
4. Builder: Lädt Agent aus DB → `_build_adapter_for_agent()` → ResilientAdapter
