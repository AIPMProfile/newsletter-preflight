"""Module A behaviour, including the cases it must stay quiet about."""

import pytest

from preflight.checks.deterministic import (
    FORCED_DARK_BG,
    check_contrast,
    check_dark_mode,
    check_deliverability_math,
    check_images,
    check_link_hygiene,
    document_stats,
    run_all,
)
from preflight.models import Severity
from preflight.parser import load

PAINTED = '<td id="canvas" bgcolor="#ffffff" style="background-color:#ffffff">{}</td>'


def codes(findings):
    return sorted(f.code for f in findings)


def run(html, fn=run_all):
    soup, sheet = load(html)
    return fn(soup, sheet) if fn is not run_all else run_all(soup, sheet)


def test_contrast_failure_is_flagged_with_a_usable_suggestion():
    soup, sheet = load(PAINTED.format('<p id="t" style="color:#aaaaaa">hello there</p>'))
    found = check_contrast(soup, sheet)
    assert [f.code for f in found] == ["contrast.aa_fail"]
    assert found[0].evidence["ratio"] == pytest.approx(2.32, abs=0.01)
    assert found[0].evidence["suggested_foreground"] == "#767676"
    assert found[0].fixable is True


def test_passing_contrast_is_silent():
    soup, sheet = load(PAINTED.format('<p id="t" style="color:#111111">hello there</p>'))
    assert check_contrast(soup, sheet) == []


def test_large_text_uses_the_three_to_one_threshold():
    """#949494 on white is 3.03:1 - a failure at 16px, a pass at 30px."""
    small = PAINTED.format('<p id="t" style="color:#949494;font-size:16px">hello</p>')
    large = PAINTED.format('<p id="t" style="color:#949494;font-size:30px">hello</p>')
    assert codes(check_contrast(*load(small))) == ["contrast.aa_fail"]
    assert "contrast.aa_fail" not in codes(check_contrast(*load(large)))


def test_aaa_shortfall_is_info_only_and_never_scored():
    soup, sheet = load(PAINTED.format('<p id="t" style="color:#767676">hello there</p>'))
    found = check_contrast(soup, sheet)
    assert [f.code for f in found] == ["contrast.aaa_fail"]
    assert found[0].severity is Severity.COULD_BE_BETTER
    assert found[0].scored is False


def test_unpainted_dark_text_is_flagged_for_dark_mode():
    soup, sheet = load('<body><p id="t" style="color:#222222">hello</p></body>')
    found = check_dark_mode(soup, sheet)
    assert codes(found) == ["darkmode.no_bg_override"]
    assert found[0].evidence["forced_dark_ratio"] < 4.5


def test_painted_container_protects_dark_text():
    soup, sheet = load(PAINTED.format('<p id="t" style="color:#222222">hello</p>'))
    assert check_dark_mode(soup, sheet) == []


def test_light_text_survives_a_forced_repaint_and_is_not_flagged():
    """The check asks whether text survives the repaint, not whether it is dark."""
    soup, sheet = load('<body><p id="t" style="color:#dddddd">hello</p></body>')
    assert check_dark_mode(soup, sheet) == []


def test_dark_mode_rule_without_a_background_is_flagged():
    html = ('<style>.c{color:#222222}'
            '@media (prefers-color-scheme: dark){.c{color:#f0f0f0}}</style>'
            + PAINTED.format('<p id="t" class="c">hello</p>'))
    soup, sheet = load(html)
    found = check_dark_mode(soup, sheet)
    assert codes(found) == ["darkmode.unsafe_override"]
    assert found[0].evidence["dark_background"] == "#ffffff"


def test_dark_mode_rule_that_repaints_both_is_silent():
    html = ('<style>.c{color:#222222;background-color:#ffffff}'
            '@media (prefers-color-scheme: dark){.c{color:#f0f0f0;background-color:#111111}}</style>'
            + PAINTED.format('<p id="t" class="c">hello</p>'))
    soup, sheet = load(html)
    assert check_dark_mode(soup, sheet) == []


def test_forced_dark_background_constant_is_actually_dark():
    from preflight.color import relative_luminance
    assert relative_luminance(FORCED_DARK_BG) < 0.05


