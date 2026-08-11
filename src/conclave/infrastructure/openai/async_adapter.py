# src/conclave/infrastructure/openai/async_adapter.py

from collections.abc import AsyncIterator

try:
    import openai
except ImportError:
    openai = None  # type: ignore

from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType
from conclave.domain.participant import Participant
from conclave.infrastructure.log import get_logger

logger = get_logger("infrastructure.openai.async")


class AsyncOpenAIAdapter:
    """Async-Variante des OpenAIAdapter – nutzt openai.AsyncOpenAI mit Responses-API."""

    DEFAULT_MODEL = "gpt-5.6"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
        system_prompt: str | None = None,
    ):
        if openai is None:
            raise ImportError(
                "Das 'openai'-Paket ist nicht installiert. "
                "Bitte installieren mit: pip install conclave[openai]"
            )
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt

    @property
    def provider(self) -> str:
        return "openai"

    async def complete(self, conversation: Conversation, participant: Participant) -> str:
        input_msgs = self._build_input(conversation)
        logger.debug("openai.async_complete start", extra={"model": self._model})
        response = await self._client.responses.create(
            model=self._model,
            input=input_msgs,
            **({"instructions": self._system_prompt} if self._system_prompt else {}),
        )
        return response.output_text

    async def stream(
        self, conversation: Conversation, participant: Participant
    ) -> AsyncIterator[str]:
        input_msgs = self._build_input(conversation)
        logger.debug("openai.async_stream start", extra={"model": self._model})
        stream = await self._client.responses.create(
            model=self._model,
            input=input_msgs,
            **({"instructions": self._system_prompt} if self._system_prompt else {}),
            stream=True,
        )
        async for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta

    def _build_input(self, conversation: Conversation) -> list[dict]:
        result = []
        for message in conversation.messages:
            role = "user" if message.author_type == MessageAuthorType.USER else "assistant"
            result.append({"role": role, "content": message.content})
        return result
