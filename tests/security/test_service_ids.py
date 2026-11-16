"""R15 (conclave#50): Die ID-Regel aus R4 gilt auch in den Diensten, nicht nur in der API.

So halten sich auch CLI, Restore-Pfade und kuenftige Aufrufer an die Regel.
"""

import pytest

from conclave.domain.agent import Agent
from conclave.domain.participant import ParticipantType

BAD = ["../x", ".", "..", "a/b", "a b", "x" * 65, "", "a#b", "a?b"]


@pytest.mark.parametrize("bad", BAD)
def test_agent_service_rejects_unsafe_ids(agent_service, bad):
    with pytest.raises(ValueError):
        agent_service.create_agent(Agent(id=bad, name="A", provider="openai", model="gpt"))


def test_agent_service_accepts_safe_ids(agent_service):
    agent_service.create_agent(Agent(id="claude-sonnet_4.5", name="A", provider="anthropic", model="m"))


@pytest.mark.parametrize("bad", BAD)
def test_conversation_service_rejects_unsafe_participant_ids(service, bad):
    conv = service.create_conversation()
    with pytest.raises(ValueError):
        service.register_participant(conv.id, bad, ParticipantType.MODEL, "P")


def test_api_and_services_share_one_rule():
    from conclave.api import app as api
    from conclave.domain import ids
    assert api.ID_RULE_ERROR == ids.ID_RULE_ERROR and api._valid_id is ids.valid_id
