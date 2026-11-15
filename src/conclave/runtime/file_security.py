"""Dateirechte fuer Schluessel, Tokens und Daten (R13).

- ``create_exclusive``: legt eine Datei nur an, wenn es sie noch nicht gibt, und
  zwar vollstaendig und nur fuer den Benutzer lesbar (auch bei gleichzeitigem Start).
- ``restrict``: nur der Benutzer hat Zugriff. POSIX: 0o600 bzw. 0o700. Windows:
  geschuetzte DACL mit genau einem Eintrag fuer den Benutzer (keine Vererbung,
  keine weiteren ausdruecklichen Rechte).
- ``foreign_access``: wer ausser dem Benutzer Zugriff hat.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import stat
from pathlib import Path

logger = logging.getLogger("conclave.runtime.file_security")


def restrict(path: Path, *, directory: bool = False) -> None:
    """Nur der aktuelle Benutzer hat Zugriff auf ``path``."""
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    sid = _user_sid()
    inherit = "OICI" if directory else ""
    _set_dacl(path, f"D:PAI(A;{inherit};FA;;;{sid})")


def foreign_access(path: Path) -> list[str]:
    """Wer ausser dem Benutzer Zugriff hat (SIDs bzw. "group"/"other"); leer = nur der Benutzer."""
    if os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode)
        return [name for name, bits in (("group", 0o070), ("other", 0o007)) if mode & bits]
    sddl = _dacl_sddl(path)
    if "NO_ACCESS_CONTROL" in sddl:
        return ["WD"]
    sid = _user_sid()
    foreign = []
    for ace in re.findall(r"\(([^)]*)\)", sddl):
        fields = ace.split(";")
        if len(fields) >= 6 and fields[0] in ("A", "OA") and fields[5] != sid and fields[5] not in foreign:
            foreign.append(fields[5])
    return foreign


def harden(path: Path, *, directory: bool = False) -> bool:
    """Entfernt fremde Rechte an einer vorhandenen Datei; True, wenn etwas geaendert wurde."""
    try:
        foreign = foreign_access(path)
        if not foreign:
            return False
        restrict(path, directory=directory)
    except OSError as exc:
        logger.warning("Rechte an %s nicht geprueft: %s", path, exc)
        return False
    logger.warning("Fremde Rechte an %s entfernt (%s)", path, ", ".join(foreign))
    return True


def create_exclusive(path: Path, data: bytes) -> bool:
    """Legt ``path`` mit ``data`` an, wenn es die Datei noch nicht gibt; True = selbst angelegt.

    Geschrieben wird in eine eigene Temp-Datei (Rechte schon gesetzt), die per
    Hardlink unter dem Zielnamen erscheint: Leser sehen nie eine halbe Datei, und
    bei gleichzeitigem Anlegen gewinnt genau einer.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        restrict(tmp)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        except OSError:
            return _create_in_place(path, data)        # Dateisystem ohne Hardlinks
        return True
    finally:
        tmp.unlink(missing_ok=True)


def _create_in_place(path: Path, data: bytes) -> bool:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    restrict(path)
    return True


def secure_runtime_dirs(paths) -> None:
    """Beim Start: Konfigurationsverzeichnis nur fuer den Benutzer; POSIX auch Daten und Logs.

    Das Konfigurationsverzeichnis wird nur angefasst, wenn secret.key darin liegt
    (umgelenkte Pfade sperren keine fremden Ordner).
    """
    config_dir = Path(paths.config_dir)
    if Path(paths.secret_key_path).parent == config_dir and config_dir.is_dir():
        harden(config_dir, directory=True)
    if os.name != "nt":
        for folder in (Path(paths.data_dir), Path(paths.log_dir)):
            if folder.is_dir() and folder.stat().st_uid == os.getuid():
                harden(folder, directory=True)


# ── Windows: DACL ueber advapi32 (unabhaengig von Sprache und icacls-Ausgabe) ──

_DACL_INFORMATION = 0x00000004
_PROTECTED_DACL_INFORMATION = 0x80000000
_SE_FILE_OBJECT = 1
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_SDDL_REVISION = 1


def _api():
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    vp, pvp = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = [vp]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, vp, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    advapi32.ConvertSidToStringSidW.argtypes = [vp, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, pvp, ctypes.POINTER(wintypes.ULONG)]
    advapi32.GetSecurityDescriptorDacl.argtypes = [vp, ctypes.POINTER(wintypes.BOOL), pvp,
                                                   ctypes.POINTER(wintypes.BOOL)]
    advapi32.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, vp, vp, vp, vp]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
                                               pvp, pvp, pvp, pvp, pvp]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        vp, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG)]
    return ctypes, wintypes, advapi32, kernel32


def _user_sid() -> str:
    ctypes, wintypes, advapi32, kernel32 = _api()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, _TOKEN_USER, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]     # TOKEN_USER.User.Sid
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel32.CloseHandle(token)


def _set_dacl(path: Path, sddl: str) -> None:
    ctypes, wintypes, advapi32, kernel32 = _api()
    descriptor = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, _SDDL_REVISION, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl),
                                                  ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        error = advapi32.SetNamedSecurityInfoW(str(path), _SE_FILE_OBJECT,
                                               _DACL_INFORMATION | _PROTECTED_DACL_INFORMATION,
                                               None, None, dacl, None)
        if error:
            raise ctypes.WinError(error)
    finally:
        kernel32.LocalFree(descriptor)


def _dacl_sddl(path: Path) -> str:
    ctypes, wintypes, advapi32, kernel32 = _api()
    descriptor = ctypes.c_void_p()
    error = advapi32.GetNamedSecurityInfoW(str(path), _SE_FILE_OBJECT, _DACL_INFORMATION,
                                           None, None, None, None, ctypes.byref(descriptor))
    if error:
        raise ctypes.WinError(error)
    try:
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, _SDDL_REVISION, _DACL_INFORMATION, ctypes.byref(text), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel32.LocalFree(descriptor)
