"""Welcher Stand geprueft wird: die Commits und Branches, die ein Ticket nennt (P7, Fix aus #113).

Massgeblich ist der neueste Kommentar des umsetzenden Agenten, der einen Commit nennt. Ein Projekt
kann mehrere Checkouts haben (etwa eine Bibliothek und eine Anwendung); in jedem wird gesucht.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Ein Commit in einem Kommentar des umsetzenden Agenten, z. B. `c6487d7`
COMMIT_REF = re.compile(r"`([0-9a-f]{7,40})`")
BRANCH_REF = re.compile(r"Branch:\*{0,2}\s*`([A-Za-z0-9_./-]{1,100})`")
# Form fuer mehrere Repos (P7): **Kern:** `feature-x` @ `a07cda0`
BRANCH_AT = re.compile(r"`([A-Za-z0-9_./-]{1,100})`\s*@\s*`[0-9a-f]{7,40}`")
GIT = ["git", "--no-pager", "-c", "core.pager=cat", "-c", "core.fsmonitor=false"]


def git(repo: str, *args: str) -> str:
    out = subprocess.run([*GIT, "-C", repo, *args], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {(out.stderr or out.stdout).strip()[:300]}")
    return out.stdout.strip()


def fetch(repo: str) -> None:
    """Neuen Stand aus dem Git-Server holen (Team-Server, TR2); der Zugang ist dort nur lesend."""
    git(repo, "fetch", "--all", "--prune", "--quiet")


def repos_for(cfg: dict, project: str) -> list[str]:
    """Checkouts eines Projekts: ein Pfad (alte Form) oder eine Liste (P7)."""
    value = (cfg.get("projects") or {}).get(project)
    if not value:
        return []
    return [value] if isinstance(value, str) else [str(v) for v in value]


def repo_name(repo: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", Path(repo).name) or "repo"


def git_server(index: int, repo: str) -> str:
    """Name des git-Servers eines Repos: "git" fuer das erste, git_<name> fuer weitere."""
    return "git" if index == 0 else "git_" + re.sub(r"[^A-Za-z0-9]", "_", Path(repo).name).lower()[:40]


def named_refs(detail: dict, author: str) -> tuple[list[str], list[str]]:
    """Commits und alle Branches aus dem neuesten Kommentar des umsetzenden Agenten, der einen Commit nennt."""
    for comment in reversed(detail.get("comments", [])):
        if comment.get("origin") != "agent" or comment.get("author_name") == author:
            continue
        hashes = COMMIT_REF.findall(comment.get("body", ""))
        if hashes:
            branches = BRANCH_REF.findall(comment["body"]) + BRANCH_AT.findall(comment["body"])
            return hashes, list(dict.fromkeys(branches))
    return [], []


def named_commits(detail: dict, author: str) -> tuple[list[str], str | None]:
    """Commits (und der erste Branch) aus dem neuesten Kommentar des umsetzenden Agenten."""
    hashes, branches = named_refs(detail, author)
    return hashes, branches[0] if branches else None


def pick_commit(repo: str, hashes: list[str]) -> str | None:
    """Der neueste der genannten Commits, die es im Repository gibt (voller Hash)."""
    found = []
    for h in dict.fromkeys(hashes):
        try:
            full = git(repo, "rev-parse", "--verify", "--quiet", f"{h}^{{commit}}")
            found.append((int(git(repo, "log", "-1", "--format=%ct", full)), full))
        except RuntimeError:
            continue
    return max(found)[1] if found else None


def exists(repo: str, commit: str) -> bool:
    try:
        git(repo, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
        return True
    except RuntimeError:
        return False


def is_ancestor(repo: str, commit: str, head: str) -> bool:
    try:
        git(repo, "merge-base", "--is-ancestor", commit, head)
        return True
    except RuntimeError:
        return False


def branch_head(repo: str, branch: str, remote_first: bool = False) -> str | None:
    """Kopf des Branches: lokal, sonst der von origin. ``remote_first`` (Team-Server mit fetch, TR2): erst
    origin, denn dort zaehlt der Stand im Git-Server; die lokalen Branches des Checkouts bleiben alt."""
    refs = [f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"]
    for ref in (refs[::-1] if remote_first else refs):
        try:
            return git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        except RuntimeError:
            continue
    return None


def find_state(repo: str, hashes: list[str], branches: list[str],
               remote_first: bool = False) -> tuple[str, str | None] | None:
    """(Commit, Branch) fuer ein Repo.

    Ein genannter Commit auf einem genannten Branch dieses Repos hat Vorrang (der neueste davon),
    damit ein nur im Text erwaehnter Commit nicht den zu pruefenden ersetzt; sonst der neueste
    genannte Commit; sonst der Kopf eines genannten Branches."""
    for branch in branches:
        head = branch_head(repo, branch, remote_first)
        on_branch = [h for h in hashes if head and exists(repo, h) and is_ancestor(repo, h, head)]
        commit = pick_commit(repo, on_branch) if on_branch else None
        if commit is not None:
            return commit, branch
    commit = pick_commit(repo, hashes) if hashes else None
    if commit is not None:
        for branch in branches:                     # der genannte Branch, der den Commit enthaelt
            head = branch_head(repo, branch, remote_first)
            if head and is_ancestor(repo, commit, head):
                return commit, branch
        return commit, None                         # kein genannter Branch dieses Repos enthaelt ihn
    for branch in branches:
        head = branch_head(repo, branch, remote_first)
        if head:
            return head, branch
    return None
