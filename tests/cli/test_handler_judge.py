# tests/cli/test_handler_judge.py
"""Tests fuer invoke_with_judge (Chain-of-Verification)."""

import pytest

from conclave.application.adapter_registry import AdapterRegistry
from conclave.cli.handler import CLIHandler
from conclave.domain.conversation import Conversation
from conclave.domain.message import MessageAuthorType
from conclave.domain.participant import Participant, ParticipantType


class CaptureAdapter:
    """FakeAdapter, der die uebergebene Conversation speichert und konfigurierbar antwortet."""
    provider = "test"

    def __init__(self, response: str = "default response"):
        self._response = response
        self.calls: list[Conversation] = []

    def complete(self, conversation: Conversation, participant: Participant) -> str:
        # Snapshot der Messages anhaengen (Conversation ist mutable)
        self.calls.append([m.content for m in conversation.messages])
        return self._response


class FailingAdapter:
    provider = "test"

    def complete(self, conversation, participant):
        raise RuntimeError("simulated provider failure")


@pytest.fixture
def handler_with_registry(service):
    registry = AdapterRegistry()
    service.set_adapter_registry(registry)
    handler = CLIHandler(service)
    return handler, registry


def _seed_conv(handler, primary_id, primary_adapter, registry):
    conv_id = handler.new_conversation().data["conversation_id"]
    handler.add_participant(
        conversation_id=conv_id,
        participant_id=primary_id,
        name=primary_id,
        participant_type=ParticipantType.MODEL,
    )
    registry.register(primary_id, primary_adapter)
    handler.add_message(conv_id, "Original user prompt")
    return conv_id


def test_invoke_with_judge_returns_both_responses(handler_with_registry):
    handler, registry = handler_with_registry
    primary = CaptureAdapter("PRIMARY answer here")
    judge = CaptureAdapter("JUDGE verdict here")
    conv_id = _seed_conv(handler, "PRIMARY", primary, registry)
    registry.register("JUDGE", judge)

    result = handler.invoke_with_judge(
        conv_id, "PRIMARY", "JUDGE",
        judge_prompt_template="Beurteile: {primary_response} (zu Prompt: {original_prompt})",
    )

    assert result.success
    assert result.data["participant_id"] == "PRIMARY"
    assert result.data["content"] == "PRIMARY answer here"
    assert result.data["judge"]["participant_id"] == "JUDGE"
    assert result.data["judge"]["content"] == "JUDGE verdict here"


def test_judge_prompt_template_is_rendered(handler_with_registry):
    handler, registry = handler_with_registry
    primary = CaptureAdapter("die zu pruefende Antwort")
    judge = CaptureAdapter("ok")
    conv_id = _seed_conv(handler, "PRIMARY", primary, registry)
    registry.register("JUDGE", judge)

    handler.invoke_with_judge(
        conv_id, "PRIMARY", "JUDGE",
        judge_prompt_template="Original: {original_prompt} | Primary sagte: {primary_response}",
    )

    # Judge sieht in seiner Conv-History (letzte USER-Message) den gerenderten Prompt
    last_seen_messages = judge.calls[-1]
    rendered = next(m for m in last_seen_messages if "Original: " in m)
    assert "Original: Original user prompt" in rendered
    assert "Primary sagte: die zu pruefende Antwort" in rendered


def test_invoke_with_judge_persists_four_messages(handler_with_registry, service):
    handler, registry = handler_with_registry
    primary = CaptureAdapter("primary text")
    judge = CaptureAdapter("judge text")
    conv_id = _seed_conv(handler, "PRIMARY", primary, registry)
    registry.register("JUDGE", judge)

    handler.invoke_with_judge(
        conv_id, "PRIMARY", "JUDGE",
        judge_prompt_template="Pruefe: {primary_response}",
    )

    conv = service.load_conversation(conv_id)
    assert len(conv.messages) == 4
    assert conv.messages[0].author_type == MessageAuthorType.USER
    assert conv.messages[0].content == "Original user prompt"
    assert conv.messages[1].author_type == MessageAuthorType.MODEL
    assert conv.messages[1].author_id == "PRIMARY"
    assert conv.messages[1].content == "primary text"
    assert conv.messages[2].author_type == MessageAuthorType.USER
    assert "primary text" in conv.messages[2].content
    assert conv.messages[3].author_type == MessageAuthorType.MODEL
    assert conv.messages[3].author_id == "JUDGE"
    assert conv.messages[3].content == "judge text"


def test_invoke_with_judge_idempotent_when_judge_already_participant(handler_with_registry, service):
    handler, registry = handler_with_registry
    primary = CaptureAdapter("primary")
    judge = CaptureAdapter("judge")
    conv_id = _seed_conv(handler, "PRIMARY", primary, registry)
    # Judge ist BEREITS als Participant in der Conv
    handler.add_participant(
        conversation_id=conv_id,
        participant_id="JUDGE",
        name="JUDGE",
        participant_type=ParticipantType.MODEL,
    )
    registry.register("JUDGE", judge)

    result = handler.invoke_with_judge(
        conv_id, "PRIMARY", "JUDGE",
        judge_prompt_template="Pruefe: {primary_response}",
    )
    assert result.success
    # Genau ein JUDGE-Participant (keine Duplikate)
    conv = service.load_conversation(conv_id)
    judge_participants = [p for p in conv.participants if p.id == "JUDGE"]
    assert len(judge_participants) == 1


def test_invoke_with_judge_primary_exception_propagates(handler_with_registry):
    """Primary-Adapter-Exception (Provider down) propagiert wie bei invoke_participant heute."""
    handler, registry = handler_with_registry
    conv_id = _seed_conv(handler, "PRIMARY", FailingAdapter(), registry)

    with pytest.raises(RuntimeError, match="simulated provider failure"):
        handler.invoke_with_judge(
            conv_id, "PRIMARY", "JUDGE",
            judge_prompt_template="x: {primary_response}",
        )


def test_invoke_with_judge_primary_adapter_not_registered_returns_failure(handler_with_registry):
    """Wenn der Primary-Agent keinen Adapter hat, success=False ohne content."""
    handler, _ = handler_with_registry
    conv_id = handler.new_conversation().data["conversation_id"]
    handler.add_participant(
        conversation_id=conv_id, participant_id="PRIMARY", name="PRIMARY",
        participant_type=ParticipantType.MODEL,
    )
    handler.add_message(conv_id, "Original user prompt")

    result = handler.invoke_with_judge(
        conv_id, "PRIMARY", "JUDGE",
        judge_prompt_template="x: {primary_response}",
    )
    assert not result.success
    assert "content" not in result.data


def test_invoke_with_judge_judge_fails_keeps_primary(handler_with_registry):
    """Judge wirft -> partial success: Primary-Content bleibt, judge.error gesetzt."""
    handler, registry = handler_with_registry
    primary = CaptureAdapter("primary success")
    conv_id = _seed_conv(handler, "PRIMARY", primary, registry)
    registry.register("JUDGE", FailingAdapter())

    result = handler.invoke_with_judge(
        conv_id, "PRIMARY", "JUDGE",
        judge_prompt_template="pruefe: {primary_response}",
    )

    assert not result.success
    assert result.data["content"] == "primary success"
    assert "error" in result.data["judge"]
