# tests/domain/test_floor.py

import uuid
import pytest
from conclave.domain.conversation import Conversation
from conclave.domain.participant import Participant, ParticipantType
from conclave.domain.errors import FloorNotGranted, ParticipantNotRegistered


def make_conv(topic="") -> Conversation:
    return Conversation.create(topic=topic)


def add_model(conv: Conversation, pid="p1", name="Model A") -> Participant:
    p = Participant(
        id=pid, conversation_id=conv.id,
        participant_type=ParticipantType.MODEL, name=name,
    )
    conv.add_participant(p)
    return p


def test_conversation_has_empty_topic_by_default():
    conv = make_conv()
    assert conv.topic == ""


def test_conversation_stores_topic():
    conv = make_conv(topic="Klimawandel")
    assert conv.topic == "Klimawandel"


def test_floor_is_none_by_default():
    conv = make_conv()
    assert conv.floor is None


def test_grant_floor_sets_participant():
    conv = make_conv()
    add_model(conv, "p1")
    conv.grant_floor("p1")
    assert conv.floor == "p1"


def test_grant_floor_raises_for_unknown_participant():
    conv = make_conv()
    with pytest.raises(ParticipantNotRegistered):
        conv.grant_floor("unbekannt")


def test_revoke_floor_clears_floor():
    conv = make_conv()
    add_model(conv, "p1")
    conv.grant_floor("p1")
    conv.revoke_floor()
    assert conv.floor is None


def test_assert_has_floor_passes_for_correct_participant():
    conv = make_conv()
    add_model(conv, "p1")
    conv.grant_floor("p1")
    conv.assert_has_floor("p1")  # kein Fehler


def test_assert_has_floor_raises_for_wrong_participant():
    conv = make_conv()
    add_model(conv, "p1")
    add_model(conv, "p2", "Model B")
    conv.grant_floor("p1")
    with pytest.raises(FloorNotGranted) as exc:
        conv.assert_has_floor("p2")
    assert exc.value.participant_id == "p2"
    assert exc.value.floor_holder == "p1"


def test_assert_has_floor_raises_when_no_floor_granted():
    conv = make_conv()
    add_model(conv, "p1")
    with pytest.raises(FloorNotGranted) as exc:
        conv.assert_has_floor("p1")
    assert exc.value.floor_holder is None


def test_floor_transfers_between_participants():
    conv = make_conv()
    add_model(conv, "p1")
    add_model(conv, "p2", "Model B")
    conv.grant_floor("p1")
    conv.grant_floor("p2")
    assert conv.floor == "p2"
