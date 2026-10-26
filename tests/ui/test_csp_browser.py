"""AP 4 / B5: UI und /api-docs laufen unter der CSP ohne externe Ressourcen.

Laedt die echte App (live_server) in Chromium, sammelt CSP-Verstoesse,
Konsolenfehler und Anfragen an fremde Hosts.
"""

from urllib.parse import urlparse

import pytest


COLLECT_CSP_VIOLATIONS = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', e => {
  window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || '') + ' ' + (e.sourceFile || '') + ':' + e.lineNumber);
});
"""


def _load(chromium, url, wait_for):
    page = chromium.new_page()
    page.add_init_script(COLLECT_CSP_VIOLATIONS)
    problems, foreign = [], []
    origin = urlparse(url).netloc
    page.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("request", lambda r: urlparse(r.url).scheme in ("http", "https")
            and urlparse(r.url).netloc != origin and foreign.append(r.url))
    response = page.goto(url)
    page.wait_for_selector(wait_for, timeout=15000)
    page.wait_for_timeout(500)
    return page, response, problems, foreign


def _ignorable(problem: str) -> bool:
    # Bestehendes Verhalten, nicht Teil von AP 4: kein Favicon vorhanden
    return "favicon" in problem or "405" in problem


@pytest.fixture(scope="module")
def ui(chromium, live_server):
    page, response, problems, foreign = _load(chromium, live_server + "/", "#convList")
    yield page, response, problems, foreign
    page.close()


def test_ui_is_served_with_csp(ui):
    _, response, _, _ = ui
    csp = response.headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp
    assert "default-src 'self'" in csp


def test_ui_has_no_csp_violations(ui):
    page, _, _, _ = ui
    assert page.evaluate("window.__csp") == []


def test_ui_has_no_console_errors(ui):
    _, _, problems, _ = ui
    assert [p for p in problems if not _ignorable(p)] == []


def test_ui_makes_no_foreign_requests(ui):
    _, _, _, foreign = ui
    assert foreign == []


def test_ui_libraries_and_fonts_are_loaded(ui):
    page, _, _, _ = ui
    state = page.evaluate("""async () => {
      await document.fonts.ready;
      await Promise.all(['400 12px Syne', '400 12px "Syne Mono"', '400 12px "DM Sans"'].map(f => document.fonts.load(f)));
      return {
        marked: typeof marked, hljs: typeof hljs, purify: typeof DOMPurify,
        fonts: [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family.replace(/"/g, '')),
      };
    }""")
    assert state["marked"] == "object"
    assert state["hljs"] == "object"
    assert state["purify"] == "function"
    for family in ("Syne", "Syne Mono", "DM Sans"):
        assert family in state["fonts"]


def test_markdown_rendering_works_under_csp(ui):
    page, _, _, _ = ui
    result = page.evaluate("""() => {
      renderMessages([{author_type:'model', author_id:'m1', sequence:1, tool_events:[],
        content:'**fett** [ok](https://example.org)\\n\\n```python\\nprint(1)\\n```'}]);
      const m = document.querySelector('#messages .msg.model .msg-content');
      return {strong: m.querySelector('strong')?.textContent, hljs: !!m.querySelector('pre code.hljs'),
              href: m.querySelector('a')?.getAttribute('href'), csp: window.__csp};
    }""")
    assert result == {"strong": "fett", "hljs": True, "href": "https://example.org", "csp": []}


def test_api_docs_render_without_violations(chromium, live_server):
    page, response, problems, foreign = _load(chromium, live_server + "/api-docs", "#swagger-ui .info .title")
    try:
        assert "script-src 'self'" in response.headers.get("content-security-policy", "")
        assert page.evaluate("window.__csp") == []
        assert [p for p in problems if not _ignorable(p)] == []
        assert foreign == []
        assert "Conclave" in page.inner_text("#swagger-ui .info .title")
    finally:
        page.close()
