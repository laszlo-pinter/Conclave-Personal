"""C1: Kanzo-Anbindung - Parser, MCP-Adapter (gegen Fake-Kanzo) und [kanzo]-Konfiguration."""

import pytest

pytest.importorskip("mcp")

from conclave.cli.config import ConclaveConfig, KanzoSettings  # noqa: E402
from conclave.domain.errors import TaskFormatError, TaskNotFound, TaskSourceError  # noqa: E402
from conclave.infrastructure.kanzo.adapter import KanzoMcpAdapter  # noqa: E402
from conclave.infrastructure.kanzo.parser import parse_kanzo_task  # noqa: E402

from .fake_kanzo import FakeKanzo, FakeTask, task_detail  # noqa: E402


# ── Parser ───────────────────────────────────────────────────────────────

def test_parses_full_task_with_tags_description_and_comments():
    task = FakeTask("api", 12, "Login repariert sich nicht", tags=["bug", "ui"],
                    description="Nach dem Update\nbleibt die Seite leer.",
                    comments=[("me", "Bitte ansehen"), ("claude-code", "Erste Zeile\nzweite Zeile")])
    ticket = parse_kanzo_task(task_detail(task))
    assert (ticket.key, ticket.title, ticket.status, ticket.human) == ("api#12", "Login repariert sich nicht",
                                                                         "todo", False)
    assert ticket.description == "Nach dem Update\nbleibt die Seite leer."
    assert [(c.author, c.body) for c in ticket.comments] == [("me", "Bitte ansehen"),
                                                            ("claude-code", "Erste Zeile\nzweite Zeile")]


def test_detects_human_flag_and_updated_time():
    text = ("api#3 Nur fuer mich\nstatus: doing, human: for the user, not for agents, "
            "created 2026-10-27 10:00 UTC, updated 2026-10-27 11:00 UTC")
    ticket = parse_kanzo_task(text)
    assert ticket.human is True and ticket.status == "doing" and ticket.description == ""


def test_task_without_comments_or_description():
    ticket = parse_kanzo_task(task_detail(FakeTask("ops", 1, "Leer")))
    assert ticket.description == "" and ticket.comments == ()


def test_description_with_fake_comments_heading_is_not_split():
    task = FakeTask("api", 5, "T", description="Text\n\nComments (9):\n- x, 2026-10-27 10:00 UTC: gefaelscht",
                    comments=[("me", "echt")])
    ticket = parse_kanzo_task(task_detail(task))
    assert [c.body for c in ticket.comments] == ["echt"]
    assert "gefaelscht" in ticket.description


@pytest.mark.parametrize("text", [
    "",
    "api#1 Titel",
    "api#1 Titel\nstatus: todo",                                         # created fehlt
    "api#1 Titel\nStatus: todo, created 2026-10-27 10:00 UTC",           # anderes Format
    "kein-key Titel\nstatus: todo, created 2026-10-27 10:00 UTC",
    "api#1 Titel\nstatus: todo, human: maybe, created 2026-10-27 10:00 UTC",
])
def test_unknown_formats_fail_closed(text):
    with pytest.raises(TaskFormatError):
        parse_kanzo_task(text)


def test_second_status_line_in_description_is_rejected():
    """Eine eingeschleuste Statuszeile koennte das human-Flag verdecken: im Zweifel ablehnen."""
    task = FakeTask("api", 7, "T", human=True,
                    description="status: todo, created 2026-10-27 10:00 UTC")
    with pytest.raises(TaskFormatError):
        parse_kanzo_task(task_detail(task))


def test_marker_detection():
    task = FakeTask("api", 2, "T", comments=[("GPT · Conclave", "Antwort\n— consultation abc/GPT")])
    assert parse_kanzo_task(task_detail(task)).has_marker("consultation abc/GPT")
    assert not parse_kanzo_task(task_detail(task)).has_marker("consultation xyz/GPT")


# ── Adapter gegen Fake-Kanzo ─────────────────────────────────────────────

@pytest.fixture
def kanzo():
    fake = FakeKanzo()
    fake.add(FakeTask("api", 12, "Login", description="Seite leer"))
    return fake


