# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Gemeinsame Schutzregeln der HTTP-API: Host-Allowlist, Groessen, Token aus der Anfrage.

Board-App und Personal nutzen dieselben Regeln (T1).
"""

BOARD_IMPORT_MAX_BYTES = 50 * 1024 * 1024    # Groesse des JSON-Exports, vor dem Parsen geprueft
MAX_REQUEST_BYTES = 10 * 1024 * 1024         # alle anderen Anfragen (R6); der Import hat seine eigene Grenze

CLIENT_HEADER = "X-Conclave-Client"

# Host-Allowlist gegen DNS-Rebinding (B2). Loopback-Namen sind immer erlaubt; weitere Hosts
# ergaenzt die App (Personal: CONCLAVE_ALLOWED_HOSTS, Board-Server: CONCLAVE_BOARD_ALLOWED_HOSTS).
# Eintraege ohne Port gelten fuer jeden Port.
DEFAULT_ALLOWED_HOSTS = "localhost,127.0.0.1,[::1]"


def _split_host(value: str) -> tuple[str, str]:
    """'Host'-Wert in (hostname, port) zerlegen; IPv6 in eckigen Klammern oder nackt."""
    value = value.strip().lower()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        if rest and not rest.startswith(":"):
            return value, ""  # fehlerhaft, z. B. "[::1].evil" - passt auf keinen Eintrag
        return host, rest[1:]
    if value.count(":") == 1:
        host, port = value.split(":")
        return host, port
    return value, ""


def parse_allowed_hosts(raw: str) -> set[tuple[str, str]]:
    entries = f"{DEFAULT_ALLOWED_HOSTS},{raw or ''}".split(",")
    return {_split_host(entry) for entry in entries if entry.strip()}


def is_host_allowed(host_header: str, allowed: set[tuple[str, str]]) -> bool:
    host, port = _split_host(host_header or "")
    return bool(host) and ((host, "") in allowed or (host, port) in allowed)


def request_token(headers) -> str | None:
    """Token aus ``Authorization: Bearer`` oder ``X-API-Key``."""
    auth_header = headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return headers.get("X-API-Key")


# ── Netzbetrieb hinter einem Proxy (T7) ─────────────────────────────────

def parse_networks(raw: str) -> tuple:
    """``"10.0.0.5, 10.1.0.0/16"`` -> Netze; leer = keiner. Ungueltige Eintraege sind ein Fehler."""
    import ipaddress
    networks = []
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if entry:
            try:
                networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                raise ValueError(f"Kein gueltiger Proxy-Eintrag: {entry!r} (IP-Adresse oder Netz wie 10.0.0.0/24).") from None
    return tuple(networks)


def _in_networks(address: str, networks) -> bool:
    import ipaddress
    try:
        ip = ipaddress.ip_address(address.strip().strip("[]"))
    except ValueError:
        return False
    return any(ip in net for net in networks)


def _is_loopback(address: str) -> bool:
    import ipaddress
    try:
        return ipaddress.ip_address(address.strip().strip("[]")).is_loopback
    except ValueError:
        return False


FORWARDED_HEADERS = ("HTTP_X_FORWARDED_FOR", "HTTP_X_FORWARDED_PROTO", "HTTP_X_FORWARDED_HOST",
                     "HTTP_X_FORWARDED_PORT", "HTTP_X_FORWARDED_PREFIX", "HTTP_FORWARDED", "HTTP_X_REAL_IP")


class TrustedProxyMiddleware:
    """``X-Forwarded-For`` und ``-Proto`` gelten nur, wenn die Verbindung von einem konfigurierten Proxy kommt.

    Dann ist die Client-Adresse der rechteste Eintrag in ``X-Forwarded-For``, der kein Proxy ist,
    und ``X-Forwarded-Proto`` (letzter Wert) das Schema. Von jeder anderen Quelle werden alle
    Forwarded-Header entfernt, bevor die App sie sehen kann.
    """

    def __init__(self, app, networks, *, proxy_only: bool = False) -> None:
        self.app = app
        self.networks = tuple(networks)
        self.proxy_only = proxy_only

    def __call__(self, environ, start_response):
        peer = environ.get("REMOTE_ADDR", "")
        from_proxy = bool(self.networks) and _in_networks(peer, self.networks)
        if self.proxy_only and not from_proxy and not _is_loopback(peer):
            body = b'{"error": "Nur ueber den TLS-Proxy erreichbar.", "type": "ProxyRequired"}'
            start_response("403 Forbidden", [("Content-Type", "application/json"),
                                             ("Content-Length", str(len(body)))])
            return [body]
        if from_proxy:
            hops = [h.strip() for h in environ.get("HTTP_X_FORWARDED_FOR", "").split(",") if h.strip()]
            for hop in reversed(hops):
                if not _in_networks(hop, self.networks):
                    environ["REMOTE_ADDR"] = hop
                    break
            proto = environ.get("HTTP_X_FORWARDED_PROTO", "").split(",")[-1].strip().lower()
            if proto in ("http", "https"):
                environ["wsgi.url_scheme"] = proto
        for name in FORWARDED_HEADERS:
            environ.pop(name, None)                           # die App liest sie nie selbst
        return self.app(environ, start_response)


# ── Zaehler je Zeitfenster (T7: Fehlversuche je IP, Anfragen je Konto) ────

_PERIODS = {"second": 1, "minute": 60, "hour": 3600}


def parse_limit(value: str) -> tuple[int, int] | None:
    """``"10 per minute"`` -> (10, 60); leer, ``off``, ``none`` oder ``0`` -> ``None`` (aus)."""
    value = (value or "").strip().lower()
    if value in ("", "off", "none", "0"):
        return None
    parts = value.replace("/", " per ").split()
    if len(parts) != 3 or parts[1] != "per" or not parts[0].isdigit() or parts[2].rstrip("s") not in _PERIODS:
        raise ValueError(f"Limit wie '10 per minute' erwartet, nicht {value!r}.")
    return int(parts[0]), _PERIODS[parts[2].rstrip("s")]


class WindowCounter:
    """Feste Zeitfenster je Schluessel, im Speicher, threadsicher. ``hit`` zaehlt und sagt, ob das
    Limit ueberschritten ist; ``over`` prueft nur. Der Speicher bleibt begrenzt."""

    MAX_KEYS = 100_000

    def __init__(self, limit: tuple[int, int], clock=None) -> None:
        import threading
        import time
        self.count, self.period = limit
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}

    def _window(self) -> int:
        return int(self._clock() // self.period)

    def over(self, key: str) -> bool:
        with self._lock:
            window, n = self._windows.get(key, (-1, 0))
            return window == self._window() and n >= self.count

    def hit(self, key: str) -> bool:
        with self._lock:
            now = self._window()
            window, n = self._windows.get(key, (now, 0))
            n = n + 1 if window == now else 1
            if key not in self._windows and len(self._windows) >= self.MAX_KEYS:
                self._evict(now)
            self._windows[key] = (now, n)
            return n > self.count

    def _evict(self, now: int) -> None:
        """Speicher hart begrenzt: alte Fenster weg; reicht das nicht, das aelteste Zehntel (Einfuegereihenfolge)."""
        stale = [k for k, (window, _n) in self._windows.items() if window != now]
        for k in stale:
            del self._windows[k]
        if len(self._windows) >= self.MAX_KEYS:
            for k in list(self._windows)[: max(1, self.MAX_KEYS // 10)]:
                del self._windows[k]

    def retry_after(self) -> int:
        return int(self.period - (self._clock() % self.period)) + 1
