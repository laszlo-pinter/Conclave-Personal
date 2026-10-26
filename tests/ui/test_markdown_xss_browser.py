"""AP 1 / B1: XSS-Payloads aus Modellantworten werden im Browser nicht ausgefuehrt.

Laedt das ausgelieferte DOMPurify und utils.js in einen Headless-Browser und
fuegt Payloads ueber renderMarkdown() per innerHTML ein. ``marked`` wird durch
einen Durchreicher ersetzt (rohes HTML geht unveraendert in den Filter) - das
ist der unguenstigste Fall und macht den Test unabhaengig vom CDN.

Benoetigt Playwright mit Chromium (``pip install -e ".[dev-ui]"`` und
``python -m playwright install chromium``); sonst wird der Test uebersprungen.
Mit ``CONCLAVE_REQUIRE_BROWSER=1`` (CI-Job ``ui-browser``) scheitert er
stattdessen (siehe conftest.py).
"""

import json

import pytest

from conclave.runtime.assets import get_asset_root


ASSET_ROOT = get_asset_root()

PAYLOADS = [
    '<img src=x onerror="window.__xss=1">BILD',
    '<script>window.__xss=2</script>SKRIPT',
    '<a href="javascript:window.__xss=3">JSLINK</a>',
    '<a href="JaVaScRiPt:window.__xss=3">JSLINK2</a>',
    '<svg onload="window.__xss=4"><circle r="1"/></svg>SVG',
    '<iframe srcdoc="<script>parent.__xss=5</script>"></iframe>IFRAME',
    '<details open ontoggle="window.__xss=6">DETAILS</details>',
    '<p style="background:url(javascript:window.__xss=7)" onclick="window.__xss=7">STIL</p>',
    '<form action="javascript:window.__xss=8"><button>FORM</button></form>',
    '<a href="data:text/html,<script>window.__xss=9</script>">DATALINK</a>',
    '<math><mtext><table><mglyph><style><img src=x onerror="window.__xss=10">MATH',
    '<input type="text" autofocus onfocus="window.__xss=11">INPUT',
    '<div id="sc">CLOBBER</div>',
]

SAFE_MARKDOWN = (
    '<p>Text <a href="https://example.org">HTTPS</a> <a href="mailto:a@example.org">MAIL</a></p>'
    '<pre><code class="language-python">print(1)</code></pre>'
    '<ul><li><input type="checkbox" checked> TASK</li></ul>'
    '<table><thead><tr><th align="center">KOPF</th></tr></thead><tbody><tr><td colspan="2">ZELLE</td></tr></tbody></table>'
    '<ol start="3"><li>DREI</li></ol>'
)


def _harness_html() -> str:
    # Skripte per src laden wie in der echten UI (DOMPurify laesst sich nicht inline einbetten)
    purify = (ASSET_ROOT / "static" / "vendor" / "purify.min.js").as_uri()
    utils = (ASSET_ROOT / "static" / "js" / "utils.js").as_uri()
    # "</" escapen, damit "</script>" in den Payloads den Skriptblock nicht beendet
    payloads = json.dumps(PAYLOADS + [SAFE_MARKDOWN]).replace("</", "<\\/")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<script>window.marked={{parse:s=>s}};function getLanguage(){{return 'de';}}</script>
<script src="{purify}"></script>
<script src="{utils}"></script>
</head><body><div id="out"></div>
<script>
const out=document.getElementById('out');
for(const p of {payloads}){{
  const d=document.createElement('div');d.className='case';
  d.innerHTML=renderMarkdown(p);
  out.appendChild(d);
}}
</script></body></html>"""


EVALUATE = """() => {
  const out = document.getElementById('out');
  const all = [...out.querySelectorAll('*')];
  return {
    xss: window.__xss || null,
    purifierActive: typeof _markdownPurifier !== 'undefined' && _markdownPurifier !== null,
    forbidden: all.filter(el => /^(SCRIPT|IMG|SVG|IFRAME|STYLE|FORM|BUTTON|MATH|DETAILS|OBJECT|EMBED)$/i.test(el.tagName)).map(el => el.tagName),
    eventAttrs: all.flatMap(el => [...el.attributes].filter(a => /^on/i.test(a.name)).map(a => el.tagName + ' ' + a.name)),
    styleAttrs: all.filter(el => el.hasAttribute('style')).length,
    idAttrs: all.filter(el => el.hasAttribute('id')).length,
    hrefs: [...out.querySelectorAll('a[href]')].map(a => ({href: a.getAttribute('href'), rel: a.getAttribute('rel'), target: a.getAttribute('target')})),
    inputs: [...out.querySelectorAll('input')].map(i => ({type: i.getAttribute('type'), disabled: i.hasAttribute('disabled')})),
    codeClass: out.querySelector('pre code')?.className || '',
    align: out.querySelector('th')?.getAttribute('align') || '',
    colspan: out.querySelector('td')?.getAttribute('colspan') || '',
    olStart: out.querySelector('ol')?.getAttribute('start') || '',
    text: out.textContent,
  };
}"""


@pytest.fixture(scope="module")
def rendered(chromium, tmp_path_factory):
    harness = tmp_path_factory.mktemp("xss") / "harness.html"
    harness.write_text(_harness_html(), encoding="utf-8")
    page = chromium.new_page()
    try:
        page.goto(harness.as_uri())
        page.wait_for_timeout(500)  # onerror/onload-Handler laufen asynchron
        return page.evaluate(EVALUATE)
    finally:
        page.close()


def test_dompurify_is_active(rendered):
    assert rendered["purifierActive"] is True


def test_no_payload_executes(rendered):
    assert rendered["xss"] is None


def test_dangerous_elements_and_attributes_are_removed(rendered):
    assert rendered["forbidden"] == []
    assert rendered["eventAttrs"] == []
    assert rendered["styleAttrs"] == 0
    assert rendered["idAttrs"] == 0


def test_only_safe_links_survive_and_open_safely(rendered):
    hrefs = [link["href"] for link in rendered["hrefs"]]
    assert hrefs == ["https://example.org", "mailto:a@example.org"]
    for link in rendered["hrefs"]:
        assert link["rel"] == "noopener noreferrer"
        assert link["target"] == "_blank"


def test_visible_text_is_kept(rendered):
    for marker in ("BILD", "SKRIPT", "JSLINK", "SVG", "IFRAME", "DETAILS", "STIL",
                   "DATALINK", "CLOBBER", "HTTPS", "MAIL", "TASK", "KOPF", "ZELLE"):
        assert marker in rendered["text"]


def test_markdown_features_survive(rendered):
    assert rendered["codeClass"] == "language-python"
    assert rendered["inputs"] == [{"type": "checkbox", "disabled": True}]
    assert rendered["align"] == "center"
    assert rendered["colspan"] == "2"
    assert rendered["olStart"] == "3"
