"""Module C - the 1-click auto-fix engine.

Non-destructive contract, in priority order:

1. Never touch Liquid. `{{ ... }}` and `{% ... %}` pass through byte-identical;
   a fix that breaks personalization is worse than the bug it fixed.
2. Never rewrite the creator's stylesheet. Contrast and dark-mode repairs are
   applied as inline overrides on the offending element - which is also what
   email clients honour most reliably.
3. Never restructure layout. Tables, widths, and custom markup are untouched.
4. Every change is reported as an `AppliedFix`, so `fix` can print a diff
   summary rather than handing back a black box.

Known limit: the document round-trips through BeautifulSoup, whose parser
collapses indentation inside whitespace-only text nodes. Tags, attributes,
attribute order, and Liquid are byte-identical; leading spaces on otherwise
blank lines are not. This is invisible to every mail client and visible in
`git diff`, which is the honest trade and not a silent one.

Anything more opinionated than that (rewriting CTA copy, moving a button above
the fold) is gated behind `aggressive=True` and stays advisory by default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString
from bs4.formatter import HTMLFormatter

from ..color import contrast_ratio, nearest_compliant, parse_color, required_ratio, to_hex
from ..models import Finding
from ..parser import Stylesheet, element_path, load, parse_declarations, resolve_style

DEFAULT_FG = (0, 0, 0)
DEFAULT_BG = (255, 255, 255)
_LIQUID_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
_BARE_URL_RE = re.compile(r"(?<![\"'=>])\bhttps?://[^\s<>\"')\]]+", re.I)
_SLUG_RE = re.compile(r"[-_]+")
_DOCTYPE_RE = re.compile(r"^\s*<!doctype[^>]*>\n?", re.I)


class _MinimalChurn(HTMLFormatter):
    """Serialize with the least possible diff against the creator's source.

    The default formatter alphabetizes attributes and XHTML-closes void tags.
    Both are semantically harmless and both make `git diff` on a fixed email
    unreadable, which defeats the point of showing the creator what changed.
    """

    def attributes(self, tag):
        return [(k, "" if v is None else v) for k, v in tag.attrs.items()]


_FORMATTER = _MinimalChurn(void_element_close_prefix="", empty_attributes_are_booleans=True)


def serialize(soup: BeautifulSoup, original: str) -> str:
    """Render the tree back to HTML, restoring the creator's own doctype line."""
    out = soup.decode(formatter=_FORMATTER)
    source_doctype = _DOCTYPE_RE.match(original)
    if source_doctype:
        out = _DOCTYPE_RE.sub("", out, count=1).lstrip("\n")
        out = source_doctype.group(0) + out
    return out


@dataclass
class AppliedFix:
    code: str
    target: str
    detail: str


class TargetIndex:
    """Ground-truth targets to elements, one element per finding.

    A plain `{element_path(t): t}` dict silently collapses every element that
    shares a path. On a real newsletter that is common - twenty article
    thumbnails sit at the same `div>a>img` - and the consequence is worse than
    a missed repair: the fixer edits the *same* image once per finding and
    reports twenty fixes, so it claims work it did not do.

    Handing out each matching element once keeps the count honest and repairs
    all twenty. `element_path` was always documented as non-unique; this is the
    part of the system that has to cope with it (D37).
    """

    def __init__(self, soup, name: str | bool = True):
        self._queues: dict[str, list] = {}
        for tag in soup.find_all(name):
            self._queues.setdefault(element_path(tag), []).append(tag)

    def take(self, target: str):
        """The next element for this target, or None once they are used up."""
        queue = self._queues.get(target)
        return queue.pop(0) if queue else None


def _set_inline(tag, prop: str, value: str) -> None:
    """Merge one declaration into an element's inline style, preserving order."""
    decls = parse_declarations(tag.get("style", ""))
    decls[prop] = value
    tag["style"] = "; ".join(f"{k}: {v}" for k, v in decls.items())


