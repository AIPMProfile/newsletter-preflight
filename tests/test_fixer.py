"""Module C. The non-destructive contract is the thing under test."""

import pytest

from preflight.audit import audit_html
from preflight.fixer.autofix import (
    apply_fixes,
    fix_document,
    fixed_path,
    liquid_tokens,
)
from preflight.parser import load, resolve_style

LIQUID = ("<body><p id='t' style='color:#aaaaaa'>Hi {{ subscriber.first_name }}, "
          "{% if subscriber.tags contains \"vip\" %}welcome back{% endif %}</p></body>")


async def _audit(html):
    return await audit_html(html, skip_llm=True)


async def test_contrast_fix_reaches_aa():
    html = "<body style='background-color:#ffffff'><p id='t' style='color:#aaaaaa'>hello there</p></body>"
    report = await _audit(html)
    fixed, applied = apply_fixes(html, report.findings)
    assert any(a.code == "contrast.aa_fail" for a in applied)
    soup, sheet = load(fixed)
    style = resolve_style(soup.find(id="t"), sheet)
    from preflight.color import contrast_ratio
    assert contrast_ratio(style.color, style.background) >= 4.5


async def test_fix_never_touches_liquid():
    report = await _audit(LIQUID)
    fixed, _ = apply_fixes(LIQUID, report.findings)
    assert liquid_tokens(fixed) == liquid_tokens(LIQUID)
    assert "{{ subscriber.first_name }}" in fixed
    assert '{% if subscriber.tags contains "vip" %}' in fixed


async def test_fix_writes_inline_overrides_not_stylesheet_edits():
    """Creator CSS is theirs. We add an override; we do not rewrite their rules."""
    html = ("<style>.muted{color:#aaaaaa}</style><body style='background-color:#ffffff'>"
            "<p id='t' class='muted'>hello there</p></body>")
    report = await _audit(html)
    fixed, _ = apply_fixes(html, report.findings)
    assert ".muted{color:#aaaaaa}" in fixed, "stylesheet was modified"
    assert "color: #767676" in fixed


async def test_dark_mode_fix_pins_the_light_mode_background():
    html = "<body style='background-color:#ffffff'><p id='t' style='color:#222222'>hello</p></body>"
    report = await _audit(html)
    fixed, applied = apply_fixes(html, report.findings)
    assert any(a.code == "darkmode.no_bg_override" for a in applied)
    assert "background-color: #ffffff" in fixed


async def test_alt_text_comes_from_surrounding_context():
    html = "<body><div><h2>Spring launch notes</h2><img id='i' src='hero-1.png'></div></body>"
    report = await _audit(html)
    fixed, _ = apply_fixes(html, report.findings)
    assert load(fixed)[0].find(id="i")["alt"] == "Spring launch notes"


async def test_alt_text_falls_back_to_the_filename():
    html = "<body><img id='i' src='https://cdn.wren.email/spring-launch-hero.png?v=2'></body>"
    report = await _audit(html)
    fixed, _ = apply_fixes(html, report.findings)
    assert load(fixed)[0].find(id="i")["alt"] == "Spring launch hero"


async def test_bare_urls_are_wrapped_without_losing_surrounding_copy():
    html = "<body><p id='t'>Read it at https://wren.email/x today.</p></body>"
    report = await _audit(html)
    fixed, _ = apply_fixes(html, report.findings)
    soup, _ = load(fixed)
    p = soup.find(id="t")
    assert p.find("a")["href"] == "https://wren.email/x"
    assert "Read it at" in p.get_text() and "today." in p.get_text()


async def test_layout_markup_survives_the_fixer():
    html = ("<body><table role='presentation' width='600'><tr>"
            "<td align='center' style='padding:32px'>"
            "<p id='t' style='color:#aaaaaa'>hello there</p></td></tr></table></body>")
    fixed, _, _ = await fix_document(html)
    soup, _ = load(fixed)
    td = soup.find("td")
    assert td["align"] == "center" and "padding:32px" in td["style"]
    assert soup.find("table")["width"] == "600"


async def test_convergence_resolves_fixes_that_create_new_findings():
    """Darkening text can push it into the dark-mode risk band - one pass is a lie."""
    html = "<body style='background-color:#ffffff'><p id='t' style='color:#aaaaaa'>hello there</p></body>"
    fixed, applied, report = await fix_document(html)
    assert [f for f in report.findings if f.fixable] == []
    assert {a.code for a in applied} == {"contrast.aa_fail", "darkmode.no_bg_override"}


async def test_fix_is_idempotent():
    html = "<body style='background-color:#ffffff'><p id='t' style='color:#aaaaaa'>hello there</p></body>"
    once, _, _ = await fix_document(html)
    twice, applied, _ = await fix_document(once)
    assert applied == []
    assert once == twice


async def test_broken_links_are_left_for_a_human():
    """We can detect a dead link; guessing its replacement is not our call."""
    html = "<body><a id='a' href='https://x.test/404'>gone</a></body>"
    report = await audit_html(html, offline_links={"https://x.test/404": 404}, skip_llm=True)
    _, applied = apply_fixes(html, report.findings)
    assert applied == []


async def test_aggressive_mode_is_required_to_touch_the_stylesheet():
    html = ("<style>.c{color:#222222}@media (prefers-color-scheme: dark){.c{color:#f0f0f0}}</style>"
            "<body style='background-color:#ffffff'><p id='t' class='c'>hello</p></body>")
    report = await _audit(html)
    conservative, _ = apply_fixes(html, report.findings, aggressive=False)
    assert conservative.count("@media") == 1
    bold, applied = apply_fixes(html, report.findings, aggressive=True)
    assert bold.count("@media") == 2
    assert any(a.code == "darkmode.unsafe_override" for a in applied)


