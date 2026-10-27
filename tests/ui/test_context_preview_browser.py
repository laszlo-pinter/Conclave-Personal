"""K4: Vorschau vor dem Aufruf im Browser (ohne Provider-Aufruf)."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from test_context_chip_browser import (  # noqa: E402,F401 - Fixture wird von pytest benutzt
    _open_conversation,
    _wait_until,
    context_server,
)


def _no_provider_calls():
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Die Vorschau darf keinen Provider aufrufen")

    return calls, patch("httpx.post", fail), patch("httpx.stream", fail)


def test_preview_shows_truncation_for_selected_participant(chromium, context_server):
    calls, post, stream = _no_provider_calls()
    with post, stream:
        page, errors = _open_conversation(chromium, context_server)
        try:
            assert page.locator("#ctxPreview").is_hidden()        # ohne Teilnehmer keine Vorschau
            _wait_until(page, "() => [...document.querySelectorAll('#pSel option')].some(o => o.value === 'p1')")
            page.select_option("#pSel", "p1")
            _wait_until(page, "() => !document.getElementById('ctxPreview').hidden")
            preview = page.locator("#ctxPreview")
            assert "5" in preview.inner_text() and "11" in preview.inner_text()
            classes = preview.get_attribute("class")
            assert "truncated" in classes and "strong" in classes

            # Neue Nachricht: Vorschau zaehlt mit (entprellt)
            page.fill("#msgInput", "Noch ein Beitrag")
            page.click("[data-action='send-msg']")
            _wait_until(page, "() => document.getElementById('ctxPreview').textContent.includes('12')")

            # Teilnehmer abwaehlen: Vorschau verschwindet
            page.select_option("#pSel", "")
            _wait_until(page, "() => document.getElementById('ctxPreview').hidden")

            assert calls == []
            assert page.evaluate("window.__csp") == []
            assert errors == []
        finally:
            page.close()


def test_orchestration_dialog_previews_each_participant(chromium, context_server):
    calls, post, stream = _no_provider_calls()
    with post, stream:
        page, errors = _open_conversation(chromium, context_server)
        try:
            _wait_until(page, "() => [...document.querySelectorAll('#pSel option')].some(o => o.value === 'p1')")
            page.click("[data-action='open-orch']")
            _wait_until(page, "() => document.querySelectorAll('#orchPreview .ctx-preview-row').length === 1")
            row = page.locator("#orchPreview .ctx-preview-row").first
            assert "Modell" in row.inner_text()                   # Name statt ID
            assert "11" in row.inner_text()

            # Unbekannte ID wird weggelassen, bekannte bleibt
            page.fill("#orchSeq", "p1, gibtsnicht")
            page.wait_for_timeout(800)
            assert page.locator("#orchPreview .ctx-preview-row").count() == 1

            page.click("[data-action='close-overlay'][data-overlay='overlayOrch']")
            page.click("[data-action='open-autoloop']")
            _wait_until(page, "() => document.querySelectorAll('#loopPreview .ctx-preview-row').length === 1")

            assert calls == []
            assert page.evaluate("window.__csp") == []
            assert errors == []
        finally:
            page.close()