@pytest.mark.parametrize("tag,expected", [
    ('<img src="a.png">', ["img.missing_alt"]),
    ('<img src="a.png" alt="">', ["img.missing_alt"]),
    ('<img src="a.png" alt="   ">', ["img.missing_alt"]),
    ('<img src="a.png" alt="hero-shot.png">', ["img.filename_alt"]),
    ('<img src="a.png" alt="A desk with a notebook">', []),
])
def test_image_alt_rules(tag, expected):
    soup, _ = load(tag)
    assert codes(check_images(soup)) == expected


@pytest.mark.parametrize("html,expected", [
    ('<a href="#">x</a>', ["link.empty_href"]),
    ('<a href="">x</a>', ["link.empty_href"]),
    ('<a href="https://wren.email">x</a>', []),
    ('<p>see https://wren.email/x now</p>', ["link.bare_url"]),
    ('<p><a href="https://wren.email/x">https://wren.email/x</a></p>', []),
])
def test_link_hygiene(html, expected):
    soup, _ = load(html)
    assert codes(check_link_hygiene(soup)) == expected


def test_link_ratio_needs_both_density_and_volume():
    dense = "".join(f'<a href="https://k.co/{i}">l{i}</a> ' for i in range(6))
    soup, _ = load(f"<body><p>short copy {dense}</p></body>")
    assert "spam.link_ratio" in codes(check_deliverability_math(soup))

    few = "".join(f'<a href="https://k.co/{i}">l{i}</a> ' for i in range(3))
    soup, _ = load(f"<body><p>short copy {few}</p></body>")
    assert "spam.link_ratio" not in codes(check_deliverability_math(soup))


def test_image_heavy_needs_thin_copy():
    soup, _ = load("<body><img src=a.png><img src=b.png><p>two words</p></body>")
    assert "deliverability.image_heavy" in codes(check_deliverability_math(soup))

    words = " ".join(["word"] * 60)
    soup, _ = load(f"<body><img src=a.png><img src=b.png><p>{words}</p></body>")
    assert "deliverability.image_heavy" not in codes(check_deliverability_math(soup))


def test_document_stats_excludes_liquid_from_the_word_count():
    soup, sheet = load("<body><p>one two {{ subscriber.first_name }}</p></body>")
    assert document_stats(soup, sheet)["words"] == 2


def test_findings_carry_source_lines():
    html = "<body>\n<p style='color:#aaaaaa'>hello there friend</p>\n</body>"
    soup, sheet = load(html)
    assert run_all(soup, sheet)[0].line == 2


def test_engine_is_silent_on_the_clean_control(corpus):
    soup, sheet = load((corpus / "sample_6_clean.html").read_text())
    scored = [f for f in run_all(soup, sheet) if f.scored]
    assert scored == [], f"false positives on the clean control: {codes(scored)}"


# --- the envelope and link text (D36) -------------------------------------

def test_a_subject_that_survives_a_phone_is_not_flagged():
    from preflight.checks.deterministic import check_envelope
    codes = {f.code for f in check_envelope("Three things I learned", "A short preview")}
    assert codes == set()


def test_a_long_subject_is_flagged_for_truncation():
    from preflight.checks.deterministic import check_envelope
    long = "A subject line that is comfortably past what any phone will show a reader"
    codes = {f.code for f in check_envelope(long, "preview")}
    assert "subject.too_long" in codes


def test_a_missing_preheader_is_flagged():
    from preflight.checks.deterministic import check_envelope
    codes = {f.code for f in check_envelope("Short subject", "")}
    assert "preheader.missing" in codes


def test_no_envelope_means_no_envelope_findings():
    """A file audited from disk has no subject, and inventing one would be
    worse than skipping the check."""
    from preflight.checks.deterministic import check_envelope
    assert check_envelope("", "") == []


def test_vague_link_text_is_flagged_and_named_links_are_not():
    from preflight.checks.deterministic import check_link_text
    from preflight.parser import load
    soup, _ = load('<p><a href="https://k.co/a">Click here</a> '
                   '<a href="https://k.co/b">the pricing teardown</a></p>')
    found = check_link_text(soup)
    assert len(found) == 1
    assert "Click here" in found[0].message


def test_link_text_check_ignores_anchors_without_a_web_target():
    from preflight.checks.deterministic import check_link_text
    from preflight.parser import load
    soup, _ = load('<p><a href="#top">here</a></p>')
    assert check_link_text(soup) == []
