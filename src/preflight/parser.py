"""HTML + CSS parsing and style resolution for email documents.

Email HTML is not web HTML: styles are mostly inline, stylesheets are small and
flat, and the interesting cascade is `inline > #id > .class > tag`. This module
implements exactly that much of CSS - enough to resolve the colors and font
sizes the checks need, and no more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from .color import RGB, parse_color

#: Elements whose text we evaluate for contrast.
TEXT_TAGS = {
    "p", "span", "a", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th",
    "div", "strong", "em", "b", "i", "small", "button", "label", "blockquote",
}
#: Never inspected for visible text.
SKIP_TAGS = {"style", "script", "head", "title", "meta", "link"}

DEFAULT_FONT_PX = 16.0
HEADING_SCALE = {"h1": 2.0, "h2": 1.5, "h3": 1.17, "h4": 1.0, "h5": 0.83, "h6": 0.67}

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_MEDIA_RE = re.compile(r"@media([^{]*)\{(.*)", re.S)
_LIQUID_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)


@dataclass
class Rule:
    selector: str
    declarations: dict[str, str]
    media: str = ""
    specificity: tuple[int, int, int] = (0, 0, 0)
    order: int = 0
    #: Properties this rule declared `!important`.
    important: set[str] = field(default_factory=set)

    @property
    def is_dark_mode(self) -> bool:
        return "prefers-color-scheme" in self.media and "dark" in self.media


@dataclass
class Stylesheet:
    rules: list[Rule] = field(default_factory=list)

    @property
    def dark_rules(self) -> list[Rule]:
        return [r for r in self.rules if r.is_dark_mode]

    @property
    def has_dark_mode_block(self) -> bool:
        return bool(self.dark_rules)


def parse_declarations(text: str) -> dict[str, str]:
    return parse_declarations_flagged(text)[0]


def parse_declarations_flagged(text: str) -> tuple[dict[str, str], set[str]]:
    """Declarations plus the set of properties marked `!important`.

    Importance is not decoration here. Email HTML is mostly inline styles, and
    the one thing that can override an inline style is an `!important` author
    declaration - which is exactly how a dark-mode block is supposed to repaint
    a surface the light design pinned. Dropping the flag made those rules
    unreachable, so the fixer could write a correct override and the checker
    would never see it.
    """
    out: dict[str, str] = {}
    important: set[str] = set()
    for chunk in text.split(";"):
        if ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        prop = prop.strip().lower()
        flagged = "!important" in value.lower()
        value = re.split(r"!important", value, flags=re.I)[0].strip()
        if prop and value:
            out[prop] = value
            if flagged:
                important.add(prop)
    return out, important


def _specificity(selector: str) -> tuple[int, int, int]:
    return (
        selector.count("#"),
        selector.count(".") + selector.count("[") + selector.count(":"),
        len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", selector)),
    )


def _split_blocks(css: str, media: str, sheet: Stylesheet, order: list[int]) -> None:
    """Walk a CSS string, recursing one level into @media blocks."""
    i = 0
    while i < len(css):
        brace = css.find("{", i)
        if brace == -1:
            return
        prelude = css[i:brace].strip()
        depth, j = 1, brace + 1
        while j < len(css) and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        body = css[brace + 1 : j - 1]
        if prelude.startswith("@media"):
            _split_blocks(body, prelude[len("@media"):].strip(), sheet, order)
        elif prelude.startswith("@"):
            pass  # @font-face, @import - not style-resolving
        else:
            decls, important = parse_declarations_flagged(body)
            for sel in (s.strip() for s in prelude.split(",")):
                if sel:
                    order[0] += 1
                    sheet.rules.append(
                        Rule(sel, dict(decls), media, _specificity(sel), order[0],
                             set(important))
                    )
        i = j


def parse_stylesheet(soup: BeautifulSoup) -> Stylesheet:
    sheet = Stylesheet()
    order = [0]
    for style_tag in soup.find_all("style"):
        css = _COMMENT_RE.sub("", style_tag.get_text())
        _split_blocks(css, "", sheet, order)
    return sheet


def _matches_simple(tag: Tag, simple: str) -> bool:
    """Match one compound selector (`td.foo#bar`) against a tag."""
    if simple in ("*", ""):
        return True
    name_match = re.match(r"^[a-zA-Z][\w-]*", simple)
    if name_match:
        if tag.name.lower() != name_match.group(0).lower():
            return False
        simple = simple[name_match.end():]
    for cls in re.findall(r"\.([\w-]+)", simple):
        if cls not in (tag.get("class") or []):
            return False
    for ident in re.findall(r"#([\w-]+)", simple):
        if tag.get("id") != ident:
            return False
    return True


def selector_matches(tag: Tag, selector: str) -> bool:
    """Descendant-combinator matching. `>`/`+`/`~` degrade to descendant."""
    if any(p in selector for p in (":hover", ":focus", "::")):
        return False
    parts = [p for p in re.split(r"\s*[>+~]\s*|\s+", selector.strip()) if p]
    if not parts:
        return False
    if not _matches_simple(tag, parts[-1]):
        return False
    node = tag.parent
    for simple in reversed(parts[:-1]):
        while isinstance(node, Tag):
            if _matches_simple(node, simple):
                node = node.parent
                break
            node = node.parent
        else:
            return False
    return True


@dataclass
class Style:
    """Resolved style for one element."""

    color: RGB | None = None
    background: RGB | None = None
    background_source: str = ""  # tag name that supplied the background
    font_size_px: float = DEFAULT_FONT_PX
    bold: bool = False
    has_own_background: bool = False
    has_own_color: bool = False
    declared: dict[str, str] = field(default_factory=dict)


def _font_size(value: str, parent_px: float) -> float | None:
    v = value.strip().lower()
    try:
        if v.endswith("px"):
            return float(v[:-2])
        if v.endswith("pt"):
            return float(v[:-2]) * 4 / 3
        if v.endswith("rem"):
            return float(v[:-3]) * DEFAULT_FONT_PX
        if v.endswith("em"):
            return float(v[:-2]) * parent_px
        if v.endswith("%"):
            return float(v[:-1]) / 100 * parent_px
    except ValueError:
        return None
    return None


def declarations_for(tag: Tag, sheet: Stylesheet, dark: bool = False) -> dict[str, str]:
    """Cascade of stylesheet rules + inline style, in specificity/order.

    `dark=False` ignores dark-mode media blocks; `dark=True` layers them on top,
    which is how the dark-mode auditor simulates an OS-level scheme switch.
    """
    applicable = [
        r for r in sheet.rules
        if (not r.media or (dark and r.is_dark_mode)) and selector_matches(tag, r.selector)
    ]
    applicable.sort(key=lambda r: (bool(r.media), r.specificity, r.order))
    merged: dict[str, str] = {}
    important: set[str] = set()
    for rule in applicable:
        merged.update(rule.declarations)
        important |= rule.important

    # Inline wins by default - that is the email cascade. It does not win over
    # an `!important` author declaration, which is real CSS and is the only way
    # a stylesheet can repaint a surface the inline style already painted.
    inline, inline_important = parse_declarations_flagged(tag.get("style", ""))
    for prop, value in inline.items():
        if prop in important and prop not in inline_important:
            continue
        merged[prop] = value
    return merged


def resolve_style(
    tag: Tag, sheet: Stylesheet, dark: bool = False, _cache: dict | None = None
) -> Style:
    """Resolve inherited color/font-size and the nearest painted background."""
    chain: list[Tag] = []
    node: Tag | None = tag
    while isinstance(node, Tag) and node.name not in ("[document]",):
        chain.append(node)
        node = node.parent
    chain.reverse()

    style = Style(font_size_px=DEFAULT_FONT_PX)
    for element in chain:
        decls = declarations_for(element, sheet, dark)
        is_target = element is tag

        if element.name in HEADING_SCALE and "font-size" not in decls:
            style.font_size_px = DEFAULT_FONT_PX * HEADING_SCALE[element.name]
        if element.name in ("strong", "b", "th") or element.name in ("h1", "h2", "h3", "h4"):
            style.bold = True

        if "font-size" in decls:
            px = _font_size(decls["font-size"], style.font_size_px)
            if px:
                style.font_size_px = px
        if "font-weight" in decls:
            fw = decls["font-weight"].strip().lower()
            style.bold = fw in ("bold", "bolder") or (fw.isdigit() and int(fw) >= 600)

        color = parse_color(decls.get("color"))
        if color is not None:
            style.color = color
            if is_target:
                style.has_own_color = True

        bg = parse_color(decls.get("background-color")) or _bg_shorthand(decls)
        if bg is None and element.get("bgcolor"):
            bg = parse_color(element.get("bgcolor"))
        if bg is not None:
            style.background = bg
            style.background_source = element.name + (f"#{element['id']}" if element.get("id") else "")
            if is_target:
                style.has_own_background = True
        if is_target:
            style.declared = decls
    return style


def _bg_shorthand(decls: dict[str, str]) -> RGB | None:
    """`background: #fff url(...)` - pull the first color-looking token."""
    raw = decls.get("background")
    if not raw:
        return None
    for token in re.split(r"\s+(?![^(]*\))", raw.strip()):
        c = parse_color(token)
        if c is not None:
            return c
    return None


def visible_text(tag: Tag) -> str:
    """Direct text of an element, with Liquid tokens stripped.

    Liquid renders to unknown content, so `{{ subscriber.first_name }}` is not
    evidence of a real text node - but it is also not a reason to skip a check.
    """
    parts = [str(c) for c in tag.children if not isinstance(c, Tag)]
    return _LIQUID_RE.sub("", "".join(parts)).strip()


def element_path(tag: Tag) -> str:
    """Stable identity for a finding: the `id` if authored, else a short path."""
    if tag.get("id"):
        return str(tag["id"])
    parts = []
    node: Tag | None = tag
    while isinstance(node, Tag) and node.name != "[document]" and len(parts) < 3:
        seg = node.name
        classes = node.get("class") or []
        if classes:
            seg += "." + classes[0]
        parts.append(seg)
        node = node.parent
    return ">".join(reversed(parts))


def load(html: str) -> tuple[BeautifulSoup, Stylesheet]:
    soup = BeautifulSoup(html, "html.parser")
    return soup, parse_stylesheet(soup)
