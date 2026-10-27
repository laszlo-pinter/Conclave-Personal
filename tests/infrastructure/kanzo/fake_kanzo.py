"""Fake-Kanzo als MCP-Server (MCP-SDK 2.x), in-process ohne Netzwerk.

Bildet Kanzos Textausgabe nach (``task_detail`` in kanzo ``src/mcp.rs``):
Kommentare ohne IDs, ``human`` nur als Text in der Statuszeile, Fehler als
Tool-Fehler mit "no task ...".
"""

from dataclasses import dataclass, field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

TIME = "2026-10-27 20:12 UTC"


@dataclass
class FakeTask:
    project: str
    id: int
    title: str
    status: str = "todo"
    human: bool = False
    description: str = ""
    tags: list = field(default_factory=list)
    comments: list = field(default_factory=list)     # (author, body)

    @property
    def key(self):
        return f"{self.project}#{self.id}"


def task_detail(t: FakeTask) -> str:
    out = f"{t.key} {t.title}"
    if t.tags:
        out += " {" + ", ".join(t.tags) + "}"
    out += f"\nstatus: {t.status}"
    if t.human:
        out += ", human: for the user, not for agents"
    out += f", created {TIME}\n"
    if t.description:
        out += f"\n{t.description}\n"
    if t.comments:
        out += f"\nComments ({len(t.comments)}):\n"
        for author, body in t.comments:
            out += f"- {author}, {TIME}: {body}\n"
    return out.rstrip()


class FakeKanzo:
    def __init__(self):
        self.tasks: dict[str, FakeTask] = {}
        self.calls: list[tuple[str, dict]] = []
        self.server = MCPServer("kanzo")

        @self.server.tool()
        def get_task(id: str) -> str:
            self.calls.append(("get_task", {"id": id}))
            return task_detail(self._find(id))

        @self.server.tool()
        def add_comment(id: str, body: str, author: str | None = None) -> str:
            self.calls.append(("add_comment", {"id": id, "body": body, "author": author}))
            task = self._find(id)
            task.comments.append((author or "agent", body))
            return f"Comment added to {task.key} as {author}."

    def _find(self, key: str) -> FakeTask:
        if key not in self.tasks:
            raise ToolError(f"no task {key}")
        return self.tasks[key]

    def add(self, task: FakeTask) -> FakeTask:
        self.tasks[task.key] = task
        return task
