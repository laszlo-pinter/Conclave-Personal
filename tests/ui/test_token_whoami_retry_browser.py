"""#96: Ein voruebergehender Fehler bei /auth/whoami darf das Token aus dem Fragment nicht verwerfen.

Mechanismus des instabilen UI-Tests: Scheitert die Rollenabfrage beim Start (Netzwerk, 5xx, 429),
galt das Token als "ungueltig". Die UI fragte per ``window.confirm`` nach, Playwright lehnt
Dialoge ab, das Token wurde nie gespeichert und jede weitere Anfrage bekam 401.
Nur 401/403 heissen "ungueltig"; voruebergehende Fehler werden kurz wiederholt.
"""

import pytest

pytest.importorskip("flask")


def _open(chromium, server, fail_whoami: int, status: int | None = None):
    page = chromium.new_page()
    seen = {"whoami": 0, "dialogs": [], "unauthorized": 0}

    def route(r):
        seen["whoami"] += 1
        if seen["whoami"] <= fail_whoami:
            if status is None:
                r.abort("connectionreset")
            else:
                r.fulfill(status=status, body="{}", content_type="application/json")
        else:
            r.continue_()

    page.route("**/auth/whoami", route)
    page.on("dialog", lambda d: (seen["dialogs"].append(d.message), d.dismiss()))
    page.on("response", lambda r: seen.__setitem__("unauthorized", seen["unauthorized"] + (r.status == 401)))
    page.goto(f"{server.url}/#token={server.token}")
    return page, seen


def _token_stored(page) -> bool:
    return bool(page.evaluate("() => sessionStorage.getItem('conclave_api_key')"))


@pytest.mark.parametrize("fail, status", [(1, None), (2, None), (1, 503), (1, 429)],
                         ids=["reset", "reset-twice", "503", "429"])
def test_transient_whoami_failure_keeps_the_token(chromium, live_server, fail, status):
    page, seen = _open(chromium, live_server, fail_whoami=fail, status=status)
    try:
        page.wait_for_function("() => !!sessionStorage.getItem('conclave_api_key')", timeout=10000)
        page.wait_for_timeout(500)
        assert seen["dialogs"] == [] and seen["unauthorized"] == 0, seen
        assert seen["whoami"] > fail                     # nach den Fehlern erneut gefragt
    finally:
        page.close()


def test_real_rejection_still_asks(chromium, live_server):
    """401 bleibt "ungueltig": Nachfrage, kein stilles Uebernehmen."""
    page, seen = _open(chromium, live_server, fail_whoami=99, status=401)
    try:
        page.wait_for_timeout(1500)
        assert len(seen["dialogs"]) == 1 and not _token_stored(page)
        assert seen["whoami"] == 1                       # keine Wiederholung bei 401
    finally:
        page.close()
