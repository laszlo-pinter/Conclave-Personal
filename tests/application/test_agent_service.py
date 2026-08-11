# tests/application/test_agent_service.py

import pytest
from conclave.application.agent_service import AgentService
from conclave.infrastructure.sqlite.agent_repository import SQLiteAgentRepository
from conclave.domain.agent import Agent
from conclave.domain.errors import AgentAlreadyExists, AgentNotFound


def make_agent(**kw) -> Agent:
    d = dict(id="a1", name="Claude", provider="anthropic", model="claude-sonnet-4-20250514")
    d.update(kw)
    return Agent(**d)


@pytest.fixture
def svc(db_connection, crypto):
    return AgentService(SQLiteAgentRepository(db_connection, crypto))


def test_create_agent_returns_agent(svc):
    agent = svc.create_agent(make_agent())
    assert agent.id == "a1"


def test_create_duplicate_raises(svc):
    svc.create_agent(make_agent())
    with pytest.raises(AgentAlreadyExists):
        svc.create_agent(make_agent())


def test_get_agent_returns_agent(svc):
    svc.create_agent(make_agent(role="kritiker"))
    agent = svc.get_agent("a1")
    assert agent.role == "kritiker"


def test_get_unknown_raises(svc):
    with pytest.raises(AgentNotFound):
        svc.get_agent("unbekannt")


def test_list_agents(svc):
    svc.create_agent(make_agent(id="a1"))
    svc.create_agent(make_agent(id="a2", name="GPT", provider="openai", model="gpt-4o"))
    assert len(svc.list_agents()) == 2


def test_update_agent(svc):
    svc.create_agent(make_agent(name="Alt"))
    updated = svc.update_agent(make_agent(name="Neu", role="analytiker"))
    assert updated.name == "Neu"
    assert svc.get_agent("a1").role == "analytiker"


def test_update_unknown_raises(svc):
    with pytest.raises(AgentNotFound):
        svc.update_agent(make_agent())


def test_delete_agent(svc):
    svc.create_agent(make_agent())
    svc.delete_agent("a1")
    with pytest.raises(AgentNotFound):
        svc.get_agent("a1")


def test_delete_unknown_raises(svc):
    with pytest.raises(AgentNotFound):
        svc.delete_agent("unbekannt")


def test_upsert_creates_if_not_exists(svc):
    svc.upsert_agent(make_agent())
    assert svc.get_agent("a1").id == "a1"


def test_upsert_updates_if_exists(svc):
    svc.create_agent(make_agent(name="Alt"))
    svc.upsert_agent(make_agent(name="Neu"))
    assert svc.get_agent("a1").name == "Neu"
