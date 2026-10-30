"""R5 (conclave#35): Token in der UI.

Ein Link mit ``#token=`` tauscht das Token nicht still aus, die Rolle steht sichtbar
in der Seitenleiste, Markdown kann weder ``class`` setzen noch Token-Links
erzeugen, und das Token liegt nur im ``sessionStorage`` des Tabs.
"""


def _open(page, live_server, token):
    page.goto(f"{live_server.url}/#token={token}")
    page.locator("#apiDot.ok, #apiDot.auth, #apiDot.err").wait_for(timeout=15000)


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
    try:
        _open(page, live_server, live_server.token)
        messages = []
        page.on("dialog", lambda d: (messages.append(d.message), d.dismiss()))
        page.goto(f"{live_server.url}/#token=foo")
        page.reload()
        for _ in range(300):                                                 # Rueckfrage nach whoami
            if messages:
                break
            page.wait_for_timeout(100)
        assert messages and ("Rolle" in messages[0] or "role" in messages[0])
        page.locator("#apiDot.ok").wait_for(timeout=15000)
        assert page.evaluate("AppState.getState('apiKey')") == live_server.token
        assert page.evaluate("sessionStorage.getItem('conclave_api_key')") == live_server.token
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
        page.locator("#apiDot.ok").wait_for(timeout=15000)
        stored = page.evaluate("({s: sessionStorage.getItem('conclave_api_key'), l: localStorage.getItem('conclave_api_key')})")
        assert stored == {"s": live_server.token, "l": None}
    finally:
        context.close()



def test_token_link_filter_parses_like_the_login(chromium, live_server):
    """Review R5: ungueltig kodiertes Fragment (decodeURIComponent wirft), URLSearchParams liest trotzdem token."""
    page = chromium.new_page()
    try:
        _open(page, live_server, live_server.token)
        for link in ["[x](http://127.0.0.1:8000/#%E0&%74oken=abc)", "[y](#%E0&%74oken=abc)",
                     "[z](#a=1&t%6Fken=abc)", "[w](#%74%6F%6B%65%6E=abc)"]:
            html = page.evaluate("v => renderMarkdown(v)", link)
            assert "href" not in html, (link, html)
            parsed = page.evaluate("v => new URLSearchParams(v).has('token')", link.split("#", 1)[1].rstrip(")"))
            assert parsed, link                                        # der Login wuerde das Token lesen
    finally:
        page.close()



def test_token_link_filter_uses_the_browsers_url_parser(chromium, live_server):
    """Review R5 (2): Tabs und Zeilenumbrueche entfernt der Browser beim Parsen - der Filter auch."""
    page = chromium.new_page()
    try:
        _open(page, live_server, live_server.token)
        for raw in ['<a href="http://127.0.0.1:8000/#to&#9;ken=abc">x</a>',
                    '<a href="http://127.0.0.1:8000/#to&#10;ken=abc">x</a>',
                    '<a href="#to&#13;ken=abc">x</a>',
                    '<a href="#a=1&amp;tok&#9;en=abc">x</a>']:
            html = page.evaluate("v => renderMarkdown(v)", raw)
            assert "href" not in html, (raw, html)
    finally:
        page.close()



def test_agent_token_link_in_a_new_tab_asks_first(chromium, live_server):
    """Entscheidung Laszlo: auch ohne gespeichertes Token nachfragen, wenn die Rolle Agent ist."""
    context = chromium.new_context()
    page = context.new_page()
    try:
        messages = []
        page.on("dialog", lambda d: (messages.append(d.message), d.dismiss()))
        page.goto(f"{live_server.url}/#token={live_server.agent_token}")
        page.locator("#apiDot.auth").wait_for(timeout=15000)
        assert messages and "Agent" in messages[0]                         # ohne Token geblieben
        assert page.evaluate("sessionStorage.getItem('conclave_api_key')") is None
    finally:
        context.close()


def test_invalid_token_link_in_a_new_tab_asks_first(chromium, live_server):
    context = chromium.new_context()
    page = context.new_page()
    try:
        messages = []
        page.on("dialog", lambda d: (messages.append(d.message), d.dismiss()))
        page.goto(f"{live_server.url}/#token=fantasie")
        page.locator("#apiDot.auth").wait_for(timeout=15000)
        assert messages
        page.locator("#apiDot.auth").wait_for(timeout=15000)
        assert page.evaluate("sessionStorage.getItem('conclave_api_key')") is None
    finally:
        context.close()


def test_human_token_in_a_new_tab_needs_no_question(chromium, live_server):
    context = chromium.new_context()
    page = context.new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    try:
        page.goto(f"{live_server.url}/#token={live_server.token}")
        page.locator("#apiDot.ok").wait_for(timeout=15000)
        assert dialogs == []
        assert page.evaluate("sessionStorage.getItem('conclave_api_key')") == live_server.token
    finally:
        context.close()