def fix_contrast(soup: BeautifulSoup, sheet: Stylesheet, findings: list[Finding]) -> list[AppliedFix]:
    applied: list[AppliedFix] = []
    index = TargetIndex(soup)
    for finding in findings:
        if finding.code != "contrast.aa_fail":
            continue
        tag = index.take(finding.target)
        if tag is None:
            continue
        style = resolve_style(tag, sheet)
        fg = style.color or DEFAULT_FG
        bg = style.background or DEFAULT_BG
        target_ratio = required_ratio(style.font_size_px, style.bold, "AA")
        new_fg = nearest_compliant(fg, bg, target_ratio)
        if new_fg == fg:
            continue
        _set_inline(tag, "color", to_hex(new_fg))
        applied.append(AppliedFix(
            finding.code, finding.target,
            f"color {to_hex(fg)} -> {to_hex(new_fg)} "
            f"({contrast_ratio(fg, bg):.2f}:1 -> {contrast_ratio(new_fg, bg):.2f}:1)",
        ))
    return applied


def fix_dark_mode(soup: BeautifulSoup, sheet: Stylesheet, findings: list[Finding]) -> list[AppliedFix]:
    """Pin the background the creator already sees in light mode.

    Making it explicit is the whole fix: clients that force dark mode leave
    declared backgrounds alone, so the text keeps the canvas it was designed for.
    """
    applied: list[AppliedFix] = []
    index = TargetIndex(soup)
    for finding in findings:
        if finding.code != "darkmode.no_bg_override":
            continue
        tag = index.take(finding.target)
        if tag is None:
            continue
        style = resolve_style(tag, sheet)
        bg = style.background or DEFAULT_BG
        _set_inline(tag, "background-color", to_hex(bg))
        applied.append(AppliedFix(finding.code, finding.target,
                                  f"pinned background-color: {to_hex(bg)}"))
    return applied


def _alt_from_context(img) -> str:
    """Derive alt text from surrounding copy, then the filename, then a
    neutral fallback. Deliberately boring - a wrong description is worse than
    a plain one, and the creator can edit it."""
    for sibling in list(img.parents)[:3]:
        heading = sibling.find(["h1", "h2", "h3"]) if hasattr(sibling, "find") else None
        if heading:
            text = _LIQUID_RE.sub("", heading.get_text(" ", strip=True)).strip()
            if text:
                return text[:100]
    link = img.find_parent("a")
    if link is not None:
        text = _LIQUID_RE.sub("", link.get_text(" ", strip=True)).strip()
        if text:
            return text[:100]
    src = (img.get("src") or "").split("?")[0].rsplit("/", 1)[-1]
    stem = re.sub(r"\.(png|jpe?g|gif|webp|svg)$", "", src, flags=re.I)
    words = [w for w in _SLUG_RE.split(stem) if w and not w.isdigit()]
    if words:
        return " ".join(words).strip().capitalize()
    return "Newsletter image"


def fix_alt_text(soup: BeautifulSoup, findings: list[Finding]) -> list[AppliedFix]:
    applied: list[AppliedFix] = []
    index = TargetIndex(soup, "img")
    for finding in findings:
        if finding.code not in ("img.missing_alt", "img.filename_alt"):
            continue
        img = index.take(finding.target)
        if img is None:
            continue
        alt = _alt_from_context(img)
        img["alt"] = alt
        applied.append(AppliedFix(finding.code, finding.target, f'alt="{alt}"'))
    return applied


def fix_bare_urls(soup: BeautifulSoup,
                  findings: list[Finding] | None = None) -> list[AppliedFix]:
    """Wrap raw URLs in anchors, splitting only the text node that contains them.

    Findings-aware, unlike its first version. It used to rewrite every bare URL
    in the document regardless of what it was asked to repair, which is fine for
    a batch fix and wrong for a surgical one: a creator who asks to fix one link
    must not have four others rewritten underneath them (D34).

    `findings is None` keeps the old whole-document behaviour for callers that
    genuinely mean "all of them".
    """
    wanted: set[str] | None = None
    if findings is not None:
        wanted = {f.evidence.get("url", "") for f in findings
                  if f.code == "link.bare_url"}
        if not wanted:
            return []
    applied: list[AppliedFix] = []
    for node in list(soup.find_all(string=_BARE_URL_RE)):
        if node.find_parent("a") or node.find_parent(["style", "script"]):
            continue
        text = str(node)
        pieces: list = []
        cursor = 0
        for match in _BARE_URL_RE.finditer(text):
            if match.start() > cursor:
                pieces.append(NavigableString(text[cursor:match.start()]))
            url = match.group(0)
            if wanted is not None and url not in wanted:
                pieces.append(NavigableString(url))   # leave this one alone
                cursor = match.end()
                continue
            anchor = soup.new_tag("a", href=url)
            anchor.string = url
            pieces.append(anchor)
            cursor = match.end()
            applied.append(AppliedFix("link.bare_url", url, "wrapped in <a href>"))
        if not pieces:
            continue
        if cursor < len(text):
            pieces.append(NavigableString(text[cursor:]))
        node.replace_with(*pieces)
    return applied


