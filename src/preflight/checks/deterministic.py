"""Module A - the deterministic inspection engine.

Architectural rule: anything decidable by arithmetic or parsing is decided
here, before any token is spent. This module is pure (no network, no LLM) so
it is fully unit-testable and runs in single-digit milliseconds.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..color import (
    contrast_ratio,
    is_large_text,
    nearest_compliant,
    parse_color,
    required_ratio,
    to_hex,
)
from ..models import Finding, Severity
from ..parser import (
    SKIP_TAGS,
    TEXT_TAGS,
    Stylesheet,
    element_path,
    resolve_style,
    visible_text,
)

DEFAULT_FG = (0, 0, 0)
DEFAULT_BG = (255, 255, 255)

#: The background a dark-mode client paints when the creator gave it nothing to
#: respect. Gmail, Outlook and Apple Mail all land within a few points of this.
#: Simulating the actual repaint beats a magic "is this color dark" threshold:
#: the question is not whether text is dark, it is whether it survives.
FORCED_DARK_BG = (0x1A, 0x1A, 0x1A)

#: Backgrounds a dark-mode client feels free to repaint. Anything else is a
#: container the creator painted deliberately and clients generally respect.
REPAINTABLE_BG_SOURCES = ("", "body", "html")

_BARE_URL_RE = re.compile(r"(?<![\"'=>])\bhttps?://[^\s<>\"')\]]+", re.I)
_FILENAME_ALT_RE = re.compile(r"^[\w\-. ]+\.(png|jpe?g|gif|webp|svg)$", re.I)
_LIQUID_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)


def _text_elements(soup: BeautifulSoup) -> list[Tag]:
    out = []
    for tag in soup.find_all(TEXT_TAGS):
        if tag.name in SKIP_TAGS:
            continue
        if visible_text(tag):
            out.append(tag)
    return out


def check_contrast(soup: BeautifulSoup, sheet: Stylesheet) -> list[Finding]:
    """WCAG 2.1 contrast for every text element against its painted background.

    AA failures are errors. AAA shortfalls are INFO only - they are a polish
    signal, and charging a creator a score penalty for missing AAA would make
    the readiness number cry wolf.
    """
    findings: list[Finding] = []
    for tag in _text_elements(soup):
        style = resolve_style(tag, sheet)
        fg = style.color or DEFAULT_FG
        bg = style.background or DEFAULT_BG
        ratio = contrast_ratio(fg, bg)
        aa = required_ratio(style.font_size_px, style.bold, "AA")
        aaa = required_ratio(style.font_size_px, style.bold, "AAA")
        large = is_large_text(style.font_size_px, style.bold)
        evidence = {
            "foreground": to_hex(fg),
            "background": to_hex(bg),
            "ratio": round(ratio, 2),
            "required": aa,
            "large_text": large,
            "font_size_px": round(style.font_size_px, 1),
            "suggested_foreground": to_hex(nearest_compliant(fg, bg, aa)),
        }
        if ratio < aa:
            findings.append(Finding(
                code="contrast.aa_fail",
                severity=Severity.WILL_EMBARRASS,
                target=element_path(tag),
                line=tag.sourceline,
                message=(
                    "This text is too light to read comfortably - readers on "
                    "phones, in sunlight, or with tired eyes will skip it."
                ),
                detail=(
                    f"{to_hex(fg)} on {to_hex(bg)} is {ratio:.2f}:1. WCAG AA "
                    f"requires {aa}:1 at this size and weight."
                ),
                remedy=f"Darken it to {evidence['suggested_foreground']} - the closest "
                       f"shade to your own that reads cleanly.",
                evidence=evidence,
                fixable=True,
            ))
        elif ratio < aaa:
            findings.append(Finding(
                code="contrast.aaa_fail",
                severity=Severity.COULD_BE_BETTER,
                target=element_path(tag),
                line=tag.sourceline,
                message="Readable, but it could be crisper.",
                detail=f"{ratio:.2f}:1 clears AA ({aa}:1) and misses AAA ({aaa}:1). "
                       f"AAA is a stretch target, not a requirement.",
                remedy=f"Optional: {to_hex(nearest_compliant(fg, bg, aaa))} would reach AAA.",
                evidence=evidence,
            ))
    return findings


def check_dark_mode(soup: BeautifulSoup, sheet: Stylesheet) -> list[Finding]:
    """Simulate an OS/client dark-mode switch and find text that disappears.

    Two distinct bugs, deliberately given distinct codes because the fixes
    differ: text with no container background of its own (the client repaints
    behind it), and an explicit dark-mode rule that recolors text without
    recoloring what it sits on.
    """
    findings: list[Finding] = []
    # `has_own_color` alone missed a whole shape of document. A list that sets
    # `color` on the <ul> and lets its <li>s inherit it was invisible twice over:
    # the <ul> has no direct text of its own to check, and the <li>s have no
    # colour of their own. The repair then pinned backgrounds on the links inside
    # while leaving the item text black on black - the exact failure this check
    # exists to catch, surviving inside its own fix.
    #
    # So an element also qualifies when it *inherits* an authored colour that
    # disappears and no ancestor is already being flagged for it: somebody has to
    # own the repair, and it should be the outermost element holding the text.
    #
    # `light.color is not None` is the load-bearing half. Text the creator never
    # coloured is not at risk: a client that repaints the background recolours
    # that text along with it. Only a colour somebody pinned survives the
    # repaint and lands on the new background - which is why dropping this
    # condition flagged a plain uncoloured link as disappearing.
    flagged: set[int] = set()

    def inherits_an_unflagged_failure(tag: Tag) -> bool:
        return not any(id(parent) in flagged for parent in tag.parents)

    for tag in _text_elements(soup):
        light = resolve_style(tag, sheet)
        fg = light.color or DEFAULT_FG
        forced_ratio = contrast_ratio(fg, FORCED_DARK_BG)
        need_forced = required_ratio(light.font_size_px, light.bold, "AA")
        survives_repaint = forced_ratio >= need_forced
        unpainted = light.background_source in REPAINTABLE_BG_SOURCES
        owns_the_failure = light.has_own_color or (
            light.color is not None and inherits_an_unflagged_failure(tag)
        )

        if not survives_repaint and unpainted and owns_the_failure:
            flagged.add(id(tag))
            findings.append(Finding(
                code="darkmode.no_bg_override",
                severity=Severity.WILL_EMBARRASS,
                target=element_path(tag),
                line=tag.sourceline,
                message=(
                    "This disappears in dark mode. Roughly half your readers open "
                    "email on a dark screen, and they will see a blank space here."
                ),
                detail=(
                    f"The text is {to_hex(fg)}, but nothing between it and the mail "
                    f"client paints a background - so the client repaints it dark and "
                    f"the text lands at {forced_ratio:.2f}:1 on {to_hex(FORCED_DARK_BG)}."
                ),
                remedy="Pin the background colour you already see in light mode, so the "
                       "client leaves it alone.",
                evidence={
                    "foreground": to_hex(fg),
                    "background_source": light.background_source or "none",
                    "forced_dark_ratio": round(forced_ratio, 2),
                    "required": need_forced,
                },
                fixable=True,
            ))

        if sheet.has_dark_mode_block:
            dark = resolve_style(tag, sheet, dark=True)
            d_fg = dark.color or DEFAULT_FG
            d_bg = dark.background or DEFAULT_BG
            changed = (d_fg != fg) or (dark.background != light.background)
            ratio = contrast_ratio(d_fg, d_bg)
            need = required_ratio(dark.font_size_px, dark.bold, "AA")
            if changed and ratio < need:
                findings.append(Finding(
                    code="darkmode.unsafe_override",
                    severity=Severity.WILL_EMBARRASS,
                    target=element_path(tag),
                    line=tag.sourceline,
                    message=(
                        "Your dark-mode styling recolours this text but not what it "
                        "sits on, so it comes out light-on-light and unreadable."
                    ),
                    detail=(
                        f"In dark mode this resolves to {to_hex(d_fg)} on "
                        f"{to_hex(d_bg)} - {ratio:.2f}:1, against {need}:1 required."
                    ),
                    remedy="Set a background colour alongside the text colour in your "
                           "dark-mode block.",
                    evidence={
                        "dark_foreground": to_hex(d_fg),
                        "dark_background": to_hex(d_bg),
                        "ratio": round(ratio, 2),
                        "required": need,
                    },
                    fixable=True,
                    # Only `fix --aggressive` repairs this: the override has to
                    # go in the creator's stylesheet, and the default fix does
                    # not touch it. Advertising it in the one-click button and
                    # then skipping it is the promise this flag exists to keep.
                    requires_aggressive=True,
                ))
    return findings


def _describe_src(src: str) -> str:
    """How an image is named back to the creator.

    A truncated data: URI is 48 characters of percent-encoding that identifies
    nothing - it tells them less than saying the image is inline. Remote sources
    are still shown, because the filename is how they find it in the document.
    """
    if src.startswith("data:"):
        return src.split(";", 1)[0].split(",", 1)[0] or "data:"
    return src[:48]


def check_images(soup: BeautifulSoup) -> list[Finding]:
    findings: list[Finding] = []
    for img in soup.find_all("img"):
        alt = img.get("alt")
        target = element_path(img)
        src = img.get("src", "")
        if alt is None or not str(alt).strip():
            findings.append(Finding(
                code="img.missing_alt",
                severity=Severity.WILL_EMBARRASS,
                target=target,
                line=img.sourceline,
                message="This image has no description, so it is invisible to anyone "
                        "using a screen reader - and a blank gap for anyone whose "
                       "client blocks images, which many do by default.",
                detail=f"<img src=\"{_describe_src(src)}\"> has no alt attribute.",
                remedy="Describe what the image shows, in the voice of the email.",
                evidence={"src": src},
                fixable=True,
            ))
        elif _FILENAME_ALT_RE.match(str(alt).strip()):
            findings.append(Finding(
                code="img.filename_alt",
                severity=Severity.WILL_EMBARRASS,
                target=target,
                line=img.sourceline,
                message="The image description is just its filename, which tells a "
                        "reader nothing.",
                detail=f'alt="{alt}" looks like a filename rather than a description.',
                remedy="Replace it with a sentence describing what the image shows.",
                evidence={"alt": alt, "src": src},
                fixable=True,
            ))
    return findings


#: An opening Liquid delimiter. Wren merge tags and logic both start this way.
_LIQUID_OPEN = re.compile(r"\{\{|\{%")
#: A complete, well-formed tag.
#:
#: The interior may not contain `{`, `}` or `<`. Without that restriction an
#: unclosed `{{` matches all the way to the next `}}` anywhere in the document,
#: so one broken tag is silently rescued by the next correct one further down -
#: and the check reports a clean file. No real Liquid tag in a broadcast spans
#: an HTML element or nests another tag, so this costs nothing and closes the
#: hole.
_LIQUID_WHOLE = re.compile(r"\{\{[^{}<]*\}\}|\{%[^{}<]*%\}")
#: Block tags that must be closed. Wren's Liquid subset, not the full language.
_LIQUID_BLOCKS = ("if", "unless", "for", "case", "capture")


def check_liquid(soup: BeautifulSoup, html: str) -> list[Finding]:
    """Liquid that will reach a subscriber as literal text.

    The worst failure in this whole tool's remit, and the cheapest to detect.
    An unclosed `{{` does not error anywhere - it renders as `{{ subscriber.`
    in someone's inbox, and the creator finds out from a reply. Wren's own merge
    tags are the most common thing in a broadcast, so this is checked on the raw
    source rather than the parsed tree: by the time BeautifulSoup is done, a
    broken tag is indistinguishable from prose.
    """
    findings: list[Finding] = []
    whole = _LIQUID_WHOLE.findall(html)
    remainder = _LIQUID_WHOLE.sub("", html)

    for match in _LIQUID_OPEN.finditer(remainder):
        line = remainder.count("\n", 0, match.start()) + 1
        snippet = remainder[match.start():match.start() + 40].split("\n")[0]
        findings.append(Finding(
            code="liquid.unparsed",
            severity=Severity.WILL_BREAK,
            target=f"line {line}",
            line=line,
            message=(
                "This personalisation tag was never closed, so subscribers will see "
                "the raw code instead of their own name."
            ),
            detail=f"Unclosed Liquid near {snippet.strip()!r}.",
            remedy="Close the tag - `}}` for a merge field, `%}` for logic.",
            evidence={"snippet": snippet.strip()},
            # Never auto-fixed. Guessing where a tag was meant to close is
            # guessing at the creator's intent, and D5 says we do not.
            fixable=False,
        ))

    open_blocks: list[str] = []
    for tag in whole:
        inner = tag.strip("{}%").strip()
        head = inner.split()[0] if inner.split() else ""
        if head in _LIQUID_BLOCKS:
            open_blocks.append(head)
        elif head.startswith("end") and open_blocks and head[3:] == open_blocks[-1]:
            open_blocks.pop()
    for name in open_blocks:
        findings.append(Finding(
            code="liquid.unclosed_block",
            severity=Severity.WILL_BREAK,
            target=f"{{% {name} %}}",
            message=(
                f"A `{name}` block was opened and never closed. Depending on the "
                f"sending engine, everything after it may vanish or come out as raw code."
            ),
            detail=f"`{{% {name} %}}` has no matching `{{% end{name} %}}`.",
            remedy=f"Add `{{% end{name} %}}`.",
            evidence={"block": name},
            fixable=False,
        ))
    return findings


#: What an iPhone shows before it cuts the subject off. Conservative: the exact
#: number moves with device and font size, so this flags well past the edge
#: rather than nagging anyone sitting near it.
SUBJECT_VISIBLE_CHARS = 41

#: Link text that tells a reader nothing about where they are going.
VAGUE_LINK_TEXT = {
    "click here", "here", "read more", "learn more", "more", "this",
    "this link", "link", "find out more", "see more", "download", "go",
}


def check_envelope(subject: str = "", preheader: str = "") -> list[Finding]:
    """The two lines a subscriber reads before deciding to open at all.

    These are not in the HTML. They live beside it in the composer, which is why
    the engine takes them as an envelope rather than digging them out of the
    document - and why a file audited from disk simply skips them (D36).
    """
    findings: list[Finding] = []
    subject = (subject or "").strip()
    preheader = (preheader or "").strip()

    if subject and len(subject) > SUBJECT_VISIBLE_CHARS:
        findings.append(Finding(
            code="subject.too_long",
            severity=Severity.COULD_BE_BETTER,
            target="subject",
            message=(
                "Your subject line will be cut off on a phone, where most people "
                "read it. The part that decides whether they open may never be seen."
            ),
            detail=f"{len(subject)} characters; roughly {SUBJECT_VISIBLE_CHARS} "
                   f"show before an iPhone truncates.",
            remedy=f"Put the point in the first {SUBJECT_VISIBLE_CHARS} characters.",
            evidence={"length": len(subject), "visible": SUBJECT_VISIBLE_CHARS,
                      "subject": subject[:80]},
        ))

    if subject and not preheader:
        findings.append(Finding(
            code="preheader.missing",
            severity=Severity.COULD_BE_BETTER,
            target="preheader",
            message=(
                "There is no preview text, so inboxes will fill that space with "
                "whatever your email happens to start with - often an unsubscribe "
                "line or a stray image."
            ),
            detail="No preheader was supplied alongside the subject.",
            remedy="Write one line that earns the open, separate from the subject.",
            evidence={"subject": subject[:80]},
        ))
    return findings


def check_link_text(soup: BeautifulSoup) -> list[Finding]:
    """Links whose words carry none of the promise.

    "Click here" makes the reader work out where they are going from the
    sentence around it, and reads as nothing at all to anyone using a screen
    reader moving link to link.
    """
    findings: list[Finding] = []
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href.startswith("http"):
            continue
        text = a.get_text(" ", strip=True).lower().rstrip(".!?›»→ ")
        if text and text in VAGUE_LINK_TEXT:
            findings.append(Finding(
                code="link.vague_text",
                severity=Severity.COULD_BE_BETTER,
                target=element_path(a),
                line=a.sourceline,
                message=(
                    f"\"{a.get_text(' ', strip=True)}\" does not tell anyone where "
                    f"it goes. Readers skimming - and anyone using a screen reader - "
                    f"get nothing from it."
                ),
                detail=f"Link text: {a.get_text(' ', strip=True)!r}",
                remedy="Name the destination: what will they find when they arrive?",
                evidence={"text": a.get_text(" ", strip=True), "href": href[:80]},
            ))
    return findings


def check_link_hygiene(soup: BeautifulSoup) -> list[Finding]:
    """Structural link problems - the ones decidable without a network call."""
    findings: list[Finding] = []
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href or href in ("#", "javascript:void(0)"):
            findings.append(Finding(
                code="link.empty_href",
                severity=Severity.WILL_BREAK,
                target=element_path(a),
                line=a.sourceline,
                message=f"The link \"{a.get_text(strip=True)[:40]}\" does not go anywhere. "
                        f"Readers will click it and nothing will happen.",
                detail=f'href="{href}"',
                remedy="Point it at the real destination before sending.",
                evidence={"href": href},
            ))
    for node in soup.find_all(string=_BARE_URL_RE):
        if node.find_parent("a") or node.find_parent(["style", "script"]):
            continue
        for url in _BARE_URL_RE.findall(str(node)):
            parent = node.parent if isinstance(node.parent, Tag) else None
            findings.append(Finding(
                code="link.bare_url",
                severity=Severity.COULD_BE_BETTER,
                target=element_path(parent) if parent else url,
                line=parent.sourceline if parent else None,
                message="This address is written out but not clickable, so readers "
                        "have to copy and paste it. Some clients will not turn it "
                        "into a link on their own.",
                detail=f"Bare URL: {url[:60]}",
                remedy="Make it a link with descriptive text.",
                evidence={"url": url},
                fixable=True,
            ))
    return findings


def check_deliverability_math(soup: BeautifulSoup) -> list[Finding]:
    """Text-to-link and text-to-image ratios.

    These are arithmetic, so they belong here and not in the LLM module even
    though they are deliverability signals - the LLM receives the computed
    numbers as evidence rather than recounting them.
    """
    findings: list[Finding] = []
    text = _LIQUID_RE.sub("", soup.get_text(" ", strip=True))
    words = len(text.split())
    links = [a for a in soup.find_all("a") if (a.get("href") or "").startswith("http")]
    images = soup.find_all("img")

    if len(links) >= 5 and words and words / len(links) < 25:
        findings.append(Finding(
            code="spam.link_ratio",
            severity=Severity.WILL_EMBARRASS,
            target="document",
            line=None,
            message=(
                "There are a lot of links and not much writing between them. Spam "
                "filters read that as promotional, and this may land in Promotions "
                "or never arrive."
            ),
            detail=f"{len(links)} links across {words} words "
                   f"({words / len(links):.0f} words per link).",
            remedy="Cut the secondary links, or add substance between them.",
            evidence={"links": len(links), "words": words},
        ))
    if len(images) >= 2 and words < 40:
        findings.append(Finding(
            code="deliverability.image_heavy",
            severity=Severity.WILL_EMBARRASS,
            target="document",
            line=None,
            message="This is mostly pictures with very little writing. Filters treat "
                    "that as a spam signature, and readers who block images will see "
                    "an almost empty email.",
            detail=f"{len(images)} images against {words} words of copy.",
            remedy="Add real text so the email still reads with images turned off.",
            evidence={"images": len(images), "words": words},
        ))
    return findings


def document_stats(soup: BeautifulSoup, sheet: Stylesheet) -> dict:
    text = _LIQUID_RE.sub("", soup.get_text(" ", strip=True))
    return {
        "words": len(text.split()),
        "links": len(soup.find_all("a")),
        "images": len(soup.find_all("img")),
        "text_elements": len(_text_elements(soup)),
        "css_rules": len(sheet.rules),
        "has_dark_mode_block": sheet.has_dark_mode_block,
    }


def run_all(soup: BeautifulSoup, sheet: Stylesheet, html: str = "",
            subject: str = "", preheader: str = "") -> list[Finding]:
    """Every offline check, in report order.

    `html` is the raw source. Liquid is checked there rather than on the parsed
    tree, because a broken tag survives parsing as ordinary text.

    `subject` and `preheader` are the envelope. They are absent when auditing a
    file from disk, and their checks simply do not fire.
    """
    return [
        *check_envelope(subject, preheader),
        *check_liquid(soup, html),
        *check_link_text(soup),
        *check_contrast(soup, sheet),
        *check_dark_mode(soup, sheet),
        *check_images(soup),
        *check_link_hygiene(soup),
        *check_deliverability_math(soup),
    ]
