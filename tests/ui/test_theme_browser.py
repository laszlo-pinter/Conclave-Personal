"""conclave#62: heller Modus.

Die UI folgt ``prefers-color-scheme``; ein Umschalter (System / hell / dunkel) ueberstimmt
die Systemeinstellung und bleibt im Browser gespeichert. In beiden Modi hat jeder sichtbare
Text einen Kontrast von mindestens 4,5:1 zu seinem Hintergrund.
"""

import re
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[2] / "src" / "conclave" / "assets"

# Kontrast aller sichtbaren Texte; Hintergruende mit Alpha werden ueber die Vorfahren verrechnet
CONTRAST_JS = r"""
() => {
  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return [0, 0, 0, 0];
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const over = (top, under) => { const a = top[3] + under[3] * (1 - top[3]); if (!a) return [0, 0, 0, 0];
    return [0, 1, 2].map(i => (top[i] * top[3] + under[i] * under[3] * (1 - top[3])) / a).concat([a]); };
  const lum = c => { const [r, g, b] = c.slice(0, 3).map(v => { v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const background = el => { const chain = []; for (let n = el; n; n = n.parentElement) chain.push(parse(getComputedStyle(n).backgroundColor));
    let bg = [255, 255, 255, 1]; for (const c of chain.reverse()) bg = over(c, bg); return bg; };
  const bad = [];
  for (const el of document.querySelectorAll('body *')) {
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own || !el.checkVisibility({opacityProperty: true, visibilityProperty: true})) continue;
    if (el.closest('[disabled], option, .hljs, pre, script, style')) continue;
    const s = getComputedStyle(el);
    if (s.animationName !== 'none') continue;
    const bg = background(el);
    const fg = over(parse(s.color), bg);
    const [l1, l2] = [lum(fg), lum(bg)].sort((a, b) => b - a);
    const ratio = (l1 + 0.05) / (l2 + 0.05);
    if (ratio < 4.5) bad.push(`${el.tagName.toLowerCase()}.${el.className} "${el.textContent.trim().slice(0, 30)}" ${ratio.toFixed(2)}`);
  }
  return bad;
}
"""


def _open(browser, server, scheme):
    context = browser.new_context(color_scheme=scheme)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server.url}/#token={server.token}")
    page.locator("#languageSelect").wait_for()
    _wait_for_theme(page)
    return context, page, errors


def _wait_for_theme(page):
    """Erst pruefen, wenn theme.css angewendet ist (sonst ist der Hintergrund durchsichtig)."""
    page.wait_for_function("getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() !== ''",
                           timeout=10000)


def _body_luminance(page):
    """Helligkeit des Seitenhintergrunds; None, solange er durchsichtig ist."""
    return page.evaluate("""() => { const m = getComputedStyle(document.body).backgroundColor.match(/[\\d.]+/g).map(Number);
        if (m.length > 3 && m[3] === 0) return null;
        const [r, g, b] = m.slice(0, 3).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
        return 0.2126 * r + 0.7152 * g + 0.0722 * b; }""")


@pytest.mark.parametrize("scheme, light", [("light", True), ("dark", False)])
def test_ui_follows_the_system_color_scheme(chromium, live_server, scheme, light):
    context, page, errors = _open(chromium, live_server, scheme)
    try:
        lum = _body_luminance(page)
        assert lum is not None and ((lum > 0.8) if light else (lum < 0.05)), (scheme, lum)
        assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == scheme
        assert errors == []
    finally:
        context.close()


def test_theme_switch_overrides_the_system_and_is_remembered(chromium, live_server):
    context, page, errors = _open(chromium, live_server, "light")
    try:
        select = page.locator("#themeSelect")
        assert select.input_value() == "system"
        select.select_option("dark")
        assert (_body_luminance(page) or 1) < 0.05
        page.reload()
        page.locator("#themeSelect").wait_for()
        _wait_for_theme(page)
        assert page.locator("#themeSelect").input_value() == "dark"
        assert (_body_luminance(page) or 1) < 0.05
        page.locator("#themeSelect").select_option("system")
        assert _body_luminance(page) > 0.8
        assert errors == []
    finally:
        context.close()


SURFACES = ["conv", "agents", "workspace", "board", "runs", "settings"]


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_every_visible_text_has_enough_contrast(chromium, live_server, scheme):
    context, page, errors = _open(chromium, live_server, scheme)
    try:
        bad = {}
        for tab in SURFACES:
            button = page.locator(f"[data-action='switch-tab'][data-tab='{tab}']")
            if button.count():
                button.first.click()
                page.wait_for_timeout(300)
            found = page.evaluate(CONTRAST_JS)
            if found:
                bad[tab] = found
        assert bad == {}, (scheme, bad)
        assert errors == []
    finally:
        context.close()


HEX_OR_RGB = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d")


@pytest.mark.parametrize("path", [
    "static/css/components.css", "static/css/layout.css",
    *[str(p.relative_to(ASSETS)).replace("\\", "/") for p in sorted((ASSETS / "static" / "js").rglob("*.js"))],
])
def test_no_fixed_colors_outside_the_theme(path):
    """Farben nur als Variablen aus theme.css, damit hell und dunkel dieselben Regeln nutzen."""
    text = (ASSETS / path).read_text(encoding="utf-8")
    text = re.sub(r"&#\d+;", "", text)                      # HTML-Entities wie &#127908; sind keine Farben
    assert HEX_OR_RGB.findall(text) == [], path


def _theme_blocks():
    css = (ASSETS / "static" / "css" / "theme.css").read_text(encoding="utf-8")
    dark = dict(re.findall(r"--([\w-]+):(#[0-9a-fA-F]{6})", css[css.index(":root{"):css.index("@media")]))
    light_css = css[css.index(':root[data-theme="light"]'):]
    light = {**dark, **dict(re.findall(r"--([\w-]+):(#[0-9a-fA-F]{6})", light_css[:light_css.index("}")]))}
    return {"dark": dark, "light": light}


def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _tint(fg, alpha, bg):
    return "#" + "".join(f"{round(int(fg[i:i + 2], 16) * alpha + int(bg[i:i + 2], 16) * (1 - alpha)):02x}"
                         for i in (1, 3, 5))


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


TEXT_TOKENS = ["text", "text-dim", "text-faint", "accent", "purple", "danger", "danger-text", "floor-color",
               *[f"p{i}-tx" for i in range(6)]]


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_palette_text_colors_reach_4_5_on_every_surface(mode):
    """Auch Farben, die erst mit Daten erscheinen (Teilnehmer, Status): auf Seite, Karten und
    Panels; farbige Texte auch auf ihrem eigenen Farbstich (bis 13 %)."""
    tokens = _theme_blocks()[mode]
    surfaces = [tokens[f] for f in ("bg", "bg-2", "bg-3")]       # Seite, Karten, Panels (bg-4/5: Eingaben)
    bad = []
    for name in TEXT_TOKENS:
        fg = tokens[name]
        for bg in surfaces:
            for alpha in ((0,) if name.startswith("text") else (0, 0.13)):
                ratio = _ratio(fg, _tint(fg, alpha, bg))
                if ratio < 4.5:
                    bad.append((name, bg, alpha, round(ratio, 2)))
    for on, under in (("on-accent", "accent"), ("on-floor", "floor-color"), ("on-strong", "purple"),
                      ("on-strong", "danger")):
        if _ratio(tokens[on], tokens[under]) < 4.5:
            bad.append((on, under, round(_ratio(tokens[on], tokens[under]), 2)))
    assert bad == [], (mode, bad)
