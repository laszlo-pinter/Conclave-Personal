"""T5: Erweiterungspunkt ``BoardPolicy`` im Kern, mit einer Test-Policy (ohne Team-Code).

- Rechte je Aktion und Projekt (write, comment, approve, release, control:*)
- Auswahl in next_task (``claimable``) und Zustaendigkeit (``assignee_for``)
- Regeln beim Statuswechsel unter einer Sperre (``lock_key``, ``check_status_change``)
- Ereignisse fuer ein Audit-Log (``record``)
- Aenderungszaehler je sichtbarem Projekt, Steuertickets mit Geltung ``mine``,
  haengende Tickets (``stuck``, ``release``)
Personal (``PersonalPolicy``) laeuft mit der ganzen Suite unveraendert.
"""

from datetime import timedelta

import pytest

from conclave_board.application.board import BoardError, BoardService
from conclave_board.application.policy import BoardPolicy, PersonalPolicy
from conclave_board.domain.principal import HUMAN_PRINCIPAL, Principal
from conclave_board.infrastructure.migrations import run_board_migrations
from conclave_board.infrastructure.sqlite.board_repository import SQLiteBoardRepository
from conclave_board.infrastructure.sqlite.connection import ThreadLocalConnection

ANNA = Principal("human", actor_id="anna")                         # approver in api
BEN = Principal("human", actor_id="ben")                           # member in api
VERA = Principal("human", actor_id="vera")                         # viewer in api
ANNA_AGENT = Principal("agent", actor_id="anna")
BEN_AGENT = Principal("agent", actor_id="ben")


class RolePolicy(BoardPolicy):
    ROLES = {"anna": "approver", "ben": "member", "vera": "viewer"}

    def __init__(self):
        self.events = []
        self.locks = []

    def can(self, principal, action, project, task=None):
        role = self.ROLES.get(principal.actor_id, "viewer")
        if action in ("read",):
            return True
        if action in ("write", "comment"):
            return role in ("member", "approver")
        if action == "release":
            return role == "approver" or (task is not None and task.assignee == principal.actor_id)
        if action == "control:mine":
            return principal.is_human and role in ("member", "approver")
        return principal.is_human and role == "approver"            # approve, control:project, control:all

    def claimable(self, principal, task):
        return task.assignee in (None, principal.actor_id)

    def assignee_for(self, principal):
        return principal.actor_id

    def lock_key(self, principal, task, new_status):
        self.locks.append((task.ref, new_status))
        return f"assignee:{task.assignee}"

    def check_status_change(self, service, principal, task, new_status):
        if new_status == "review" and task.title == "verboten":
            raise BoardError("Regel verletzt", 409, "RuleViolation")

    def record(self, principal, event, project, target, detail):
        self.events.append((event, principal.actor_id, project, target))


@pytest.fixture
def board(tmp_path):
    conn = ThreadLocalConnection(tmp_path / "board.db")
    run_board_migrations(conn)
    service = BoardService(SQLiteBoardRepository(conn, autocommit=True), policy=RolePolicy())
    service.create_project(ANNA, "api", "API")
    service.create_project(ANNA, "web", "Web")
    return service


def test_personal_policy_is_the_default():
    assert isinstance(BoardService(object()).policy, PersonalPolicy)
    personal = PersonalPolicy()
    assert personal.can(HUMAN_PRINCIPAL, "approve", "api") and not personal.can(Principal("agent"), "approve", "api")
    assert personal.can(Principal("agent"), "write", "api") and personal.claimable(Principal("agent"), None)
    assert personal.assignee_for(HUMAN_PRINCIPAL) is None


def test_viewer_reads_but_cannot_write_or_comment(board):
    board.create_task(BEN, "api", "von Ben")
    assert board.list_tasks("api")
    with pytest.raises(BoardError, match="Nur lesen"):
        board.create_task(VERA, "api", "von Vera")
    with pytest.raises(BoardError, match="Nur lesen"):
        board.add_comment(VERA, "api#1", "x")
    with pytest.raises(BoardError, match="Nur lesen"):
        board.update_task(VERA, "api#1", title="neu")


def test_member_cannot_approve_rank_or_unmark(board):
    board.create_task(BEN, "api", "T", human=True)
    with pytest.raises(BoardError, match="Freigabe-Recht"):
        board.update_task(BEN, "api#1", status="done")
    with pytest.raises(BoardError, match="Rang"):
        board.update_task(BEN, "api#1", rank=5)
    with pytest.raises(BoardError, match="nur fuer Menschen"):
        board.update_task(BEN, "api#1", human=False)
    with pytest.raises(BoardError, match="Freigabe-Recht"):
        board.delete_task(BEN, "api#1")
    board.update_task(ANNA, "api#1", status="done")
    assert ("approval", "anna", "api", "api#1") in board.policy.events


def test_next_task_respects_claimable_and_sets_the_assignee(board):
    board.create_task(ANNA, "api", "erstes")
    board.create_task(ANNA, "api", "zweites")
    taken = board.next_task(BEN_AGENT, "api")
    assert taken.ref == "api#1" and taken.assignee == "ben"
    history = [(e.field_name, e.new_value) for e in board.history("api#1")]
    assert ("assignee", "ben") in history
    board.release_task(ANNA, "api#1")                                 # Approver gibt frei
    released = board.get_task("api#1")
    assert released.status == "todo" and released.assignee is None
    # Nacharbeit bleibt beim Zustaendigen: Ticket von Ben ist fuer Anna nicht uebernehmbar
    board.next_task(BEN_AGENT, "api", task="api#1")
    board.update_task(BEN_AGENT, "api#1", status="review")
    board.review(Principal("reviewer"), "api#1", "rework", "gelb")
    assert board.get_task("api#1").assignee == "ben"
    assert board.next_task(ANNA_AGENT, "api").ref == "api#2"         # api#1 gehoert Ben
    with pytest.raises(BoardError, match="jemand anderem"):
        board.next_task(ANNA_AGENT, "api", task="api#1")
    assert board.next_task(BEN_AGENT, "api").ref == "api#1"