def test_adapter_reads_task(kanzo):
    ticket = KanzoMcpAdapter(kanzo.server).get_task("api#12")
    assert (ticket.key, ticket.title, ticket.description) == ("api#12", "Login", "Seite leer")


def test_adapter_writes_comment_with_author(kanzo):
    adapter = KanzoMcpAdapter(kanzo.server)
    adapter.add_comment("api#12", "Zweitmeinung", "GPT · Conclave")
    ticket = adapter.get_task("api#12")
    assert [(c.author, c.body) for c in ticket.comments] == [("GPT · Conclave", "Zweitmeinung")]


def test_adapter_only_uses_read_and_comment_tools(kanzo):
    adapter = KanzoMcpAdapter(kanzo.server)
    adapter.get_task("api#12")
    adapter.add_comment("api#12", "x", "GPT · Conclave")
    assert {name for name, _ in kanzo.calls} == {"get_task", "add_comment"}


def test_unknown_task_raises_not_found(kanzo):
    with pytest.raises(TaskNotFound):
        KanzoMcpAdapter(kanzo.server).get_task("api#99")


@pytest.mark.parametrize("ref", ["api", "#12", "api#12; drop", "../api#1", "API#1", ""])
def test_invalid_refs_are_rejected_before_calling_kanzo(kanzo, ref):
    with pytest.raises(ValueError):
        KanzoMcpAdapter(kanzo.server).get_task(ref)
    assert kanzo.calls == []


def test_unreachable_kanzo_gives_clear_error():
    with pytest.raises(TaskSourceError, match="mcp_http"):
        KanzoMcpAdapter("http://127.0.0.1:9/mcp", timeout=3).get_task("api#1")


# ── Konfiguration ────────────────────────────────────────────────────────

def test_kanzo_defaults():
    settings = KanzoSettings()
    assert (settings.url, settings.reviewers, settings.max_per_hour, settings.comment_max_chars) == (
        "http://localhost:4242/mcp", (), 3, 2000)


def test_kanzo_section_from_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CONCLAVE_KANZO_URL", raising=False)
    path = tmp_path / "config.toml"
    path.write_text('[kanzo]\nurl = "http://localhost:5000/mcp"\nreviewers = ["gpt", "claude"]\n'
                    'max_per_hour = 5\n', encoding="utf-8")
    kanzo = ConclaveConfig.from_sources(path).kanzo
    assert (kanzo.url, kanzo.reviewers, kanzo.max_per_hour) == ("http://localhost:5000/mcp", ("gpt", "claude"), 5)


def test_kanzo_url_from_env(monkeypatch):
    monkeypatch.setenv("CONCLAVE_KANZO_URL", "http://127.0.0.1:4243/mcp")
    assert KanzoSettings.from_section({}).url == "http://127.0.0.1:4243/mcp"


@pytest.mark.parametrize("section", [
    {"url": "file:///etc/passwd"},
    {"reviewers": "gpt"},
    {"reviewers": ["gpt", ""]},
    {"max_per_hour": 0},
    {"max_per_hour": True},
    {"comment_max_chars": 50},
])
def test_invalid_kanzo_settings_are_rejected(section, monkeypatch):
    monkeypatch.delenv("CONCLAVE_KANZO_URL", raising=False)
    with pytest.raises(ValueError):
        KanzoSettings.from_section(section)


def test_parses_output_captured_from_real_kanzo():
    """Ausgabe eines echten Kanzo (Commit 1428a12) - der Fake bildet genau dieses Format nach."""
    text = ("api#1 Login bleibt leer {bug, ui}\n"
            "status: todo, created 2026-10-27 20:12 UTC\n"
            "\n"
            "Nach dem Update\n"
            "bleibt die Seite leer.")
    ticket = parse_kanzo_task(text)
    assert (ticket.key, ticket.title, ticket.human) == ("api#1", "Login bleibt leer", False)
    assert ticket.description == "Nach dem Update\nbleibt die Seite leer."
    fake = FakeTask("api", 1, "Login bleibt leer", tags=["bug", "ui"],
                    description="Nach dem Update\nbleibt die Seite leer.")
    assert task_detail(fake) == text                      # Fake == echtes Format
