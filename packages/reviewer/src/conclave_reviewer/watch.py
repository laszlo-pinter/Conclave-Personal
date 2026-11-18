"""Die Schleife des Reviewers: Spalte ``review`` beobachten, Reviews starten, Zustand merken.

Fragt den Aenderungszaehler ``GET /board/v1/changes`` ab und liest die Spalte review
(``GET /board/v1/tasks?status=review``) nur nach einer Aenderung, immer mit dem Reviewer-Token (nie
Agent- oder Mensch-Token). Etwa alle 60 s meldet er sich mit einem Herzschlag (W3); beim Start gibt
er haengende Reviews (``running`` ohne Lauf) frei und prueft sie neu.
Fuer jedes neu nach review geschobene Ticket: Review-Status ``running``, Worktree(s) der genannten
Commits, ``claude -p`` dort; der Reviewer setzt das Ergebnis selbst ueber ``conclave-mcp --reviewer``.
Endet der Lauf ohne Ergebnis (Zeitlimit, Absturz), bleibt der Status ``running`` und ein Kommentar
sagt warum; Conclave zeigt das als haengendes Review.

Ein Projekt kann mehrere Checkouts haben (P7, ``projects.conclave = ['...', '...']``): Die genannten
Commits werden in jedem gesucht; jedes Repo mit Treffer bekommt einen eigenen Worktree und einen
eigenen git-Server. Das Verhalten entspricht dem alten Watcher (``kanzo-reviewer/watcher.py``).

Am Team-Server (TR2, ``server = "team"``): https mit dem CA-Buendel aus der Konfiguration, ohne Proxy
und ohne Umleitungen (``transport``); das Token aus der Anmeldeinformationsverwaltung oder einer Datei;
vor jedem Review ``git fetch`` in den Checkouts; genannte Commits, die es dort nicht gibt, ergeben ein
rotes Review ohne claude ("Commits nicht im Git-Server").
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from conclave_reviewer import command, refs, transport, worktrees
from conclave_reviewer.command import BOARDS

LOG_LIMIT = 1_000_000
# Festes Review-Format wie im Prompt (Urteil, Geprueft, Blockierend, Vorschlaege, Erledigt, Nicht geprueft)
MISSING_ON_SERVER = (
    "Urteil: rot\nGeprüft: –\nBlockierend:\n- B1 Commits nicht im Git-Server: {hashes}. Auf dem Server prüft "
    "der Reviewer nur, was gepusht ist. Bitte den Branch pushen (oder den Commit im Kommentar berichtigen) und "
    "das Ticket erneut nach review schieben.\nVorschläge:\n- keine\nErledigt aus dem letzten Review: –\n"
    "Nicht geprüft:\n- der Code: Ohne die Commits im Git-Server gibt es keinen Stand zum Prüfen.\n"
    "— automatisches Review (Reviewer, ohne claude: Commits fehlen), nicht von Laszlo freigegeben")


def load_config(path: Path) -> dict:
    """Die Konfiguration des alten Watchers (``config.toml``); W2 bringt einen eigenen Abschnitt."""
    with path.open("rb") as f:
        cfg = tomllib.load(f)
    board = cfg.setdefault("board", "conclave")
    if board != "conclave":
        raise SystemExit(f"board = {board!r} wird nicht mehr unterstuetzt; nur noch das Conclave-Board.")
    return cfg


class Reviewer:
    """Ein Reviewer mit Konfiguration, Datenordner (Log, Zustand, Sperre, Worktrees) und Prompt-Ordner."""

    current_task: str | None = None                   # fuer den Herzschlag: welches Ticket gerade geprueft wird
    _last_changes = None
    _heartbeat_ok = True

    def __init__(self, cfg: dict, data_dir: Path, base_dir: Path | None = None, prompt: str | None = None) -> None:
        """``prompt``: der Text (W2, Ressource oder ``prompt_file``); ohne ihn die alte Form aus ``base_dir``."""
        self.cfg = cfg
        self.data_dir = data_dir
        self.base_dir = base_dir or data_dir           # alte Form: dort liegt die Prompt-Datei
        self.prompt = prompt
        self.log_file = data_dir / "reviewer.log"
        self.lock_file = data_dir / "reviewer.lock"
        self.mcp_config = data_dir / "mcp-board.json"
        self.worktrees = data_dir / "worktrees"
        self.state_file = data_dir / "state.json"
        self.status_file = data_dir / "status.json"      # fuer conclave-reviewer status (W4)
        self.mcp_token = data_dir / "mcp-reviewer.token"  # nur waehrend eines Reviews, bei Token aus der
        self.active_worktrees: list = []                 # Anmeldeinformationsverwaltung (TR2)
        self._opener = None

    def prepare(self) -> None:
        """Datenordner nur fuer den Benutzer (R13); neue Dateien darin erben das unter Windows."""
        from conclave_board.runtime.file_security import make_private_dirs, restrict
        make_private_dirs(self.data_dir)
        restrict(self.data_dir, directory=True)

    @staticmethod
    def _private_file(path: Path) -> None:
        from conclave_board.runtime.file_security import create_private, restrict
        if not path.exists():
            create_private(path)
            restrict(path)

    # ── Protokoll und Zustand ────────────────────────────────────────────

    def log(self, msg: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.log_file.exists() and self.log_file.stat().st_size > LOG_LIMIT:
            self.log_file.replace(self.log_file.with_suffix(".log.1"))
        self._private_file(self.log_file)
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(line)
        if sys.stdout:
            print(line, end="", flush=True)

    def mark_started(self, dry_run: bool) -> None:
        """Gleich nach dem Sperren (W4-Review V2), auch im Probelauf: PID und Start passen zum Sperrinhaber."""
        self.write_status(pid=os.getpid(), started_at=datetime.now().isoformat(timespec="seconds"),
                          current_task=None, version=_version(), dry_run=dry_run)

    def write_status(self, **updates) -> None:
        """Was ``conclave-reviewer status`` zeigt: PID, Start, laufendes Ticket, letztes Ergebnis."""
        from conclave_board.runtime.file_security import replace_private
        try:
            current = json.loads(self.status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        current.update(updates)
        try:
            replace_private(self.status_file, json.dumps(current, ensure_ascii=False).encode("utf-8"))
        except OSError as e:
            self.log(f"status not written: {e}")

    def load_state(self):
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def save_state(self, state: dict) -> None:
        from conclave_board.runtime.file_security import replace_private
        replace_private(self.state_file, json.dumps(state, indent=1, ensure_ascii=False).encode("utf-8"))

    # ── Board ueber HTTP, nur mit dem Reviewer-Token ──────────────────────

    def token_file(self) -> Path:
        """Die Token-Datei fuer den MCP-Server; bei einem Token aus der Anmeldeinformationsverwaltung eine
        Datei nur fuer das Dienstkonto im Datenordner, die nur waehrend eines Reviews existiert."""
        if self.cfg.get("reviewer_token_credential"):
            return self.mcp_token
        if self.cfg.get("reviewer_token_file"):
            return Path(self.cfg["reviewer_token_file"])
        # Wie conclave.runtime.api_token.reviewer_token_path (ohne dessen Logging-Abhaengigkeit)
        override = os.environ.get("CONCLAVE_REVIEWER_TOKEN_FILE", "").strip()
        if override:
            return Path(override).expanduser()
        from conclave_reviewer.paths import conclave_config_dir
        return conclave_config_dir() / "reviewer.token"

    def token(self) -> str:
        if self.cfg.get("reviewer_token_credential"):
            from conclave_reviewer.credentials import read_generic
            return read_generic(self.cfg["reviewer_token_credential"])
        return self.token_file().read_text(encoding="utf-8").strip()

    def write_mcp_token(self) -> None:
        """Fuer die Dauer eines Reviews: Token aus der Anmeldeinformationsverwaltung als Datei fuer den MCP-Server."""
        if self.cfg.get("reviewer_token_credential"):
            from conclave_board.runtime.file_security import replace_private
            replace_private(self.mcp_token, self.token().encode("utf-8"))

    def drop_mcp_token(self) -> None:
        if self.cfg.get("reviewer_token_credential"):
            self.mcp_token.unlink(missing_ok=True)

    def http(self) -> urllib.request.OpenerDirector:
        """https mit dem CA-Buendel aus der Konfiguration, ohne Proxy und ohne Umleitungen (TR2, R12)."""
        if self._opener is None:
            self._opener = transport.opener(self.cfg.get("ca_bundle"))
        return self._opener

    def get_json(self, url: str):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token()}"})
        with self.http().open(req, timeout=10) as r:  # nosec B310 - URL aus der eigenen Konfiguration
            return json.load(r)

    def post_json(self, url: str, body: dict):
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {self.token()}",
                                              "Content-Type": "application/json"})
        with self.http().open(req, timeout=10) as r:  # nosec B310 - URL aus der eigenen Konfiguration
            return json.load(r)

    def task_url(self, key: str) -> str:
        project, number = key.split("#", 1)
        return f"{self.cfg['conclave_url']}/board/v1/projects/{urllib.parse.quote(project, safe='')}/tasks/{int(number)}"

    def set_review(self, key: str, state: str, comment: str = "", **counts) -> None:
        self.post_json(self.task_url(key) + "/review", {"state": state, "comment": comment, **counts})

    def note(self, key: str, body: str) -> None:
        """Kommentar des Reviewers selbst (Herkunft reviewer), z. B. wenn ein Lauf ohne Ergebnis endete."""
        self.post_json(self.task_url(key) + "/comments", {"body": body, "author_name": self.cfg["author"]})

    def fetch_tasks(self) -> dict:
        """Tickets nach Referenz, mit Projekt, Titel, Status, "nur fuer Menschen" und Review-Status."""
        query = urllib.parse.urlencode({"status": self.cfg["review_status"]})
        data = self.get_json(f"{self.cfg['conclave_url']}/board/v1/tasks?{query}")
        return {t["ref"]: {"project": t["project"], "title": t["title"], "status": t["status"],
                           "human": t["human"], "review_state": (t.get("review") or {}).get("state", "none")}
                for t in data["tasks"]}

    # ── Ein Review ────────────────────────────────────────────────────────

    claude_proc = None                                # der laufende claude (W4-Review B1)

    def run_claude(self, key: str, cmd: list[str], cwd: str) -> str:
        try:
            return command.run_claude(cmd, cwd, self.cfg["review_timeout_minutes"], self.log, key,
                                      on_start=lambda proc: setattr(self, "claude_proc", proc))
        finally:
            self.claude_proc = None

    def drop_worktrees(self) -> None:
        """Worktrees des laufenden Reviews entfernen, innere zuerst (auch beim Ende mitten im Review)."""
        added, self.active_worktrees = self.active_worktrees, []
        for r, path in reversed(added):
            worktrees.remove_worktree(r, path)

    def clean_orphans(self) -> None:
        """Beim Start, mit gehaltener Sperre: Worktrees und die Token-Datei fuer den MCP-Server, die ein
        abgebrochener Lauf liegen liess (#98-Review V3, TR2-Review V3). Erst nach der Sperre: Ein zweiter
        Start, der an ihr scheitert, loescht nichts, was ein laufendes Review noch braucht."""
        self.drop_mcp_token()
        repos = dict.fromkeys(r for project in (self.cfg.get("projects") or {})
                              for r in refs.repos_for(self.cfg, project))
        removed = worktrees.remove_orphans(self.worktrees, list(repos))
        if removed:
            self.log(f"removed leftover worktrees: {', '.join(removed)}")

    def stop_claude(self) -> None:
        """Beim Ende mit dem Desktop: den laufenden claude samt Kindprozessen beenden."""
        command.kill_claude(self.claude_proc)

    def command_for(self, task: dict, key: str, checked: str, extra, missing) -> list[str]:
        return command.review_command(self.cfg, task, key, mcp_config=self.mcp_config,
                                      prompt_text=(command.fill_prompt(self.cfg, self.prompt) if self.prompt is not None
                                                   else command.prompt(self.cfg, self.base_dir)), checked=checked,
                                      extra=extra, missing=missing)

    def run_review(self, task: dict, key: str, repo: str | list[str], dry_run: bool) -> None:
        """running -> Worktrees der genannten Commits -> der Reviewer setzt das Ergebnis.

        Ohne Ergebnis bleibt der Status ``running`` und ein Kommentar sagt warum. ``failed`` zu setzen
        zaehlte als rotes Review gegen den Umsetzer (drei in Folge gehen an den Menschen) und schickte
        das Ticket in eine Nacharbeit, die niemand verlangt hat.
        """
        repos = [repo] if isinstance(repo, str) else list(repo)
        detail = self.get_json(self.task_url(key))
        hashes, branches = refs.named_refs(detail, self.cfg["author"])
        if self.cfg.get("fetch") and (hashes or branches):
            for r in repos:                             # Team-Server: nur der Stand im Git-Server zaehlt (TR2)
                refs.fetch(r)
        if hashes and self.cfg.get("missing_commits") == "red":
            # Rot nur, wenn keiner der genannten Commits da ist oder ein zu pruefender (`branch` @ `hash`)
            # fehlt; ein nur erwaehnter alter Commit geht wie bisher als Hinweis an claude (Review V1).
            known = {h: any(refs.exists(r, h) for r in repos) for h in dict.fromkeys(hashes)}
            pinned = refs.pinned_commits(detail, self.cfg["author"])
            absent = list(known) if not any(known.values()) else [h for h in pinned if not known.get(h, True)]
            if absent:
                self.log(f"{key}: commits not on the git server: {', '.join(absent)}; red without claude")
                if not dry_run:
                    self.set_review(key, "failed", MISSING_ON_SERVER.format(
                        hashes=", ".join(f"`{h}`" for h in absent)), blocking=1, suggestions=0)
                return
        found = []                                      # (Repo, Commit, Branch)
        for r in repos:
            state = refs.find_state(r, hashes, branches, bool(self.cfg.get("fetch"))) if (hashes or branches) else None
            if state:
                found.append((r, *state))
        if not found:
            self.log(f"{key}: no commit named in the ticket, not reviewed")
            if not dry_run:
                self.note(key, "Kein Review gestartet: Im Ticket ist kein Commit genannt (z. B. `abc1234` im "
                               "Kommentar mit Branch, Commits und Tests). Bitte nachtragen und erneut nach review "
                               "schieben.")
            return
        missing = [h for h in dict.fromkeys(hashes) if not any(refs.exists(r, h) for r in repos)]
        if len(repos) == 1:
            checked = f"{found[0][2] or 'detached'} @ {found[0][1][:7]}"
        else:
            checked = " · ".join(f"{refs.repo_name(r)}: {b or 'detached'} @ {c[:7]}" for r, c, b in found)
        if dry_run:
            self.log(f"{key}: dry run, would review {checked} from {', '.join(r for r, _c, _b in found)}")
            self._log_planned(task, key, found, checked, missing)
            return
        self.set_review(key, "running")
        first_repo, first_commit, _ = found[0]
        worktree = worktrees.add_worktree(self.worktrees, first_repo, key, first_commit)
        added = [(first_repo, worktree)]
        self.active_worktrees = added
        try:
            extra = []
            for index, (r, commit, _b) in enumerate(found[1:], start=1):
                added.append((r, worktrees.add_worktree(self.worktrees, r, key, commit, inside=worktree)))
                extra.append((refs.repo_name(r), f"_repos/{refs.repo_name(r)}", refs.git_server(index, r)))
            from conclave_board.runtime.file_security import replace_private
            servers = command.mcp_servers(self.cfg, [str(p) for _r, p in added], self.token_file())
            replace_private(self.mcp_config, json.dumps(servers).encode("utf-8"))
            self.write_mcp_token()
            self.log(f"{key}: review started ({checked}) in {worktree}")
            self.current_task = key
            self.write_status(current_task=key)
            outcome = "failed"
            outcome = self.run_claude(key, self.command_for(task, key, checked, extra, missing), str(worktree))
        finally:
            if self.current_task is not None:           # auch wenn claude gar nicht startete (W4-Review V1)
                self.write_status(current_task=None, last_result={
                    "task": key, "outcome": outcome, "at": datetime.now().isoformat(timespec="seconds")})
            self.current_task = None
            self.drop_mcp_token()
            self.drop_worktrees()
        after = self.get_json(self.task_url(key))
        if after.get("status") == self.cfg["review_status"] and (after.get("review") or {}).get("state") == "running":
            reason = {"timeout": f"nach {self.cfg['review_timeout_minutes']} Minuten abgebrochen",
                      "failed": "mit einem Fehler beendet"}.get(outcome, "ohne Ergebnis beendet")
            self.note(key, f"Review {reason}. Der Status bleibt „läuft“; das Ergebnis zählt nicht als rot. "
                           "Neu prüfen: den Reviewer neu starten (er gibt hängende Reviews frei und prüft sie "
                           "neu) oder das Ticket aus review und wieder hinein schieben.")
            self.log(f"{key}: review {outcome} without a result, state left at running")

    def _log_planned(self, task: dict, key: str, found, checked: str, missing) -> None:
        """Probelauf: der Aufruf und die MCP-Konfiguration, wie sie ein echter Lauf naehme (nichts angelegt)."""
        first = worktrees.worktree_path(self.worktrees, found[0][0], key)
        paths = [str(first)] + [str(worktrees.worktree_path(self.worktrees, r, key, inside=first))
                                for r, _c, _b in found[1:]]
        extra = [(refs.repo_name(r), f"_repos/{refs.repo_name(r)}", refs.git_server(i, r))
                 for i, (r, _c, _b) in enumerate(found[1:], start=1)]
        cmd = self.command_for(task, key, checked, extra, missing)
        shown = [("<Prompt, " + str(len(a)) + " Zeichen>") if i and cmd[i - 1] == "--append-system-prompt" else a
                 for i, a in enumerate(cmd)]
        self.log(f"{key}: dry run, command (cwd {first}): {json.dumps(shown, ensure_ascii=False)}")
        self.log(f"{key}: dry run, mcp config: "
                 f"{json.dumps(command.mcp_servers(self.cfg, paths, self.token_file()), ensure_ascii=False)}")

    # ── Die Schleife ──────────────────────────────────────────────────────

    def check(self, state: dict | None, tasks: dict, dry_run: bool) -> dict:
        """Neu nach review geschobene Tickets pruefen. Ein Probelauf schreibt keinen Zustand: Er soll den
        naechsten echten Lauf nicht beeinflussen (gesehene Tickets, Zaehler je Stunde)."""
        save = (lambda _s: None) if dry_run else self.save_state
        statuses = {k: t["status"] for k, t in tasks.items()}
        if state is None and dry_run:
            # Probelauf ohne gemerkten Stand: alles in review zeigen, als waere es neu (es wird nichts gespeichert)
            self.log(f"dry run without saved state: showing all {len(statuses)} tickets in review")
            state = {"statuses": {}, "pending": [], "reviews": []}
        if state is None:
            # Erster Lauf: das Board merken; Tickets, die schon in review stehen, werden nicht geprueft.
            already = [k for k, s in statuses.items() if s == self.cfg["review_status"]]
            self.log(f"first run: {len(statuses)} tickets, already in review (skipped): {already or 'none'}")
            return {"statuses": statuses, "pending": [], "reviews": []}

        pending = [k for k in state["pending"] if k in tasks and statuses[k] == self.cfg["review_status"]]
        for k, s in statuses.items():
            if s == self.cfg["review_status"] and state["statuses"].get(k) != s and k not in pending:
                self.log(f"{k}: moved to {s}")
                pending.append(k)
        state = {"statuses": statuses, "pending": pending, "reviews": state["reviews"]}
        # Vor dem Review speichern: Ein Absturz mitten im Review verliert es, statt es doppelt zu bezahlen.
        save(state)

        while state["pending"]:
            key = state["pending"][0]
            task = tasks[key]
            hour_ago = time.time() - 3600
            state["reviews"] = [t for t in state["reviews"] if t > hour_ago]
            if len(state["reviews"]) >= self.cfg["max_reviews_per_hour"]:
                self.log(f"limit of {self.cfg['max_reviews_per_hour']} reviews per hour reached; "
                         f"{len(state['pending'])} waiting")
                break
            state["pending"].pop(0)
            repos = [r for r in refs.repos_for(self.cfg, task["project"]) if Path(r).is_dir()]
            if task.get("human"):
                self.log(f"{key}: for humans only, not reviewed")
            elif task.get("review_state", "none") != "none":
                self.log(f"{key}: review state is {task['review_state']!r}, not reviewed again")
            elif not repos:
                self.log(f"{key}: no local checkout for project {task['project']!r} in config.toml, not reviewed")
            else:
                state["reviews"].append(time.time())
                save(state)
                try:
                    self.run_review(task, key, repos if len(repos) > 1 else repos[0], dry_run)
                except (urllib.error.URLError, OSError, ValueError, KeyError, RuntimeError) as e:
                    self.log(f"{key}: review not run: {e}")
            save(state)
        return state

    def changed(self, state: dict | None, tasks: dict) -> bool:
        if state is None or state["pending"]:
            return True
        return {k: t["status"] for k, t in tasks.items()} != state["statuses"]

    # ── Aenderungszaehler, Herzschlag, haengende Reviews (W3) ─────────────

    def changes(self):
        return self.get_json(f"{self.cfg['conclave_url']}/board/v1/changes")["changes"]

    def send_heartbeat(self) -> None:
        try:
            self.post_json(f"{self.cfg['conclave_url']}/board/v1/reviewer/heartbeat",
                           {"version": _version(), "task": self.current_task})
        except (urllib.error.URLError, OSError, ValueError) as e:
            if self._heartbeat_ok:
                self.log(f"heartbeat not sent: {e}")
            self._heartbeat_ok = False
            return
        self._heartbeat_ok = True

    def start_heartbeat(self) -> threading.Event:
        """Herzschlag in einem eigenen Thread, auch waehrend ein Review laeuft (claude blockiert die Schleife)."""
        stop = threading.Event()
        every = float(self.cfg.get("heartbeat_seconds", 60))

        def beat():
            while not stop.wait(every):
                self.send_heartbeat()

        threading.Thread(target=beat, name="reviewer-heartbeat", daemon=True).start()
        return stop

    def recover_hanging(self, dry_run: bool) -> list[str]:
        """Beim Start: ``running`` ohne Lauf (dieser Reviewer laeuft ja erst jetzt; die Sperre schliesst einen
        zweiten aus) kommentieren und auf ``none`` zuruecksetzen; diese Tickets werden neu geprueft."""
        hanging = [k for k, t in self.fetch_tasks().items()
                   if t["status"] == self.cfg["review_status"] and t.get("review_state") == "running"]
        for key in hanging:
            if dry_run:
                self.log(f"{key}: dry run, would release the hanging review")
                continue
            self.set_review(key, "none", "Review hing (Status „läuft“ ohne laufenden Reviewer, z. B. nach einem "
                                         "Absturz oder Neustart). Es wird jetzt neu geprüft.")
            self.log(f"{key}: hanging review released, reviewing again")
        return [] if dry_run else hanging

    def poll_once(self, state, dry_run: bool):
        if state is not None and not state["pending"]:
            current = self.changes()
            if current == self._last_changes:
                return state                           # nichts geaendert: die Spalte nicht lesen
            self._last_changes = current
        else:
            self._last_changes = self.changes()
        tasks = self.fetch_tasks()                     # nur die Spalte review; mit dem letzten Stand vergleichen
        if self.changed(state, tasks):
            state = self.check(state, tasks, dry_run)
            if not dry_run:
                self.save_state(state)
        return state

    def loop(self, dry_run: bool = False, once: bool = False) -> None:
        self.log(f"watching {BOARDS['conclave']['name']} {self.cfg['conclave_url']} for tickets moved to "
                 f"{self.cfg['review_status']!r}" + (" (dry run)" if dry_run else ""))
        state, reachable = self.load_state(), True
        self.send_heartbeat()
        stop = None if once else self.start_heartbeat()
        try:
            recovered = self.recover_hanging(dry_run)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            self.log(f"hanging reviews not checked: {e}")
            recovered = []
        if recovered:
            if state is None:                          # erster Lauf: das Board merken, die freigegebenen trotzdem pruefen
                state = self.check(None, self.fetch_tasks(), dry_run)
            state["pending"] = list(dict.fromkeys([*state["pending"], *recovered]))
            self.save_state(state)
        try:
            self._loop(state, reachable, dry_run, once)
        finally:
            if stop is not None:
                stop.set()

    def _loop(self, state, reachable: bool, dry_run: bool, once: bool) -> None:
        while True:
            try:
                state = self.poll_once(state, dry_run)
                if not reachable:
                    self.log("board reachable again")
                    reachable = True
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                if reachable:
                    self.log(f"board not reachable: {e}")
                    reachable = False
            if once:
                return
            time.sleep(self.cfg["poll_seconds"])


# Eigenes Wheel (Team-Server) zuerst, dann Personal, das den Reviewer buendelt (TR1); gleiche Version
VERSION_SOURCES = ("conclave-reviewer", "conclave-personal")


def _version() -> str:
    from importlib.metadata import version
    for name in VERSION_SOURCES:
        try:
            return version(name)
        except Exception:  # noqa: BLE001, S112 - nicht installiert: naechste Quelle
            continue
    return "dev"                                              # Quellbaum ohne Installation


def legacy_locks(cfg: dict, config_path: Path) -> tuple[Path, ...]:
    """Sperrdatei(en) des alten Watchers: neben seiner config.toml und, falls gesetzt, ``legacy_lock_file``."""
    paths = [config_path.parent / "watcher.lock"]
    if cfg.get("legacy_lock_file"):
        paths.append(Path(cfg["legacy_lock_file"]))
    return tuple(dict.fromkeys(paths))


def default_data_dir(config_path: Path | None = None) -> Path:
    """Eigener Datenordner (``<Konfigurationsordner von Conclave>/reviewer``), nie der des alten Watchers:
    dessen Log, Zustand und Worktrees bleiben unberuehrt (bis W5 ist er massgeblich)."""
    from conclave_reviewer.config import data_dir
    return data_dir()
