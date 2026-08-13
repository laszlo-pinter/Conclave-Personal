from pathlib import Path

from conclave.runtime.assets import get_asset_root


ROOT = Path(__file__).resolve().parents[2]
HTML = get_asset_root() / "conclave-ui.html"


def test_personal_navigation_has_five_workspaces():
    html = HTML.read_text(encoding="utf-8")

    for tab in [
        'data-tab="conv">Studio',
        'data-tab="agents">Agents',
        'data-tab="workspace">Files',
        'data-tab="runs">Runs',
        'data-tab="settings">Settings',
    ]:
        assert tab in html

    assert 'data-tab="usage"' not in html
    assert "Registry" not in html


def test_personal_workspaces_have_main_surfaces():
    html = HTML.read_text(encoding="utf-8")

    for surface_id in [
        "registryMain",
        "workspaceMain",
        "runsMain",
        "settingsMain",
        "agentWorkbench",
        "workspaceMainList",
        "settingsRuntime",
    ]:
        assert f'id="{surface_id}"' in html


def test_no_dsgvo_vocabulary_in_user_interface():
    html = HTML.read_text(encoding="utf-8").lower()

    for forbidden in ["dsgvo", "consent", "dpa"]:
        assert forbidden not in html


def test_agent_form_uses_personal_roles():
    html = HTML.read_text(encoding="utf-8")

    for role in ["writer", "reviewer", "critic", "researcher", "planner", "judge", "custom"]:
        assert f'data-role="{role}"' in html

    for old_role in ["analytiker", "kritiker", "programmierer", "advocatus"]:
        assert f'data-role="{old_role}"' not in html