def apply_selected(
    html: str, findings: list[Finding], keys: set[tuple[str, str]] | None = None,
    aggressive: bool = False,
) -> tuple[str, list[AppliedFix]]:
    """Apply only the findings whose `key` is in `keys`.

    The whole per-finding control suite rests on this. The UI holds the
    *original* document plus a set of accepted keys and recomputes from scratch
    on every change, rather than mutating in place and keeping an undo stack.
    Undo is then set-removal, which is correct by construction: there is no
    ordering between fixes to get wrong, and un-picking one repair cannot
    disturb another (D34).

    `keys is None` means "everything", which is the batch button.
    """
    chosen = findings if keys is None else [f for f in findings if f.key in keys]
    return apply_fixes(html, chosen, aggressive=aggressive)


def apply_fixes(
    html: str, findings: list[Finding], aggressive: bool = False
) -> tuple[str, list[AppliedFix]]:
    """Return (fixed_html, applied). `findings` come from a prior audit."""
    soup, sheet = load(html)
    applied: list[AppliedFix] = []
    applied += fix_contrast(soup, sheet, findings)
    applied += fix_dark_mode(soup, sheet, findings)
    applied += fix_alt_text(soup, findings)
    applied += fix_bare_urls(soup, findings)
    if aggressive:
        applied += _fix_dark_mode_block(soup, sheet, findings)
    return serialize(soup, html), applied


def _fix_dark_mode_block(soup: BeautifulSoup, sheet: Stylesheet, findings: list[Finding]) -> list[AppliedFix]:
    """Aggressive: append a dark-mode block that pairs every recolor with a
    background. Touches the creator's <style>, so it is opt-in."""
    targets = {f.target for f in findings if f.code == "darkmode.unsafe_override"}
    if not targets:
        return []
    index = TargetIndex(soup)
    rules = []
    for target in sorted(targets):
        tag = index.take(target)
        if tag is None:
            continue
        selector = f"#{tag['id']}" if tag.get("id") else tag.name
        rules.append(f"  {selector} {{ background-color: #1a1a1a !important; color: #f5f5f5 !important; }}")
    if not rules:
        return []
    block = "\n@media (prefers-color-scheme: dark) {\n" + "\n".join(rules) + "\n}\n"
    style_tag = soup.find("style")
    if style_tag is None:
        style_tag = soup.new_tag("style")
        (soup.head or soup).append(style_tag)
    style_tag.append(block)
    return [AppliedFix("darkmode.unsafe_override", t, "paired dark-mode bg + color") for t in sorted(targets)]


def fixed_path(path: str | Path) -> Path:
    p = Path(path)
    return p.with_name(f"fixed_{p.name}")


def liquid_tokens(html: str) -> list[str]:
    """Used by tests and by `fix` itself to assert the non-destructive contract."""
    return _LIQUID_RE.findall(html)


async def fix_document(
    html: str,
    *,
    max_passes: int = 3,
    aggressive: bool = False,
    offline_links: dict | None = None,
) -> tuple[str, list[AppliedFix], "object"]:
    """Audit -> fix -> re-audit until the fixable findings stop changing.

    One pass is not enough: darkening low-contrast text can push it into the
    dark-mode risk band, and pinning a background changes the contrast pair.
    Converging (capped at `max_passes`) is what makes "1-click" honest, and the
    final re-audit is the receipt we print instead of asking for trust.
    """
    from ..audit import audit_html  # local import - fixer sits above audit

    applied: list[AppliedFix] = []
    current = html
    report = await audit_html(current, offline_links=offline_links, skip_llm=True)
    for _ in range(max_passes):
        fixable = [f for f in report.findings if (f.fixable if aggressive else f.fixable_now)]
        if not fixable:
            break
        current, new_fixes = apply_fixes(current, report.findings, aggressive=aggressive)
        if not new_fixes:
            break
        applied.extend(new_fixes)
        report = await audit_html(current, offline_links=offline_links, skip_llm=True)
    return current, applied, report
