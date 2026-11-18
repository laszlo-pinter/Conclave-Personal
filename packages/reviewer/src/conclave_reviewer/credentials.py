"""Reviewer-Token aus der Windows-Anmeldeinformationsverwaltung (TR2).

``reviewer_token_credential = "<Zielname>"`` in ``[reviewer]``: Das Token liegt als generische
Anmeldeinformation des Dienstkontos (Zielname wie angegeben, Kennwort = Token), etwa angelegt mit

    cmdkey /generic:ConclaveReviewer /user:reviewer /pass

unter dem Dienstkonto. Es steht so weder in der Konfiguration noch in der Kommandozeile des
Reviewers. Nur unter Windows; sonst gilt ``reviewer_token_file`` (Datei nur fuer das Dienstkonto).
"""

from __future__ import annotations

import sys


class CredentialError(OSError):
    """Anmeldeinformation fehlt oder ist unbrauchbar."""


def read_generic(target: str) -> str:
    """Kennwort der generischen Anmeldeinformation ``target`` (ohne Leerraum am Rand)."""
    if not sys.platform.startswith("win"):
        raise CredentialError("reviewer_token_credential gibt es nur unter Windows; reviewer_token_file nutzen.")
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    advapi.CredReadW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.POINTER(CREDENTIAL)()
    if not advapi.CredReadW(target, 1, 0, ctypes.byref(pointer)):          # 1 = CRED_TYPE_GENERIC
        raise CredentialError(f"Anmeldeinformation {target!r} nicht gefunden (Fehler {ctypes.get_last_error()}); "
                              "unter dem Dienstkonto anlegen, siehe Anleitung.")
    try:
        cred = pointer.contents
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
    finally:
        advapi.CredFree(pointer)
    # cmdkey und die Systemsteuerung speichern UTF-16, andere Werkzeuge oft UTF-8
    try:
        token = raw.decode("utf-16-le") if len(raw) % 2 == 0 and b"\x00" in raw else raw.decode("utf-8")
    except UnicodeDecodeError:
        raise CredentialError(f"Anmeldeinformation {target!r}: Kennwort ist kein Text.") from None
    token = token.strip()
    if not token:
        raise CredentialError(f"Anmeldeinformation {target!r}: Kennwort ist leer.")
    return token
