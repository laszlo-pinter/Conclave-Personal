"""Automatischer Reviewer fuer das Conclave-Board (W1, Plan reviewer.md).

Ein eigener Prozess (``conclave-reviewer``), nicht Teil des Servers: Er beobachtet die Spalte
``review``, legt fuer jedes neue Ticket einen Worktree des genannten Commits an und startet dort
``claude -p`` ohne Oberflaeche. Der Reviewer liest das Repo und setzt das Ergebnis ueber
``conclave-mcp --reviewer``; Dateien aendern, pushen oder Tickets verschieben kann er nicht.

Aufteilung:
- ``refs``: welche Commits und Branches ein Ticket nennt und welcher Stand geprueft wird
- ``worktrees``: Worktrees anlegen und wieder entfernen
- ``command``: der Aufruf von ``claude -p`` mit seinen Tools und der MCP-Konfiguration
- ``git_mcp``: schreibgeschuetzter git-Zugang als MCP-Server (stdio)
- ``lock``: hoechstens ein Reviewer je Datenordner, auch gegenueber dem alten Watcher
- ``watch``: die Schleife (Board abfragen, Reviews starten, Zustand merken)
- ``cli``: ``conclave-reviewer run``

- ``paths``: Standardorte (Konfigurationsordner von Conclave Personal), ohne Import aus Personal

Eigenes Paket seit TR1 (Plan team-reviewer.md): Es nutzt nur die Standardbibliothek, HTTP und
``conclave_board.runtime`` und importiert nichts aus Conclave Personal (``conclave``) oder dem
einer Erweiterung des Boards (import-linter). Personal buendelt es; ``conclave.reviewer`` ist dort ein Alias.
"""
