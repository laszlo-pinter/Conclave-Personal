# src/conclave/cli/watch.py
"""Standalone Watcher — pollt eine Conversation ueber die HTTP-API.

Nutzung:
    python -m conclave.cli.watch <conversation_id> [--api http://localhost:8000] [--interval 5] [--since 0] [--full]

Gibt neue Nachrichten auf stdout aus. Ctrl+C zum Beenden.
Kann von jedem Client genutzt werden der HTTP-Zugriff auf die API hat.
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

from conclave.runtime.api_token import read_token


def is_http_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def fetch_conversation(api: str, conv_id: str, api_key: str = "") -> dict | None:
    if not is_http_url(api):
        return None
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{api}/conversations/{conv_id}", headers=headers)
    try:
        # Schema oben auf http(s) geprueft, kein file:// o. ae.
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            return json.loads(resp.read())
    except Exception:
        return None


def print_message(m: dict, full: bool = False) -> None:
    author = m.get("author_id") or "User"
    seq = m.get("sequence", "?")
    content = m.get("content", "").strip()
    if full:
        print(f"\n[#{seq} {author}]")
        print(content)
        print()
    else:
        lines = content.split("\n")
        first = lines[0][:120] + ("…" if len(lines[0]) > 120 else "")
        more = f" (+{len(lines)-1} Zeilen)" if len(lines) > 1 else ""
        print(f"[#{seq} {author}] {first}{more}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Conclave Conversation Watcher")
    parser.add_argument("conversation_id")
    parser.add_argument("--api", default="http://localhost:8000", help="API-URL (Default: http://localhost:8000)")
    parser.add_argument("--interval", type=int, default=5, help="Poll-Intervall in Sekunden (Default: 5)")
    parser.add_argument("--since", type=int, default=0, help="Ab welcher Sequence starten (Default: 0)")
    parser.add_argument("--full", action="store_true", help="Vollstaendige Nachrichten anzeigen (Default: erste Zeile)")
    parser.add_argument("--key", default="", help="API-Token (Default: CONCLAVE_API_KEY oder lokale Token-Datei)")
    args = parser.parse_args()
    if not is_http_url(args.api):
        parser.error("--api muss eine http(s)-URL sein")
    args.key = args.key or read_token()

    conv = fetch_conversation(args.api, args.conversation_id, args.key)
    if conv is None:
        print(f"Fehler: Conversation {args.conversation_id} nicht erreichbar", file=sys.stderr)
        sys.exit(1)

    topic = conv.get("topic", "")
    messages = conv.get("messages", [])
    last_seq = args.since

    print(f"=== Conclave Watch: {args.conversation_id[:8]}{'… ' + topic if topic else ''} ===")
    print(f"--- {len(messages)} Nachrichten, Intervall {args.interval}s, Ctrl+C zum Beenden ---")
    print()

    for m in messages:
        if m["sequence"] > last_seq:
            print_message(m, full=args.full)
            last_seq = m["sequence"]

    try:
        while True:
            time.sleep(args.interval)
            conv = fetch_conversation(args.api, args.conversation_id, args.key)
            if conv is None:
                continue
            for m in conv.get("messages", []):
                if m["sequence"] > last_seq:
                    print_message(m, full=args.full)
                    last_seq = m["sequence"]
    except KeyboardInterrupt:
        print("\n--- Watch beendet ---")


if __name__ == "__main__":
    main()
