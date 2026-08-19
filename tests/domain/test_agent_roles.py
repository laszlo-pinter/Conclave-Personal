from conclave.domain.agent_roles import list_agent_roles, role_prompt


def test_list_agent_roles_returns_personal_roles():
    roles = list_agent_roles()
    ids = {role["id"] for role in roles}

    assert {"writer", "reviewer", "critic", "researcher", "planner", "custom"} <= ids
    assert "judge" not in ids


def test_role_prompt_uses_name_and_topic():
    prompt = role_prompt("reviewer", "Ada", "Release Notes")

    assert "Ada" in prompt
    assert "Release Notes" in prompt
    assert "Reviewer" in prompt


def test_unknown_role_prompt_is_empty():
    assert role_prompt("unknown", "Ada") == ""
