"""R4 (conclave#34): IDs in API-Pfaden der UI werden vollstaendig kodiert."""

import pytest


@pytest.mark.parametrize("value, expected", [
    ("../../../backup?", "..%2F..%2F..%2Fbackup%3F"),
    ("a/b#c", "a%2Fb%23c"),
    ("gpt-5.1_x", "gpt-5.1_x"),
])
def test_path_segment_encoding(chromium, live_server, value, expected):
    page = chromium.new_page()
    try:
        page.goto(f"{live_server.url}/#token={live_server.token}")
        page.wait_for_function("typeof pathSeg === 'function'")
        assert page.evaluate("v => pathSeg(v)", value) == expected
    finally:
        page.close()


@pytest.mark.parametrize("value", ["", ".", ".."])
def test_dot_segments_are_refused(chromium, live_server, value):
    page = chromium.new_page()
    try:
        page.goto(f"{live_server.url}/#token={live_server.token}")
        page.wait_for_function("typeof pathSeg === 'function'")
        assert page.evaluate("v => { try { pathSeg(v); return 'ok'; } catch (e) { return 'error'; } }", value) == "error"
    finally:
        page.close()


def test_invoke_request_stays_on_the_participant_route(chromium, live_server):
    """Selbst eine ID wie ../../backup? (kann der Server nicht mehr anlegen) bleibt im Pfad der Route."""
    page = chromium.new_page()
    seen = []
    page.on("request", lambda r: seen.append(r.url))
    try:
        page.goto(f"{live_server.url}/#token={live_server.token}")
        page.wait_for_function("typeof pathSeg === 'function'")
        page.evaluate("""() => { currentConvId = 'c1';
            return req('POST', `/conversations/${pathSeg(currentConvId)}/participants/${pathSeg('../../backup?')}/invoke`)
                .catch(() => null); }""")
        hits = [u for u in seen if "/invoke" in u or u.endswith("/backup")]
        assert hits and all("/conversations/c1/participants/..%2F..%2Fbackup%3F/invoke" in u for u in hits)
    finally:
        page.close()
