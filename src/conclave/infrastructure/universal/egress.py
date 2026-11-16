# src/conclave/infrastructure/universal/egress.py
"""Ausgehende Verbindungen zu Providern.

Der Name des Ziels wird bei jeder Anfrage aufgeloest. Erlaubt sind nur
oeffentliche Adressen; verbunden wird mit genau der geprueften Adresse
(Host-Header und SNI bleiben beim Namen). Im Zweifel wird blockiert.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable

import httpx

from conclave.domain.errors import ProviderTargetBlocked
from conclave.infrastructure.log import get_logger

logger = get_logger("infrastructure.egress")

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def address_blocked(value: str) -> bool:
    """True fuer alles ausser oeffentlichen Unicast-Adressen (eingebettete IPv4 ausgepackt)."""
    ip = ipaddress.ip_address(value.split("%", 1)[0])
    if ip.version == 6:
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip.sixtofour:
            ip = ip.sixtofour
        elif ip.teredo:
            ip = ip.teredo[1]
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return not ip.is_global or ip.is_multicast


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return True


class GuardedTransport(httpx.BaseTransport):
    """httpx-Transport, der jedes Ziel vor dem Verbinden prueft.

    Args:
        provider: Name fuer Fehlermeldungen
        local_port: Lokaler Provider (Ollama) - nur dieser Port auf localhost
        inner: eigentlicher Transport (Default: httpx.HTTPTransport)
        resolve: Namensaufloesung (Default: socket.getaddrinfo)
    """

    def __init__(self, provider: str, *, local_port: int | None = None,
                 inner: httpx.BaseTransport | None = None, resolve: Callable | None = None) -> None:
        self._provider = provider
        self._local_port = local_port
        self._inner = inner or httpx.HTTPTransport()
        self._resolve = resolve

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        if self._local_port is not None and host in LOCAL_HOSTS and port == self._local_port:
            return self._inner.handle_request(request)
        address = self._checked_address(host, port)
        if address != host:
            request.url = request.url.copy_with(host=address)
            request.extensions = {**request.extensions, "sni_hostname": host}
        return self._inner.handle_request(request)

    def _checked_address(self, host: str, port: int) -> str:
        if _is_ip(host):
            addresses = [host]
        else:
            resolve = self._resolve or socket.getaddrinfo
            try:
                addresses = [info[4][0] for info in resolve(host, port, type=socket.SOCK_STREAM)]
            except (OSError, UnicodeError):
                logger.warning("Provider-Ziel nicht aufloesbar", extra={"provider": self._provider})
                raise ProviderTargetBlocked(self._provider, "Name nicht aufloesbar") from None
        try:
            blocked = not addresses or any(address_blocked(a) for a in addresses)
        except ValueError:
            blocked = True
        if blocked:
            logger.warning("Provider-Ziel blockiert: keine oeffentliche Adresse",
                           extra={"provider": self._provider})
            raise ProviderTargetBlocked(self._provider, "keine oeffentliche Adresse")
        return addresses[0]

    def close(self) -> None:
        self._inner.close()
