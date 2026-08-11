# tests/application/test_async_ports.py

import asyncio
from collections.abc import AsyncIterator

import pytest

from conclave.application.ports import AsyncModelAdapter, AsyncStreamingModelAdapter
from conclave.domain.conversation import Conversation
from conclave.domain.participant import Participant, ParticipantType


class FakeAsyncAdapter:
    provider = "test"
    async def complete(self, conversation: Conversation, participant: Participant) -> str:
        return "response"


class FakeAsyncStreamingAdapter:
    provider = "test"
    async def complete(self, conversation: Conversation, participant: Participant) -> str:
        return "response"

    async def stream(self, conversation: Conversation, participant: Participant) -> AsyncIterator[str]:
        for token in ["Hal", "lo"]:
            yield token


def test_async_model_adapter_protocol_exists():
    assert hasattr(AsyncModelAdapter, "complete")


def test_fake_satisfies_async_model_adapter():
    adapter = FakeAsyncAdapter()
    assert isinstance(adapter, AsyncModelAdapter)


def test_async_streaming_protocol_exists():
    assert hasattr(AsyncStreamingModelAdapter, "complete")
    assert hasattr(AsyncStreamingModelAdapter, "stream")


def test_fake_satisfies_async_streaming_adapter():
    adapter = FakeAsyncStreamingAdapter()
    assert isinstance(adapter, AsyncStreamingModelAdapter)


def test_async_model_adapter_complete_is_coroutine():
    """AsyncModelAdapter.complete muss als Coroutine deklariert sein."""
    import inspect
    adapter = FakeAsyncAdapter()
    assert inspect.iscoroutinefunction(adapter.complete)