@pytest.mark.parametrize("given,expected", [
    ("email.html", "fixed_email.html"),
    ("/a/b/newsletter.html", "/a/b/fixed_newsletter.html"),
])
def test_output_naming(given, expected):
    assert str(fixed_path(given)) == expected


async def test_the_mixed_sample_improves_and_keeps_its_liquid(corpus, ground_truth):
    source = (corpus / "sample_5_mixed.html").read_text()
    before = await audit_html(source, offline_links=ground_truth["link_status"], skip_llm=True)
    fixed, applied, after = await fix_document(
        source, offline_links=ground_truth["link_status"]
    )
    assert before.verdict == "HOLD"
    assert len(after.blocking_findings) < len(before.blocking_findings)
    assert liquid_tokens(fixed) == liquid_tokens(source)
    assert {f.code for f in after.findings if f.scored} == {"link.broken"}


async def test_serialization_keeps_the_diff_minimal():
    """Attribute order, void-tag style, and the doctype line survive untouched."""
    html = ('<!doctype html>\n<body><img id="hero" src="a.png" width="5">'
            '<p id="t" style="color:#aaaaaa">hello there</p></body>')
    report = await _audit(html)
    fixed, _ = apply_fixes(html, report.findings)
    assert fixed.startswith("<!doctype html>")
    assert '<img id="hero" src="a.png" width="5" alt=' in fixed
    assert "/>" not in fixed


async def test_unfixable_document_round_trips_unchanged():
    html = ('<!doctype html>\n<html><body><td bgcolor="#ffffff">'
            '<p id="t" style="color:#111111">hello there</p></td></body></html>')
    report = await _audit(html)
    fixed, applied = apply_fixes(html, report.findings)
    assert applied == []
    assert fixed == html


async def test_documented_serialization_limit_is_indentation_only():
    """Round-trip changes whitespace-only indentation and nothing else."""
    html = ('<html>\n<head>\n  <meta charset="utf-8">\n</head>\n'
            '<body>\n  <td bgcolor="#ffffff">\n    <p id="t" style="color:#111111">hi there</p>\n'
            "  </td>\n</body>\n</html>")
    report = await _audit(html)
    fixed, applied = apply_fixes(html, report.findings)
    assert applied == []
    assert "".join(fixed.split()) == "".join(html.split()), "content changed, not just whitespace"


# --- surgical repair (D34) ------------------------------------------------

@pytest.mark.asyncio
async def test_fixing_one_finding_leaves_the_others_alone(corpus, ground_truth):
    from preflight.fixer.autofix import apply_selected
    source = (corpus / "sample_5_mixed.html").read_text()
    report = await audit_html(source, offline_links=ground_truth["link_status"], skip_llm=True)
    fixable = [f for f in report.findings if f.fixable_now]
    target = fixable[0]

    out, applied = apply_selected(source, report.findings, {target.key})
    assert len(applied) == 1

    after = await audit_html(out, offline_links=ground_truth["link_status"], skip_llm=True)
    still = {f.key for f in after.findings}
    assert target.key not in still
    assert all(f.key in still for f in fixable[1:]), "a repair leaked onto another element"


@pytest.mark.asyncio
async def test_undoing_one_repair_keeps_the_rest(corpus, ground_truth):
    """The reason state is `original + accepted set` rather than a history
    stack: un-picking one repair cannot disturb another, because every result
    is derived from the untouched draft (D34)."""
    from preflight.fixer.autofix import apply_selected
    source = (corpus / "sample_5_mixed.html").read_text()
    report = await audit_html(source, offline_links=ground_truth["link_status"], skip_llm=True)
    three = [f for f in report.findings if f.fixable_now][:3]

    kept = {f.key for f in three} - {three[1].key}
    out, _ = apply_selected(source, report.findings, kept)
    after = await audit_html(out, offline_links=ground_truth["link_status"], skip_llm=True)
    still = {f.key for f in after.findings}

    assert three[1].key in still, "the undone repair did not come back"
    assert three[0].key not in still and three[2].key not in still


def test_bare_url_repair_touches_only_the_url_it_was_asked_about():
    """It used to rewrite every bare URL in the document regardless of the
    findings it was given, which is wrong for a single-element repair."""
    from preflight.fixer.autofix import fix_bare_urls
    from preflight.models import Finding, Severity
    from preflight.parser import load

    html = "<p>See https://a.example/one and https://b.example/two</p>"
    soup, _ = load(html)
    only = Finding(code="link.bare_url", severity=Severity.COULD_BE_BETTER,
                   target="p", message="m", evidence={"url": "https://a.example/one"})
    applied = fix_bare_urls(soup, [only])
    out = str(soup)
    assert len(applied) == 1
    assert '<a href="https://a.example/one">' in out
    assert '<a href="https://b.example/two">' not in out


def test_elements_sharing_a_path_are_each_repaired_once():
    """Twenty thumbnails at the same `div>a>img` path is normal in real mail.

    A `{path: tag}` dict collapsed them, so the fixer edited one image once per
    finding and reported twenty repairs it had not made (D37).
    """
    from preflight.fixer.autofix import apply_fixes
    from preflight.models import Finding, Severity
    from preflight.parser import element_path, load

    html = ("<div>" + "".join(f'<a><img src="t{i}.png"></a>' for i in range(5)) + "</div>")
    soup, _ = load(html)
    path = element_path(soup.find("img"))
    findings = [Finding(code="img.missing_alt", severity=Severity.WILL_EMBARRASS,
                        target=path, message="m", fixable=True) for _ in range(5)]

    out, applied = apply_fixes(html, findings)
    assert len(applied) == 5
    assert out.count("alt=") == 5, "some images were left without alt text"
