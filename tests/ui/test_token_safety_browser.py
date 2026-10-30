"""R5 (conclave#35): Token in der UI.

Ein Link mit ``#token=`` tauscht das Token nicht still aus, die Rolle steht sichtbar
in der Seitenleiste, Markdown kann weder ``class`` setzen noch Token-Links
erzeugen, und das Token liegt nur im ``sessionStorage`` des Tabs.
"""


def _open(page, live_server, token):
    page.goto(f"{live_server.url}/#token={token}")
    page.wait_for_function("document.getElementById('apiDot').className !== 'api-dot'", timeout=15000)


def test_markdown_drops_class_but_keeps_code_language(chromium, live_server):
    page = chromium.new_page()
    try:
        _open(page, live_server, live_server.token)
        html = page.evaluate("renderMarkdown('<div class=\"overlay open\">x</div>')")
        assert "class" not in html
        code = page.evaluate("renderMarkdown('```python\\nprint(1)\\n```')")
        assert 'class="language-python"' in code
        other = page.evaluate("renderMarkdown('<code class=\"overlay\">x</code>')")
        assert "class" not in other
    finally:
        page.close()


def test_markdown_token_links_lose_their_target(chromium, live_server):
    page = chromium.new_page()
    try:
        _open(page, live_server, live_server.token)
        evil = page.evaluate("renderMarkdown('[Details](#token=foo) [B](#a&TOKEN=x)')")
        assert "token=" not in evil.lower() and "href" not in evil
        local = page.evaluate("renderMarkdown('[Abschnitt](#teil-2)')")
        assert 'href="#teil-2"' in local and "_blank" not in local
        external = page.evaluate("renderMarkdown('[Doku](https://example.org/x)')")
        assert 'target="_blank"' in external
    finally:
        page.close()


def test_fragment_token_does_not_replace_another_token_silently(chromium, live_server):
    page = chromium.new_page()
    dialogs = []

    def on_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", on_dialog)
    try:
        _open(page, live_server, live_server.token)
        page.goto(f"{live_server.url}/#token=foo")
        page.reload()
        for _ in range(100):                                                # Rueckfrage nach whoami abwarten
            if dialogs:
                break
            page.wait_for_timeout(100)
        assert page.evaluate("AppState.getState('apiKey')") == live_server.token
        assert page.evaluate("sessionStorage.getItem('conclave_api_key')") == live_server.token
        assert dialogs, "keine Rueckfrage"
    finally:
        page.close()


def test_confirmed_switch_shows_the_new_role(chromium, live_server):
    page = chromium.new_page()
    page.on("dialog", lambda d: d.accept())
    agent = live_server.agent_token
    try:
        _open(page, live_server, live_server.token)
        badge = page.locator("#roleBadge")
        badge.wait_for(state="visible", timeout=10000)
        assert badge.inner_text() == "Mensch"
        page.goto(f"{live_server.url}/#token={agent}")
        page.reload()
        page.locator("#roleBadge.role-agent").wait_for(timeout=10000)
        assert page.evaluate("AppState.getState('apiKey')") == agent
        assert "role-agent" in (badge.get_attribute("class") or "")
    finally:
        page.close()


def test_token_lives_in_session_storage_only(chromium, live_server):
    context = chromium.new_context()
    page = context.new_page()
    try:
        _open(page, live_server, live_server.token)
        stored = page.evaluate("({s: sessionStorage.getItem('conclave_api_key'), l: localStorage.getItem('conclave_api_key')})")
        assert stored == {"s": live_server.token, "l": None}
    finally:
        context.close()


def test_old_local_storage_token_is_moved_once(chromium, live_server):
    """Wer bisher eingeloggt war, bleibt es in diesem Tab; localStorage wird geleert."""
    context = chromium.new_context()
    page = context.new_page()
    try:
        page.goto(live_server.url + "/")
        page.evaluate(f"localStorage.setItem('conclave_api_key', '{live_server.token}')")
        page.reload()
        page.wait_for_function("document.getElementById('apiDot').className === 'api-dot ok'", timeout=15000)
        stored = page.evaluate("({s: sessionStorage.getItem('conclave_api_key'), l: localStorage.getItem('conclave_api_key')})")
        assert stored == {"s": live_server.token, "l": None}
    finally:
        context.close()
