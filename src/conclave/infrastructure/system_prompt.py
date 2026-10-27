"""System-Prompt fuer alle Adapter: Agent-Prompt, context_files, Chat-Regeln, Workspace-Hinweise.

Wird vom UniversalAdapter und den nativen Adaptern (Anthropic, OpenAI) gemeinsam
genutzt, damit alle Agenten denselben Kontext bekommen.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from conclave.application.workspace_security import (
    agent_read_limit_bytes,
    assert_size_allowed,
    is_agent_visible,
    resolve_workspace_path,
    workspace_root,
)
from conclave.domain.context_report import requested_context_files
from conclave.domain.conversation import Conversation
from conclave.infrastructure.log import get_logger

logger = get_logger("infrastructure.system_prompt")


def build_workspace_info() -> str:
    """Erstellt eine Workspace-Uebersicht fuer den System-Prompt.

    Die @read/@save/@workspace-Faehigkeiten werden immer erklaert. Das
    automatische Auflisten ALLER Workspace-Dateien ist standardmaessig AUS:
    es blaeht jeden System-Prompt auf (rekursiver os.walk ueber den ganzen
    Baum) und verleitet Agenten dazu, bei vagen Aufgaben proaktiv fremde
    Dateien wie 'Projektziel.md' zu lesen (Kontext-Leak). Gezielten Kontext
    liefert stattdessen 'context_files:' in den Chat-Regeln. Wer das alte
    Voll-Listing will, setzt CONCLAVE_WORKSPACE_AUTOLIST=1.
    """
    workspace = str(workspace_root())
    if not os.path.isdir(workspace):
        return ""
    info = (
        "Du hast Zugriff auf einen gemeinsamen Workspace.\n\n"
        "LESEN: Der Benutzer kann Dateien referenzieren mit @workspace/dateiname "
        "und der Inhalt wird automatisch in die Nachricht eingefuegt.\n"
        "Du selbst kannst eine konkrete, dir bekannte Datei lesen mit "
        "@read(pfad/zur/datei.py) in deiner Antwort. Lies nur Dateien, nach "
        "denen ausdruecklich gefragt wurde - erkunde nicht von dir aus den Workspace.\n\n"
        "SCHREIBEN: Du kannst Dateien im Workspace speichern. Verwende dazu:\n"
        "@save(dateiname.md)\n"
        "Hier steht der Dateiinhalt...\n"
        "@endsave\n"
        "Behaupte nicht selbst, dass die Datei gespeichert wurde. Das Backend "
        "fuehrt den Schreibvorgang aus und protokolliert das Ergebnis als Tool-Event."
    )
    if not os.environ.get("CONCLAVE_WORKSPACE_AUTOLIST"):
        return info
    try:
        files = []
        for root, dirs, filenames in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in filenames:
                if f.startswith("."):
                    continue
                rel = os.path.relpath(os.path.join(root, f), workspace)
                files.append(rel.replace("\\", "/"))
        if not files:
            return info
        listing = "\n".join(f"  - @workspace/{f}" for f in sorted(files))
        return info + f"\n\nVerfuegbare Dateien:\n{listing}"
    except Exception:
        return info


def collect_context_files(conversation: Conversation) -> tuple[str, list[dict], list[dict]]:
    """Laedt context_files aus der Conversation.

    context_files ist eine kommaseparierte Liste von Workspace-Pfaden
    im rules-Feld mit dem Prefix 'context_files:'.
    Format: Erste Zeile von rules = 'context_files: datei1.md, datei2.md'

    Returns: (Text fuer den System-Prompt, eingebundene [{path, bytes}],
    abgewiesene [{path, reason}])
    """
    root = workspace_root()
    parts = []
    loaded: list[dict] = []
    skipped: list[dict] = []
    for filepath in requested_context_files(getattr(conversation, "rules", "") or ""):
        # Dieselben Grenzen wie @workspace/ und @read(): kein absoluter Pfad,
        # kein Ausbruch aus dem Workspace, keine versteckten Pfade, Leselimit.
        resolved = resolve_workspace_path(filepath, root)
        if resolved is None or not resolved.path.is_file() or not is_agent_visible(resolved.path, root):
            logger.warning("context_files: '%s' ignoriert (ausserhalb des Workspace, versteckt oder fehlt)", filepath)
            skipped.append({"path": filepath, "reason": "not_found_or_not_allowed"})
            continue
        if not assert_size_allowed(resolved.path, agent_read_limit_bytes()):
            logger.warning("context_files: '%s' ignoriert (groesser als das Agent-Leselimit)", filepath)
            skipped.append({"path": filepath, "reason": "too_large"})
            continue
        try:
            content = resolved.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            skipped.append({"path": filepath, "reason": "unreadable"})
            continue
        parts.append(f"--- Kontext: {resolved.relative} ---\n{content}")
        loaded.append({"path": resolved.relative, "bytes": len(content.encode("utf-8"))})
    return ("\n\n".join(parts) if parts else ""), loaded, skipped


def load_context_files(conversation: Conversation) -> str:
    """Inhalt der context_files als Text (siehe collect_context_files)."""
    return collect_context_files(conversation)[0]


@dataclass(frozen=True)
class SystemPrompt:
    text: str | None
    parts: tuple[str, ...] = ()
    context_files: tuple[dict, ...] = ()
    skipped_context_files: tuple[dict, ...] = ()


def assemble_system_prompt(
    system_prompt: str | None, conversation: Conversation
) -> SystemPrompt:
    """Baut den System-Prompt und merkt sich, welche Bausteine enthalten sind."""
    parts = []
    names = []
    if system_prompt:
        parts.append(system_prompt)
        names.append("agent_prompt")
    # Kontext-Dateien als statischer Kontext (spart Tokens vs. Chat-Messages)
    context, loaded, skipped = collect_context_files(conversation)
    if context:
        parts.append(context)
        names.append("context_files")
    # Chat-Regeln (ohne context_files-Zeilen)
    rules = getattr(conversation, "rules", "") or ""
    clean_rules = "\n".join(
        line for line in rules.split("\n")
        if not line.strip().lower().startswith("context_files:")
    ).strip()
    if clean_rules:
        parts.append(f"Chat-Regeln:\n{clean_rules}")
        names.append("rules")
    workspace_info = build_workspace_info()
    if workspace_info:
        parts.append(workspace_info)
        names.append("workspace_info")
    return SystemPrompt(
        text="\n\n".join(parts) if parts else None,
        parts=tuple(names),
        context_files=tuple(loaded),
        skipped_context_files=tuple(skipped),
    )


def build_system_prompt(
    system_prompt: str | None, conversation: Conversation
) -> str | None:
    """Baut den kombinierten System-Prompt aus Agent-Prompt, Regeln, Kontext-Dateien und Workspace."""
    return assemble_system_prompt(system_prompt, conversation).text
