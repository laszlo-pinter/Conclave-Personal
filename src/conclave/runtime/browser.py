import webbrowser
from urllib.parse import quote, urlsplit

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def server_url(host: str, port: int) -> str:
    # Vergleich, keine Bindung: Wildcard-Adressen im Browser durch Loopback ersetzen
    browser_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host  # nosec B104
    return f"http://{browser_host}:{port}"


def is_local_url(url: str) -> bool:
    """Loopback-Adresse dieses Rechners? Nur dorthin geht das Token (R5).

    Der Port ist bewusst frei: `conclave desktop` weicht auf einen freien Port aus, und ein
    lokaler Prozess desselben Benutzers koennte `api.token` ohnehin lesen.
    """
    try:
        parts = urlsplit(url)
        return parts.scheme in ("http", "https") and (parts.hostname or "").lower() in LOOPBACK_HOSTS
    except ValueError:
        return False


def url_with_token(url: str, token: str) -> str:
    """Token im Fragment uebergeben: landet nicht in Server-Logs, die UI entfernt es sofort."""
    return f"{url}#token={quote(token, safe='')}" if token else url


def open_browser(url: str) -> bool:
    return webbrowser.open(url)
