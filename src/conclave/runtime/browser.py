import webbrowser
from urllib.parse import quote


def server_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return f"http://{browser_host}:{port}"


def url_with_token(url: str, token: str) -> str:
    """Token im Fragment uebergeben: landet nicht in Server-Logs, die UI entfernt es sofort."""
    return f"{url}#token={quote(token, safe='')}" if token else url


def open_browser(url: str) -> bool:
    return webbrowser.open(url)
