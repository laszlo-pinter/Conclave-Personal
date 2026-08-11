# src/conclave/infrastructure/anthropic/async_adapter.py

from collections.abc import AsyncIterator

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore

from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType
from conclave.domain.participant import Participant
from conclave.infrastructure.log import get_logger

logger = get_logger("infrastructure.anthropic.async")


class AsyncAnthropicAdapter:
    """Async-Variante des AnthropicAdapter – nutzt anthropic.AsyncAnthropic."""

    DEFAULT_MODEL = "claude-sonnet-5"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        system_prompt: str | None = None,
    ):
        if anthropic is None:
            raise ImportError(
                "Das 'anthropic'-Paket ist nicht installiert. "
                "Bitte installieren mit: pip install conclave[anthropic]"
            )
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt

    @property
    def provider(self) -> str:
        return "anthropic"

    async def complete(self, conversation: Conversation, participant: Participant) -> str:
        messages = self._build_messages(conversation)
        kwargs = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if self._system_prompt:
            kwargs["system"] = self._system_prompt

        logger.debug("anthropic.async_complete start", extra={"model": self._model})
        response = await self._client.messages.create(**kwargs)
        return response.content[0].text

    async def stream(
        self, conversation: Conversation, participant: Participant
    ) -> AsyncIterator[str]:
        messages = self._build_messages(conversation)
        kwargs = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if self._system_prompt:
            kwargs["system"] = self._system_prompt

        logger.debug("anthropic.async_stream start", extra={"model": self._model})
        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if (
                    event.type == "content_block_delta"
                    and event.delta.type == "text_delta"
                ):
                    yield event.delta.text

    def _build_messages(self, conversation: Conversation) -> list[dict]:
        result = []
        for message in conversation.messages:
            role = "user" if message.author_type == MessageAuthorType.USER else "assistant"
            result.append({"role": role, "content": message.content})
        return result
