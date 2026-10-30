"""R3 (conclave#33): Hinweis im Agenten-Formular, wenn die Adresse nicht zum Preset gehoert."""


def test_hint_appears_for_a_foreign_address(chromium, live_server):
    page = chromium.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(f"{live_server.url}/#token={live_server.token}")
        page.click("[data-action='switch-tab'][data-tab='agents']")
        page.click("[data-action='open-agent-form']")
        page.locator("#aPreset option[value='openai']").wait_for(state="attached", timeout=10000)
        page.select_option("#aPreset", "openai")
        hint = page.locator("#aApiUrlHint")
        assert hint.is_hidden()                                             # Preset-Adresse
        page.click("[data-action='toggle-advanced']")
        page.fill("#aApiUrl", "https://gateway.invalid/v1/chat/completions")
        assert hint.is_visible()
        page.fill("#aApiUrl", "http://api.openai.com/v1/chat/completions")
        assert hint.is_visible()                                            # gleicher Host, anderes Schema
        page.fill("#aApiUrl", "https://api.openai.com/v1/chat/completions")
        assert hint.is_hidden()                                             # gleicher Host
        assert errors == []
    finally:
        page.close()
