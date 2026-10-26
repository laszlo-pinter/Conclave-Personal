"""AP 2 / B12: Die UI uebernimmt das Token aus dem URL-Fragment (conclave desktop)."""


def _open(chromium, url):
    page = chromium.new_page()
    statuses = []
    page.on("response", lambda r: "/conversations" in r.url and statuses.append(r.status))
    page.goto(url)
    page.wait_for_function("document.getElementById('apiDot').className !== 'api-dot'", timeout=15000)
    page.wait_for_timeout(300)
    return page, statuses


def test_fragment_token_logs_in_and_is_removed_from_url(chromium, live_server):
    page, statuses = _open(chromium, f"{live_server.url}/#token={live_server.token}")
    try:
        state = page.evaluate("""() => ({
            hash: window.location.hash,
            href: window.location.href,
            stored: localStorage.getItem('conclave_api_key'),
            dot: document.getElementById('apiDot').className,
        })""")
        assert state["hash"] == ""
        assert live_server.token not in state["href"]
        assert state["stored"] == live_server.token
        assert state["dot"] == "api-dot ok"
        assert statuses and all(s == 200 for s in statuses)
    finally:
        page.close()


def test_ui_without_token_loads_but_reports_auth_failure(chromium, live_server):
    context = chromium.new_context()  # leerer localStorage
    page = context.new_page()
    try:
        response = page.goto(live_server.url + "/")
        assert response.status == 200  # B12: Seite selbst braucht kein Token
        page.wait_for_function("document.getElementById('apiDot').className !== 'api-dot'", timeout=15000)
        assert page.evaluate("document.getElementById('apiDot').className") == "api-dot auth"
    finally:
        context.close()
