"""Settings-Seite im Browser: Server-Log und Rate-Limit."""

import json
import logging
import urllib.request

import pytest

from conclave.infrastructure.log import configure_logging


@pytest.fixture
def file_logging(tmp_path):
    logger = configure_logging("INFO", tmp_path / "conclave-server.log")
    logging.getLogger("conclave.test").warning("Hinweis fuer den Browser-Test <b>kein html</b>")
    yield
    for h in list(logger.handlers):
        if getattr(h, "_conclave_managed", False):
            logger.removeHandler(h)
            h.close()


def _wait_until(page, expression, timeout=10.0):
    """Wie wait_for_function, aber ohne eval im Seitenkontext (die CSP verbietet es)."""
    import time
    deadline = time.monotonic() + timeout
    while not page.evaluate(expression):
        assert time.monotonic() < deadline, f"Zeitueberschreitung: {expression}"
        page.wait_for_timeout(50)


def _settings(live_server):
    req = urllib.request.Request(live_server.url + "/settings",
                                 headers={"Authorization": f"Bearer {live_server.token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["settings"]


def test_settings_page_shows_logs_and_saves_rate_limit(chromium, live_server, file_logging):
    page = chromium.new_page()
    page.add_init_script("window.__csp=[];document.addEventListener('securitypolicyviolation',e=>window.__csp.push(e.violatedDirective));")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    original = _settings(live_server)["rate_limit"]["value"]
    try:
        page.goto(f"{live_server.url}/#token={live_server.token}")
        page.click("[data-action='switch-tab'][data-tab='settings']")

        page.wait_for_selector("#logList .log-row", timeout=10000)
        messages = page.locator("#logList .log-msg").all_inner_texts()
        assert any("<b>kein html</b>" in m for m in messages)  # als Text, nicht als HTML
        assert page.locator("#logList b").count() == 0

        page.select_option("#logLevel", "ERROR")
        _wait_until(page, "() => ![...document.querySelectorAll('#logList .log-msg')]"
                          ".some(e => e.textContent.includes('kein html'))")

        _wait_until(page, "() => document.getElementById('settingsRateLimit').value !== ''")
        page.fill("#settingsRateLimit", "500 per minute")
        page.click("#btnSaveRateLimit")
        _wait_until(page, "() => document.getElementById('settingsRateLimit').value === '500 per minute'")
        page.wait_for_timeout(300)
        assert _settings(live_server)["rate_limit"]["value"] == "500 per minute"

        page.fill("#settingsRateLimit", "viele")
        page.click("#btnSaveRateLimit")
        page.wait_for_selector(".toast.err", timeout=5000)
        assert _settings(live_server)["rate_limit"]["value"] == "500 per minute"

        assert page.evaluate("window.__csp") == []
        assert errors == []
    finally:
        req = urllib.request.Request(live_server.url + "/settings", method="PUT",
                                     data=json.dumps({"rate_limit": original}).encode(),
                                     headers={"Authorization": f"Bearer {live_server.token}",
                                              "Content-Type": "application/json"})
        urllib.request.urlopen(req).close()
        page.close()
