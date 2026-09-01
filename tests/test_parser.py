"""Style resolution: the cascade subset that email actually uses."""

import pytest

from preflight.parser import (
    declarations_for,
    element_path,
    load,
    parse_declarations,
    resolve_style,
    selector_matches,
    visible_text,
)


def _tag(html, ident):
    soup, sheet = load(html)
    return soup.find(id=ident), sheet


def test_parse_declarations_strips_important_and_blanks():
    assert parse_declarations("color: red !important; ; font-size:16px;") == {
        "color": "red", "font-size": "16px",
    }


@pytest.mark.parametrize("selector,matches", [
    ("p", True), (".card", True), ("#target", True), ("p.card", True),
    ("div p", True), ("div .card", True), ("span", False),
    ("#other", False), (".missing", False), ("td p", False),
])
def test_selector_matching(selector, matches):
    soup, _ = load('<div><p id="target" class="card">x</p></div>')
    assert selector_matches(soup.find(id="target"), selector) is matches


def test_inline_style_beats_stylesheet():
    tag, sheet = _tag('<style>.c{color:#111111}</style><p id="t" class="c" style="color:#222222">x</p>', "t")
    assert resolve_style(tag, sheet).color == (34, 34, 34)


def test_id_selector_beats_class_selector():
    tag, sheet = _tag('<style>.c{color:#111111} #t{color:#333333}</style><p id="t" class="c">x</p>', "t")
    assert resolve_style(tag, sheet).color == (51, 51, 51)


def test_color_inherits_background_does_not():
    html = '<div style="color:#123456;background-color:#ffffff"><p id="t">x</p></div>'
    tag, sheet = _tag(html, "t")
    style = resolve_style(tag, sheet)
    assert style.color == (18, 52, 86)
    assert style.background == (255, 255, 255)
    assert style.has_own_background is False


def test_nearest_painted_ancestor_wins():
    html = ('<body style="background-color:#000000"><td id="cell" bgcolor="#ffffff">'
            '<p id="t">x</p></td></body>')
    tag, sheet = _tag(html, "t")
    style = resolve_style(tag, sheet)
    assert style.background == (255, 255, 255)
    assert style.background_source == "td#cell"


@pytest.mark.parametrize("declared,expected_px", [
    ("font-size:20px", 20.0),
    ("font-size:12pt", 16.0),
    ("font-size:1.5rem", 24.0),
    ("font-size:150%", 24.0),
])
def test_font_size_units(declared, expected_px):
    tag, sheet = _tag(f'<p id="t" style="{declared}">x</p>', "t")
    assert resolve_style(tag, sheet).font_size_px == pytest.approx(expected_px)


def test_em_is_relative_to_parent():
    html = '<div style="font-size:20px"><p id="t" style="font-size:2em">x</p></div>'
    tag, sheet = _tag(html, "t")
    assert resolve_style(tag, sheet).font_size_px == pytest.approx(40.0)


def test_headings_are_bold_and_scaled_by_default():
    tag, sheet = _tag("<h1 id='t'>x</h1>", "t")
    style = resolve_style(tag, sheet)
    assert style.bold is True
    assert style.font_size_px == pytest.approx(32.0)


def test_background_shorthand_color_is_extracted():
    tag, sheet = _tag('<p id="t" style="background: #ff0000 url(x.png) no-repeat">x</p>', "t")
    assert resolve_style(tag, sheet).background == (255, 0, 0)


def test_media_rules_are_ignored_in_light_mode_and_applied_in_dark():
    html = ('<style>.c{color:#222222}'
            '@media (prefers-color-scheme: dark){.c{color:#eeeeee}}</style>'
            '<p id="t" class="c">x</p>')
    tag, sheet = _tag(html, "t")
    assert sheet.has_dark_mode_block is True
    assert resolve_style(tag, sheet).color == (34, 34, 34)
    assert resolve_style(tag, sheet, dark=True).color == (238, 238, 238)


def test_non_color_scheme_media_rules_never_apply():
    html = ('<style>.c{color:#222222}@media (max-width:600px){.c{color:#eeeeee}}</style>'
            '<p id="t" class="c">x</p>')
    tag, sheet = _tag(html, "t")
    assert resolve_style(tag, sheet, dark=True).color == (34, 34, 34)


def test_declarations_for_merges_cascade():
    tag, sheet = _tag('<style>p{color:#111111;font-size:14px}</style>'
                      '<p id="t" style="font-size:18px">x</p>', "t")
    decls = declarations_for(tag, sheet)
    assert decls["color"] == "#111111"
    assert decls["font-size"] == "18px"


def test_visible_text_strips_liquid_tags_but_keeps_literal_copy():
    """`{{ }}` and `{% %}` are removed; text they wrap is real copy and stays."""
    soup, _ = load('<p id="t">Hi {{ subscriber.first_name }}{% if x %}!{% endif %}</p>')
    assert visible_text(soup.find(id="t")) == "Hi !"


def test_visible_text_ignores_child_element_text():
    soup, _ = load('<div id="t"><span>child</span></div>')
    assert visible_text(soup.find(id="t")) == ""


def test_element_path_prefers_id_then_falls_back():
    soup, _ = load('<div><p id="named">a</p><p class="body">b</p></div>')
    assert element_path(soup.find(id="named")) == "named"
    assert element_path(soup.find("p", class_="body")).endswith("p.body")
