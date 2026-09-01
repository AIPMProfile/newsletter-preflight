"""WCAG 2.1 color math. Pure functions, no I/O - this is the hot path.

Relative luminance:  L = 0.2126R + 0.7152G + 0.0722B  (linearized channels)
Contrast ratio:      (L_lighter + 0.05) / (L_darker + 0.05)
"""

from __future__ import annotations

import re

RGB = tuple[int, int, int]

AA_NORMAL = 4.5
AA_LARGE = 3.0
AAA_NORMAL = 7.0
AAA_LARGE = 4.5

#: Named colors that actually show up in email templates. Not the full CSS list -
#: an unknown name returns None and the check declines to guess.
NAMED_COLORS: dict[str, RGB] = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "navy": (0, 0, 128),
    "teal": (0, 128, 128), "purple": (128, 0, 128), "orange": (255, 165, 0),
    "yellow": (255, 255, 0), "maroon": (128, 0, 0), "lime": (0, 255, 0),
    "aqua": (0, 255, 255), "fuchsia": (255, 0, 255), "olive": (128, 128, 0),
    "whitesmoke": (245, 245, 245), "lightgray": (211, 211, 211),
    "lightgrey": (211, 211, 211), "darkgray": (169, 169, 169),
    "darkgrey": (169, 169, 169), "dimgray": (105, 105, 105),
}

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_FUNC_RE = re.compile(r"^rgba?\(([^)]*)\)$", re.I)


def parse_color(value: str | None) -> RGB | None:
    """Parse a CSS color into 8-bit RGB. Returns None for transparent/unknown.

    Fully transparent colors return None so callers fall through to the parent
    background rather than compositing against nothing.
    """
    if not value:
        return None
    v = value.strip().lower()
    if v in ("transparent", "inherit", "initial", "unset", "none", "currentcolor"):
        return None
    if v in NAMED_COLORS:
        return NAMED_COLORS[v]
    if _HEX_RE.match(v):
        h = v[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        if len(h) == 8 and int(h[6:8], 16) == 0:
            return None
        return (r, g, b)
    m = _FUNC_RE.match(v)
    if m:
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(1)) if p.strip()]
        if len(parts) >= 3:
            try:
                chan = [_to_channel(p) for p in parts[:3]]
            except ValueError:
                return None
            if len(parts) >= 4 and _alpha(parts[3]) == 0.0:
                return None
            return (chan[0], chan[1], chan[2])
    return None


def _to_channel(part: str) -> int:
    if part.endswith("%"):
        return _clamp8(round(float(part[:-1]) * 255 / 100))
    return _clamp8(round(float(part)))


def _alpha(part: str) -> float:
    if part.endswith("%"):
        return float(part[:-1]) / 100
    return float(part)


def _clamp8(n: int) -> int:
    return max(0, min(255, n))


def to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _linearize(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: RGB) -> float:
    r, g, b = (_linearize(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: RGB, bg: RGB) -> float:
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def is_large_text(font_size_px: float, bold: bool) -> bool:
    """WCAG large text: >=18.66px (14pt) bold, or >=24px (18pt) regular."""
    return font_size_px >= 24.0 or (bold and font_size_px >= 18.66)


def required_ratio(font_size_px: float, bold: bool, level: str = "AA") -> float:
    large = is_large_text(font_size_px, bold)
    if level == "AAA":
        return AAA_LARGE if large else AAA_NORMAL
    return AA_LARGE if large else AA_NORMAL


def nearest_compliant(fg: RGB, bg: RGB, target: float) -> RGB:
    """Darken or lighten `fg` the minimum amount that reaches `target` on `bg`.

    Keeps hue and saturation by scaling toward black or white in sRGB, so a
    brand color stays recognizably itself. Direction is chosen by whichever
    endpoint the background is *not* near, and we binary-search the smallest
    shift - a fix that overshoots to pure black is a fix creators revert.
    """
    if contrast_ratio(fg, bg) >= target:
        return fg
    bg_lum = relative_luminance(bg)
    anchor: RGB = (0, 0, 0) if bg_lum > 0.18 else (255, 255, 255)
    if contrast_ratio(anchor, bg) < target:
        # Background is mid-gray: neither endpoint works. Take the better one.
        alt: RGB = (255, 255, 255) if anchor == (0, 0, 0) else (0, 0, 0)
        anchor = alt if contrast_ratio(alt, bg) > contrast_ratio(anchor, bg) else anchor
        return anchor
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        cand = _mix(fg, anchor, mid)
        if contrast_ratio(cand, bg) >= target:
            hi = mid
        else:
            lo = mid
    return _mix(fg, anchor, hi)


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(_clamp8(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]
