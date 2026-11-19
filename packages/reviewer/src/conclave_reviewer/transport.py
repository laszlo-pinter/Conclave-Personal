"""HTTP zum Board: https mit eigenem CA-Buendel, ohne Proxy und ohne Umleitungen (TR2, R12).

- ``ca_bundle`` (Pfad zu einer PEM-Datei) ersetzt die Zertifikate des Systems ganz: Es gilt nur die
  eigene CA, ``SSL_CERT_FILE`` und ``SSL_CERT_DIR`` wirken nicht. Ohne Angabe (nur in Personal
  moeglich, am entfernten Server Pflicht) gilt der Zertifikatsspeicher des Systems.
- Proxy-Umgebungsvariablen (``HTTPS_PROXY`` usw.) gelten nicht, Umleitungen werden nicht verfolgt:
  Das Reviewer-Token geht nur an den eingetragenen Server.
- http nur fuer einen Server auf diesem Rechner (127.0.0.1, ::1, localhost), sonst https.
"""

from __future__ import annotations

import ssl
import urllib.parse
import urllib.request

LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")


class TransportError(ValueError):
    """Server-Adresse oder CA-Buendel unbrauchbar; die Meldung nennt, was fehlt."""


def check_url(url: str) -> str:
    """Die Server-Adresse ohne Schraegstrich am Ende; http nur lokal."""
    parts = urllib.parse.urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise TransportError(f"Server-Adresse {url!r}: http(s)://host[:port] erwartet.")
    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        raise TransportError(f"Server-Adresse {url!r}: ausser fuer diesen Rechner nur https.")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise TransportError(f"Server-Adresse {url!r}: ohne Anmeldedaten, Abfrage oder Fragment.")
    return url.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):           # Token nie an ein anderes Ziel mitnehmen
        return None


def ssl_context(ca_bundle: str | None) -> ssl.SSLContext:
    """Mit ``ca_bundle`` nur diese CA (``SSL_CERT_FILE`` und Systemspeicher gelten dann nicht)."""
    try:
        return ssl.create_default_context(cafile=ca_bundle or None)
    except (OSError, ssl.SSLError) as e:
        raise TransportError(f"CA-Buendel {ca_bundle} nicht lesbar ({e.__class__.__name__}).") from None


def opener(ca_bundle: str | None) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(),
                                       urllib.request.HTTPSHandler(context=ssl_context(ca_bundle)))