def test_release_only_by_own_human_or_approver(board):
    board.create_task(ANNA, "api", "T")
    board.next_task(BEN_AGENT, "api")
    with pytest.raises(BoardError, match="Freigeben"):
        board.release_task(VERA, "api#1")
    with pytest.raises(BoardError, match="Sache des Menschen"):
        board.release_task(BEN_AGENT, "api#1")
    board.release_task(BEN, "api#1")                                  # eigener Mensch
    assert ("release", "ben", "api", "api#1") in board.policy.events


def test_status_change_rules_run_under_the_lock_and_block_the_write(board):
    board.create_task(BEN, "api", "verboten")
    board.next_task(BEN_AGENT, "api")
    with pytest.raises(BoardError, match="Regel verletzt"):
        board.update_task(BEN_AGENT, "api#1", status="review")
    assert board.get_task("api#1").status == "doing"                 # nichts geschrieben
    assert ("api#1", "review") in board.policy.locks


def test_rank_and_control_are_recorded(board):
    board.create_task(BEN, "api", "T")
    board.update_task(ANNA, "api#1", rank=3)
    board.create_task(ANNA, "api", "Pause", kind="control", control="pause", scope="project")
    kinds = [e[0] for e in board.policy.events]
    assert "rank" in kinds and "control" in kinds
    with pytest.raises(BoardError, match="Geltung 'project'"):
        board.create_task(BEN, "api", "Pause", kind="control", control="pause", scope="project")


def test_pause_for_my_agents_stops_only_them(board):
    board.create_task(ANNA, "api", "Arbeit")
    board.create_task(ANNA, "api", "Arbeit 2")
    board.create_task(BEN, "api", "Ben macht Pause", kind="control", control="pause", scope="mine")
    with pytest.raises(BoardError, match="Pausiert"):
        board.next_task(BEN_AGENT, "api")
    assert board.next_task(ANNA_AGENT, "api").ref == "api#1"
    assert [p["scope"] for p in board.control_state(principal=BEN_AGENT)["pauses"]] == ["mine"]
    assert board.control_state(principal=ANNA_AGENT)["pauses"] == []


def test_pause_for_my_agents_in_personal_applies_to_all(tmp_path):
    conn = ThreadLocalConnection(tmp_path / "p.db")
    run_board_migrations(conn)
    board = BoardService(SQLiteBoardRepository(conn, autocommit=True))
    board.create_project(HUMAN_PRINCIPAL, "api", "API")
    board.create_task(HUMAN_PRINCIPAL, "api", "Arbeit")
    board.create_task(HUMAN_PRINCIPAL, "api", "Pause", kind="control", control="pause", scope="mine")
    with pytest.raises(BoardError, match="Pausiert"):
        board.next_task(Principal("agent"), "api")


def test_change_token_counts_only_visible_projects(board):
    scoped = Principal("agent", actor_id="ben", projects=frozenset({"api"}))
    board.create_task(BEN, "api", "T")
    before = board.change_token_for(scoped)
    board.create_task(ANNA, "web", "anderswo")
    board.add_comment(ANNA, "web#1", "auch anderswo")
    assert board.change_token_for(scoped) == before                   # fremde Aenderungen zaehlen nicht
    board.add_comment(BEN, "api#1", "hier")
    assert board.change_token_for(scoped) > before
    assert board.change_token_for(HUMAN_PRINCIPAL) == board._repo.change_token()


def test_stuck_lists_long_running_tickets(board):
    board.create_task(ANNA, "api", "T")
    board.next_task(BEN_AGENT, "api")
    assert board.stuck(ANNA, "api", timedelta(hours=1)) == []
    stuck = board.stuck(ANNA, "api", timedelta(seconds=0))
    assert [t.ref for t, _ in stuck] == ["api#1"] and stuck[0][1] is not None


class OnlyApiApprover(RolePolicy):
    """Anna gibt nur in api frei; jede Freigabe-Pruefung muss das Projekt nennen."""

    def can(self, principal, action, project, task=None):
        if action == "approve":
            self.locks.append(("approve", project))
            return principal.actor_id == "anna" and project == "api"
        return super().can(principal, action, project, task)


def test_every_approval_check_names_the_project(tmp_path):
    conn = ThreadLocalConnection(tmp_path / "a.db")
    run_board_migrations(conn)
    board = BoardService(SQLiteBoardRepository(conn, autocommit=True), policy=RolePolicy())
    board.create_project(ANNA, "api", "API")
    board.create_project(ANNA, "web", "Web")
    board.create_task(ANNA, "api", "A")
    board.create_task(ANNA, "web", "W")
    board.policy = OnlyApiApprover()
    board.create_initiative(ANNA, "api", "sich", "S")
    board.update_initiative(ANNA, "api", "sich", title="S2")
    board.assign_initiative(ANNA, "api#1", "sich")
    board.delete_task(ANNA, "api#1")
    for call in (lambda: board.create_initiative(ANNA, "web", "x", "X"),
                 lambda: board.delete_task(ANNA, "web#1"),
                 lambda: board.update_task(ANNA, "web#1", status="done")):
        with pytest.raises(BoardError, match="Freigabe-Recht"):
            call()
    assert ("approve", None) not in board.policy.locks
