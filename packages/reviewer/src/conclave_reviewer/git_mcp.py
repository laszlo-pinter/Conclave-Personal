"""git_mcp: read-only git access for the reviewer, as a minimal MCP server (stdio).

The reviewer runs with --restricted, so it has no shell. This server is its only
way into git: fixed subcommands, fixed flags, checked arguments. Nothing here can
write files, change refs or run configured external programs.

    python -I git_mcp.py --repo <checkout>

Wird als Datei gestartet (``-I``: isoliert, ohne Benutzer-site und ohne das aktuelle Verzeichnis
im Suchpfad) und nutzt deshalb nur die Standardbibliothek.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_OUTPUT = 60_000
# A revision: branch, tag, hash, HEAD~2, main^, origin/main. Never an option.
REV = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./~^-]{0,199}\Z")
# Applied to every call; turns off external diff/textconv drivers and pagers.
BASE = ["git", "--no-pager", "-c", "core.pager=cat", "-c", "diff.external=", "-c", "core.fsmonitor=false"]
DIFF_FLAGS = ["--no-ext-diff", "--no-textconv", "--no-color"]

TOOLS = [
    {"name": "status", "description": "git status --short --branch",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "branches", "description": "Alle Branches mit letztem Commit (git branch -a -v)",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "log", "description": "git log --oneline fuer eine Revision, optional nur fuer einen Pfad",
     "inputSchema": {"type": "object", "properties": {
         "rev": {"type": "string", "default": "HEAD"},
         "max_count": {"type": "integer", "default": 30, "maximum": 200},
         "path": {"type": "string"}}}},
    {"name": "show", "description": "Ein Commit mit Statistik und Patch, optional nur fuer einen Pfad",
     "inputSchema": {"type": "object", "required": ["rev"], "properties": {
         "rev": {"type": "string"}, "path": {"type": "string"}}}},
    {"name": "diff", "description": "Aenderungen von head gegenueber dem gemeinsamen Vorfahren mit base (git diff base...head)",
     "inputSchema": {"type": "object", "required": ["base", "head"], "properties": {
         "base": {"type": "string"}, "head": {"type": "string"},
         "path": {"type": "string"}, "stat_only": {"type": "boolean", "default": False}}}},
    {"name": "file", "description": "Inhalt einer Datei in einer Revision (git show rev:path)",
     "inputSchema": {"type": "object", "required": ["rev", "path"], "properties": {
         "rev": {"type": "string"}, "path": {"type": "string"}}}},
]


class Refused(ValueError):
    pass


def rev(value) -> str:
    value = "HEAD" if value is None else value
    if not isinstance(value, str) or not REV.match(value) or ".." in value:
        raise Refused(f"ungueltige Revision: {value!r}")
    return value


def rel_path(repo: Path, value) -> str:
    if not isinstance(value, str) or not value or value.startswith("-") or ":" in value or "\0" in value:
        raise Refused(f"ungueltiger Pfad: {value!r}")
    resolved = (repo / value).resolve()
    if resolved != repo and repo not in resolved.parents:
        raise Refused(f"Pfad ausserhalb des Repositorys: {value!r}")
    return resolved.relative_to(repo).as_posix()


ARGS = {t["name"]: set(t["inputSchema"]["properties"]) for t in TOOLS}


def build(repo: Path, name: str, args: dict) -> list[str]:
    if name not in ARGS:
        raise Refused(f"unbekanntes Tool: {name!r}")
    if not isinstance(args, dict) or set(args) - ARGS[name]:
        raise Refused(f"unbekannte Argumente fuer {name}: {sorted(set(args) - ARGS[name]) if isinstance(args, dict) else args!r}")
    path = [rel_path(repo, args["path"])] if args.get("path") else []
    if name == "status":
        return ["status", "--short", "--branch"]
    if name == "branches":
        return ["branch", "--list", "-a", "-v", "--no-color"]
    if name == "log":
        count = args.get("max_count", 30)
        if not isinstance(count, int) or not 1 <= count <= 200:
            raise Refused("max_count muss zwischen 1 und 200 liegen")
        return ["log", "--oneline", "--decorate", "--no-color", f"--max-count={count}", rev(args.get("rev")), "--", *path]
    if name == "show":
        return ["show", "--stat", "--patch", *DIFF_FLAGS, rev(args.get("rev")), "--", *path]
    if name == "diff":
        stat = ["--stat"] if args.get("stat_only") else ["--stat", "--patch"]
        return ["diff", *stat, *DIFF_FLAGS, f"{rev(args.get('base'))}...{rev(args.get('head'))}", "--", *path]
    if name == "file":
        return ["show", "--no-textconv", f"{rev(args.get('rev'))}:{rel_path(repo, args.get('path'))}"]
    raise Refused(f"unbekanntes Tool: {name!r}")


def run_git(repo: Path, name: str, args: dict) -> tuple[str, bool]:
    try:
        cmd = BASE + build(repo, name, args or {})
    except Refused as e:
        return str(e), True
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out = subprocess.run(cmd, cwd=repo, capture_output=True, stdin=subprocess.DEVNULL, timeout=30, env=env,
                         text=True, encoding="utf-8", errors="replace")
    text = out.stdout if out.returncode == 0 else (out.stderr or out.stdout)
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n[... gekuerzt, {len(text)} Zeichen insgesamt; Pfad angeben oder stat_only nutzen]"
    return text or "(keine Ausgabe)", out.returncode != 0


def handle(repo: Path, msg: dict):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "git-readonly", "version": "1"}}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        text, failed = run_git(repo, params.get("name"), params.get("arguments"))
        return {"content": [{"type": "text", "text": text}], "isError": failed}
    if method == "ping":
        return {}
    raise LookupError(method)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    repo = Path(parser.parse_args().repo).resolve()
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:
            continue                      # notifications need no answer
        try:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(repo, msg)}
        except LookupError as e:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"unknown method {e}"}}
        except Exception as e:            # keep serving; report the error to the client
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(e)}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
