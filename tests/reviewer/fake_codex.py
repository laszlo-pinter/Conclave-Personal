"""Ersatz fuer ``codex exec`` in den Tests des zweiten Backends (conclave#152). Kostet nichts.

Liest die Schalter wie Codex: ``-C`` (Arbeitsverzeichnis) und ``-c mcp_servers.<name>.<feld>=<TOML>``, den Auftrag
aus stdin (``-``). Startet den Board-Server genau nach diesen Angaben, liest das Ticket, setzt das Ergebnis und
schreibt, was er gesehen hat, als JSON nach ``FAKE_CODEX_REPORT``.
"""

import asyncio
import json
import os
import re
import sys
import tomllib

from mcp import Client, StdioServerParameters


def parse(args: list[str]) -> dict:
    seen = {"flags": [], "servers": {}, "cwd": None, "model": None}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-C", "-s", "-m", "--color") and i + 1 < len(args):
            value = args[i + 1]
            if arg == "-C":
                seen["cwd"] = value
            elif arg == "-m":
                seen["model"] = value
            seen["flags"] += [arg, value]
            i += 2
            continue
        if arg == "-c" and i + 1 < len(args):
            key, _, raw = args[i + 1].partition("=")
            value = tomllib.loads(f"v = {raw}")["v"]
            parts = key.split(".")
            if parts[0] == "mcp_servers":
                seen["servers"].setdefault(parts[1], {})[parts[2]] = value
            else:
                seen.setdefault("config", {})[key] = value
            i += 2
            continue
        seen["flags"].append(arg)
        i += 1
    return seen


async def review(seen: dict, ask: str) -> dict:
    key = re.search(r"Reviewe das Ticket (\S+?)\.", ask).group(1)
    board = seen["servers"]["conclave"]
    params = StdioServerParameters(command=board["command"], args=board["args"],
                                   env={**os.environ, **board.get("env", {})})
    async with Client(params) as client:
        tools = sorted(t.name for t in (await client.list_tools()).tools)
        got = await client.call_tool("conclave_board_get", {"task": key})
        done = await client.call_tool("conclave_board_review", {
            "task": key, "state": "passed", "comment": "Urteil: gruen\nBlockierend:\n- keine\n— Probe (fake codex)",
            "blocking": 0, "suggestions": 0, "checked": "probe"})
    return {"key": key, "tools": tools, "get_error": got.is_error, "review_error": done.is_error}


def main() -> int:
    args = sys.argv[1:]
    ask = sys.stdin.read() if args and args[-1] == "-" else ""
    seen = parse(args)
    report = {"argv": args, "seen": seen, "ask": ask, "cwd_now": os.getcwd(), "env_names": sorted(os.environ)}
    report.update(asyncio.run(review(seen, ask)))
    with open(os.environ["FAKE_CODEX_REPORT"], "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False)
    print("Probe-Review gesetzt (fake codex)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
