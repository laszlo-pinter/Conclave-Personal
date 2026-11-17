"""Fester Stand zum Pruefen: der genannte Commit in einem eigenen Worktree.

Das erste Repo ist das Arbeitsverzeichnis des Reviewers; weitere liegen darin unter
``_repos/<name>``, damit die Datei-Tools (``--restricted`` haelt sie im Arbeitsverzeichnis) sie
erreichen (P7).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from conclave.reviewer.refs import git, repo_name


def worktree_path(worktrees: Path, repo: str, key: str, inside: Path | None = None) -> Path:
    return (inside / "_repos" / repo_name(repo)) if inside else worktrees / re.sub(r"[^A-Za-z0-9_-]", "-", key)


def add_worktree(worktrees: Path, repo: str, key: str, commit: str, inside: Path | None = None) -> Path:
    """Worktree von ``commit``; mit ``inside`` unter ``<inside>/_repos/<repo>`` (weitere Repos, P7)."""
    worktrees.mkdir(parents=True, exist_ok=True)
    path = worktree_path(worktrees, repo, key, inside)
    remove_worktree(repo, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--detach", "--force", str(path), commit)
    return path


def remove_worktree(repo: str, path: Path) -> None:
    try:
        git(repo, "worktree", "remove", "--force", str(path))
    except RuntimeError:
        pass
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    try:
        git(repo, "worktree", "prune")
    except RuntimeError:
        pass
