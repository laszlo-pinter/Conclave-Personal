"""Hoechstens ein Reviewer je Datenordner (Entscheidung Laszlo: Sperre des Betriebssystems).

Gesperrt wird ein Byte der Sperrdatei (Windows ``msvcrt.locking``, sonst ``fcntl.flock``). Die
Sperre gehoert dem Prozess und faellt mit ihm weg, auch nach einem Absturz; eine verwaiste
Sperrdatei sperrt also nie. Laeuft noch der alte Watcher, haelt er seine ``watcher.lock`` auf
dieselbe Weise; sie gilt deshalb ebenfalls als belegt und wird fuer die Laufzeit mitgesperrt
(dann startet auch der alte Watcher nicht neben dem neuen).
"""

from __future__ import annotations

import os
from pathlib import Path


class AlreadyRunning(RuntimeError):
    """Ein anderer Reviewer (oder der alte Watcher) laeuft schon."""


def _lock(handle) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


class ProcessLock:
    def __init__(self, path: Path, legacy: tuple[Path, ...] = ()) -> None:
        self.path = path
        self.legacy = tuple(p for p in legacy if p != path)
        self._handles = []

    def acquire(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for path, what in ((self.path, "conclave-reviewer"), *((p, "der alte Watcher") for p in self.legacy)):
            if what != "conclave-reviewer" and not path.exists():
                continue
            handle = path.open("a+")                    # nie kuerzen: die Datei gehoert evtl. dem anderen
            if not _lock(handle):
                handle.close()
                self.release()
                raise AlreadyRunning(f"{what} laeuft schon ({path}).")
            self._handles.append(handle)
        return self

    def release(self) -> None:
        for handle in reversed(self._handles):
            _unlock(handle)
            handle.close()
        self._handles.clear()

    def __enter__(self) -> "ProcessLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()
