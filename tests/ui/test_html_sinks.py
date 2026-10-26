"""AP 1 / B1: HTML-Senken im Frontend sind inventarisiert und abgesichert.

Jede Zuweisung an innerHTML/outerHTML und jeder Aufruf von insertAdjacentHTML
braucht einen Kommentar ``// safe-html: <Begruendung>`` in derselben oder der
direkt vorangehenden Zeile. Neue Stellen ohne Begruendung lassen den Test
scheitern.
"""

import re
from pathlib import Path

from conclave.runtime.assets import get_asset_root


ASSET_ROOT = get_asset_root()
JS_ROOT = ASSET_ROOT / "static" / "js"
VENDOR_ROOT = ASSET_ROOT / "static" / "vendor"
HTML = ASSET_ROOT / "conclave-ui.html"

SINK = re.compile(r"\.(?:innerHTML|outerHTML)\s*=(?!=)|insertAdjacentHTML\s*\(|document\.write\s*\(")
MARKER = "// safe-html:"


def _js_files():
    return sorted(JS_ROOT.rglob("*.js"))


def _unmarked_sinks():
    missing = []
    for path in _js_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not SINK.search(line):
                continue
            previous = lines[index - 1] if index > 0 else ""
            if MARKER in line or previous.strip().startswith(MARKER):
                continue
            missing.append(f"{path.relative_to(JS_ROOT)}:{index + 1}: {line.strip()[:120]}")
    return missing


def test_every_html_sink_has_safe_html_marker():
    missing = _unmarked_sinks()
    assert not missing, "HTML-Senken ohne '// safe-html:'-Begruendung:\n" + "\n".join(missing)


def test_safe_html_markers_have_a_reason():
    for path in _js_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if MARKER in line:
                reason = line.split(MARKER, 1)[1].strip()
                assert reason, f"{path.name}:{number}: '// safe-html:' ohne Begruendung"


def test_sink_scanner_detects_unmarked_assignment():
    assert SINK.search("el.innerHTML=value;")
    assert SINK.search("el.insertAdjacentHTML('beforeend',html);")
    assert not SINK.search("if(el.innerHTML===''){}")
    assert not SINK.search("el.textContent=value;")


def test_render_markdown_sanitizes_with_dompurify():
    utils = (JS_ROOT / "utils.js").read_text(encoding="utf-8")
    body = utils.split("function renderMarkdown", 1)[1].split("\n}", 1)[0]
    assert "sanitizeHtml(marked.parse(" in body
    # Ohne DOMPurify nie rohes HTML zurueckgeben
    assert "!_markdownPurifier) return esc(text)" in body
    assert "ALLOWED_URI_REGEXP" in utils
    assert "noopener noreferrer" in utils


def test_markdown_allowlist_excludes_dangerous_tags_and_attributes():
    utils = (JS_ROOT / "utils.js").read_text(encoding="utf-8")
    tags = re.search(r"const MARKDOWN_ALLOWED_TAGS=\[(.*?)\];", utils, re.S).group(1)
    attrs = re.search(r"const MARKDOWN_ALLOWED_ATTR=\[(.*?)\];", utils, re.S).group(1)
    for tag in ("script", "style", "iframe", "object", "embed", "svg", "math", "form", "img", "link", "meta"):
        assert f"'{tag}'" not in tags
    for attribute in ("style", "id", "name", "src", "srcset", "action", "formaction"):
        assert f"'{attribute}'" not in attrs
    assert not re.search(r"'on\w+'", attrs)


def test_esc_escapes_quotes_for_attribute_context():
    utils = (JS_ROOT / "utils.js").read_text(encoding="utf-8")
    esc_line = next(line for line in utils.splitlines() if line.startswith("function esc("))
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert entity in esc_line


def test_dompurify_is_vendored_and_loaded_before_utils():
    purify = VENDOR_ROOT / "purify.min.js"
    assert purify.is_file()
    assert purify.read_text(encoding="utf-8").startswith("/*! @license DOMPurify ")
    html = HTML.read_text(encoding="utf-8")
    assert '<script src="static/vendor/purify.min.js"></script>' in html
    assert html.index("static/vendor/purify.min.js") < html.index("static/js/utils.js")


def test_unescaped_api_values_are_not_interpolated():
    """B14: bekannte Stellen mit ungeschuetzten Werten bleiben behoben."""
    participants = (JS_ROOT / "features" / "participants.js").read_text(encoding="utf-8")
    agents = (JS_ROOT / "features" / "agents.js").read_text(encoding="utf-8")
    assert 'value="${a.id}"' not in participants
    assert "(${a.id})" not in participants
    assert 'value="${p.id}"' not in participants
    assert 'value="${p.name}"' not in agents
    assert 'value="${m}"' not in agents
