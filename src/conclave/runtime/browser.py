import webbrowser


def server_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return f"http://{browser_host}:{port}"


def open_browser(url: str) -> bool:
    return webbrowser.open(url)
