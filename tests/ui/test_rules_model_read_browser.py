"""R6 (conclave#41): Freigabe fuer @read im Dialog "Chat-Regeln"."""

import json
import urllib.request


def _api(live_server, method, path, body=None):
    req = urllib.request.Request(live_server.url + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {live_server.token}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def test_toggle_saves_model_read(chromium, live_server):
    conv = _api(live_server, "POST", "/conversations", {})["conversation_id"]
    page = chromium.new_page()
    try:
        page.goto(f"{live_server.url}/#token={live_server.token}")
        page.locator(f"[data-action='select-conversation'][data-conversation-id='{conv}']").click()
        page.click("[data-action='open-rules-modal']")
        box = page.locator("#rulesModelRead")
        box.wait_for(state="visible", timeout=10000)
        assert not box.is_checked()
        box.check()
        page.click("[data-action='save-rules']")
        for _ in range(50):                                                  # Speichern abwarten
            if _api(live_server, "GET", f"/conversations/{conv}/rules")["model_read"]:
                break
            page.wait_for_timeout(100)
        assert _api(live_server, "GET", f"/conversations/{conv}/rules")["model_read"] is True
    finally:
        page.close()
