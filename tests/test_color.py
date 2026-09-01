"""WCAG math. These are the numbers everything else is built on, so they are
pinned against values from the specification and the WebAIM checker."""

import pytest

from preflight.color import (
    contrast_ratio,
    is_large_text,
    nearest_compliant,
    parse_color,
    relative_luminance,
    required_ratio,
    to_hex,
)


@pytest.mark.parametrize("value,expected", [
    ("#fff", (255, 255, 255)),
    ("#FFFFFF", (255, 255, 255)),
    ("#1a4f8b", (26, 79, 139)),
    ("rgb(10, 20, 30)", (10, 20, 30)),
    ("rgb(10 20 30)", (10, 20, 30)),
    ("rgba(10, 20, 30, 0.5)", (10, 20, 30)),
    ("white", (255, 255, 255)),
    ("  #AAA  ", (170, 170, 170)),
])
def test_parse_color(value, expected):
    assert parse_color(value) == expected


@pytest.mark.parametrize("value", [
    None, "", "transparent", "inherit", "currentColor",
    "rgba(0,0,0,0)", "#00000000", "not-a-color", "url(x.png)",
])
def test_parse_color_declines(value):
    assert parse_color(value) is None


def test_luminance_endpoints():
    assert relative_luminance((0, 0, 0)) == 0.0
    assert relative_luminance((255, 255, 255)) == pytest.approx(1.0)


def test_contrast_extremes_and_symmetry():
    assert contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert contrast_ratio((255, 255, 255), (0, 0, 0)) == pytest.approx(21.0)
    assert contrast_ratio((128, 128, 128), (128, 128, 128)) == pytest.approx(1.0)


@pytest.mark.parametrize("fg,bg,expected", [
    ("#767676", "#ffffff", 4.54),   # the canonical AA-boundary grey
    ("#aaaaaa", "#ffffff", 2.32),
    ("#1a4f8b", "#ffffff", 8.28),
])
def test_known_contrast_ratios(fg, bg, expected):
    assert contrast_ratio(parse_color(fg), parse_color(bg)) == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("size,bold,large", [
    (16, False, False), (16, True, False), (19, True, True),
    (24, False, True), (23.9, False, False), (18.66, True, True),
])
def test_large_text_thresholds(size, bold, large):
    assert is_large_text(size, bold) is large


def test_required_ratio_levels():
    assert required_ratio(16, False, "AA") == 4.5
    assert required_ratio(30, False, "AA") == 3.0
    assert required_ratio(16, False, "AAA") == 7.0
    assert required_ratio(30, False, "AAA") == 4.5


def test_nearest_compliant_reaches_target_on_light_bg():
    fixed = nearest_compliant((170, 170, 170), (255, 255, 255), 4.5)
    assert contrast_ratio(fixed, (255, 255, 255)) >= 4.5
    assert to_hex(fixed) == "#767676"


def test_nearest_compliant_lightens_on_dark_bg():
    fixed = nearest_compliant((60, 60, 60), (17, 17, 17), 4.5)
    assert contrast_ratio(fixed, (17, 17, 17)) >= 4.5
    assert sum(fixed) > 60 * 3, "should have moved toward white, not black"


def test_nearest_compliant_is_minimal():
    """A fix that overshoots to pure black is a fix creators revert."""
    bg = (255, 255, 255)
    fixed = nearest_compliant((170, 170, 170), bg, 4.5)
    assert contrast_ratio(fixed, bg) < 5.2, "moved further than necessary"
    assert fixed != (0, 0, 0)


def test_nearest_compliant_leaves_passing_colors_alone():
    passing = (17, 17, 17)
    assert nearest_compliant(passing, (255, 255, 255), 4.5) == passing


def test_nearest_compliant_preserves_hue_direction():
    """Brand colors should stay recognizably themselves."""
    fixed = nearest_compliant((120, 180, 255), (255, 255, 255), 4.5)
    r, g, b = fixed
    assert b > g > r, "blue should still be the dominant channel"
