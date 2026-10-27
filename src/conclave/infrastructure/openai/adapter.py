# src/conclave/infrastructure/openai/adapter.py

from collections.abc import Iterator

try:
    import openai
except ImportError:
    openai = None  # type: ignore

from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType
from conclave.domain.context_report import native_context_report
from conclave.domain.model_response import Completion, TokenUsage
from conclave.domain.participant import Participant
from conclave.infrastructure.log import get_logger, request_logger

logger = get_logger("infrastructure.openai")


class OpenAIAdapter:
    """Ruft die OpenAI Responses-API auf (/v1/responses)."""

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
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt

    @property
    def provider(self) -> str:
        return "openai"

    def _build_instructions(self, conversation: Conversation) -> str | None:
        parts = []
        if self._system_prompt:
            parts.append(self._system_prompt)
        rules = getattr(conversation, "rules", "")
        if rules:
            parts.append(f"Chat-Regeln:\n{rules}")
        return "\n\n".join(parts) if parts else None

    def _report(self, conversation: Conversation, instructions: str | None):
        return native_context_report(conversation, agent_prompt=self._system_prompt,
                                     system_text=instructions, adapter="openai-native")

    def complete(self, conversation: Conversation, participant: Participant) -> Completion:
        input_msgs = self._build_input(conversation)
        instructions = self._build_instructions(conversation)
        with request_logger(logger, operation="openai.complete", model=self._model):
            response = self._client.responses.create(
                model=self._model,
                input=input_msgs,
                **({"instructions": instructions} if instructions else {}),
            )
        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return Completion(text=response.output_text, usage=usage,
                          report=self._report(conversation, instructions))

    def stream(
        self, conversation: Conversation, participant: Participant
    ) -> Iterator[str | Completion]:
        input_msgs = self._build_input(conversation)
        instructions = self._build_instructions(conversation)
        logger.debug("openai.stream start", extra={"model": self._model})
        stream = self._client.responses.create(
            model=self._model,
            input=input_msgs,
            **({"instructions": instructions} if instructions else {}),
            stream=True,
        )
        usage = None
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta
            elif event.type == "response.completed":
                usage = TokenUsage(
                    input_tokens=event.response.usage.input_tokens,
                    output_tokens=event.response.usage.output_tokens,
                )
        yield Completion(usage=usage, report=self._report(conversation, instructions))

    def _build_input(self, conversation: Conversation) -> list[dict]:
        """Wandelt Conclave-Messages in das OpenAI Responses-Format um."""
        result = []
        for message in conversation.messages:
            role = "user" if message.author_type == MessageAuthorType.USER else "assistant"
            result.append({"role": role, "content": message.content})
        return result
