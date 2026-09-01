"""Module D (part 1) - the synthetic benchmark corpus.

Every sample is written to isolate one failure mode, with a deliberate
*passing* control inside the same file. That structure is what lets the harness
separate "the check works" from "the check fires at everything".

Ground truth is authored from intent - what a careful human reviewer would flag
in this file - and is not derived from the agent's output. When the agent and
this table disagree, one of them has a bug; the harness exists to say which.
"""

from __future__ import annotations

import json
from pathlib import Path

SAMPLES_DIR = Path(__file__).parent / "samples"
GROUND_TRUTH_PATH = Path(__file__).parent / "ground_truth.json"

BROKEN_404 = "https://wren-preflight-fixture.invalid/deleted-post"
BROKEN_500 = "https://wren-preflight-fixture.invalid/boom"
GOOD_LINK = "https://wren.email/creator-guide"

SAMPLES: dict[str, str] = {}

SAMPLES["sample_1_contrast.html"] = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { margin: 0; background-color: #f4f4f4; font-family: Helvetica, Arial, sans-serif; }
    .wrap { width: 600px; margin: 0 auto; }
    .muted { color: #8a8a8a; font-size: 15px; }
  </style>
</head>
<body>
  <table class="wrap" role="presentation"><tr>
    <td id="canvas" bgcolor="#ffffff" style="padding: 32px;">
      <h1 id="headline" style="color: #999999; font-size: 28px; font-weight: bold;">This week in your inbox</h1>
      <p id="good-copy" style="color: #333333; font-size: 16px;">
        Hi {{ subscriber.first_name }}, three things worth your attention today.
      </p>
      <p id="intro" class="muted">
        We spent the week talking to creators about what actually moves a launch.
      </p>
      <p id="footer-note" style="color: #bbbbbb; font-size: 12px;">
        You are receiving this because you subscribed at wren.email.
      </p>
      <p><a id="cta" href="__GOOD__" style="color: #1a4f8b; font-size: 16px;">Read the full guide</a></p>
      <img id="sig" src="signature.png" alt="Handwritten signature reading Anusha" width="140">
    </td>
  </tr></table>
</body>
</html>
"""

SAMPLES["sample_2_darkmode.html"] = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="light dark">
  <style>
    .card { color: #222222; font-size: 16px; }
    .wrap { width: 600px; margin: 0 auto; font-family: Georgia, serif; }
    @media (prefers-color-scheme: dark) {
      /* Recolors the text but never repaints what it sits on. */
      .card { color: #f0f0f0; }
    }
  </style>
</head>
<body>
  <table class="wrap" role="presentation"><tr>
    <td style="padding: 28px;">
      <h2 id="title" style="color: #101010; font-size: 24px;">Notes from the studio</h2>
      <p id="card-copy" class="card">
        The dark-mode rule below flips this text light without giving it a surface.
      </p>
      <p id="orphan-copy" style="color: #222222; font-size: 16px;">
        This paragraph never declares a background of its own.
      </p>
    </td>
  </tr></table>
  <table class="wrap" role="presentation"><tr>
    <td id="safe-cell" bgcolor="#ffffff" style="padding: 28px; background-color: #ffffff;">
      <p id="safe-copy" style="color: #222222; font-size: 16px;">
        This one pins its own surface, so a forced dark mode leaves it alone.
      </p>
      <p><a id="cta" href="__GOOD__" style="color: #14477d;">See the full notes</a></p>
    </td>
  </tr></table>
</body>
</html>
"""

SAMPLES["sample_3_links_assets.html"] = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style> .wrap { width: 600px; margin: 0 auto; font-family: Helvetica, Arial, sans-serif; } </style>
</head>
<body>
  <table class="wrap" role="presentation"><tr>
    <td id="canvas" bgcolor="#ffffff" style="padding: 32px; background-color: #ffffff;">
      <h2 id="title" style="color: #1a1a1a; font-size: 24px;">Three links, one of them fine</h2>
      <img id="hero" src="hero-launch.png" width="520">
      <p id="body" style="color: #2d2d2d; font-size: 16px;">
        Last week's post is <a id="dead-link" href="__404__">still up over here</a>,
        and the archive lives <a id="server-error" href="__500__">in the vault</a>.
      </p>
      <p id="raw-url" style="color: #2d2d2d; font-size: 16px;">
        Prefer the plain version? https://wren.email/plain-text-archive
      </p>
      <p><a id="empty-link" href="#" style="color: #14477d; font-size: 16px;">Manage your preferences</a></p>
      <p><a id="good-link" href="__GOOD__" style="color: #14477d; font-size: 16px;">Read the creator guide</a></p>
      <img id="badge" src="badge-icon.png" alt="badge-icon.png" width="80">
      <img id="logo" src="wren-logo.png" alt="Wren logo" width="60">
    </td>
  </tr></table>
</body>
</html>
"""

SAMPLES["sample_4_cta_spam.html"] = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style> .wrap { width: 600px; margin: 0 auto; font-family: Helvetica, Arial, sans-serif; } </style>
</head>
<body>
  <table class="wrap" role="presentation"><tr>
    <td id="canvas" bgcolor="#ffffff" style="padding: 32px; background-color: #ffffff;">
      <h1 id="headline" style="color: #1a1a1a; font-size: 30px;">ACT NOW!!! 100% FREE MONEY GUARANTEED</h1>
      <p id="p1" style="color: #2d2d2d; font-size: 16px;">
        Hi {{ subscriber.first_name }}, this is a RISK-FREE, no-obligation, once-in-a-lifetime
        opportunity and you will not believe what happens next. Limited time only. Act fast.
      </p>
      <p id="p2" style="color: #2d2d2d; font-size: 16px;">
        Before I tell you about the offer, let me tell you about my week. On Monday I woke up
        early and made coffee. On Tuesday I answered email for six hours straight, which is not
        something I recommend to anyone who values their attention span or their eyesight.
      </p>
      <p id="p3" style="color: #2d2d2d; font-size: 16px;">
        On Wednesday I rewrote the landing page four separate times and then reverted all of it.
        On Thursday I read three books about pricing and came away more confused than I started,
        which is roughly the standard outcome of reading three books about pricing in one day.
      </p>
      <p id="p4" style="color: #2d2d2d; font-size: 16px;">
        On Friday I finally sat down to write this email, and here we are, still not at the point.
        Anyway. There is a thing I would like you to do, and it is at the very bottom of this email,
        below the part where I thank you for reading this far, which you probably have not.
      </p>
      <p id="p5" style="color: #2d2d2d; font-size: 16px;">
        Thanks for reading this far. Truly. It means more than the analytics will ever show me.
      </p>
      <p><a id="cta-button" href="__GOOD__" style="color: #2d2d2d; font-size: 13px; text-decoration: underline;">click here now</a></p>
    </td>
  </tr></table>
</body>
</html>
"""

SAMPLES["sample_5_mixed.html"] = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    .wrap { width: 600px; margin: 0 auto; font-family: Helvetica, Arial, sans-serif; }
    .fine-print { color: #b4b4b4; font-size: 12px; }
    @media (prefers-color-scheme: dark) {
      .fine-print { color: #ededed; }
    }
  </style>
</head>
<body>
  <table class="wrap" role="presentation"><tr>
    <td style="padding: 32px;">
      <h1 id="headline" style="color: #1a1a1a; font-size: 30px;">The launch is live</h1>
      <img id="hero" src="launch-hero.png" width="520">
      <p id="lede" style="color: #9b9b9b; font-size: 16px;">
        Hi {{ subscriber.first_name }} - the thing I have been building for eight months is finally out.
      </p>
      <p id="body" style="color: #2b2b2b; font-size: 16px;">
        {% if subscriber.tags contains "early" %}You have had access for a week already.{% endif %}
        The full write-up is <a id="dead-link" href="__404__">on the blog</a>, and the changelog is
        <a id="server-error" href="__500__">here</a>.
      </p>
      <p id="raw-url" style="color: #2b2b2b; font-size: 16px;">
        Direct link, if you prefer: https://wren.email/launch-notes
      </p>
      <p id="disclaimer" class="fine-print">
        No refunds after 30 days. Prices shown exclude tax.
      </p>
      <p><a id="cta-button" href="__GOOD__" style="color: #7a7a7a; font-size: 13px;">maybe check it out</a></p>
    </td>
  </tr></table>
</body>
</html>
"""

SAMPLES["sample_6_clean.html"] = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="light dark">
  <style>
    body { margin: 0; background-color: #f4f4f4; font-family: Helvetica, Arial, sans-serif; }
    .wrap { width: 600px; margin: 0 auto; }
    .surface { background-color: #ffffff; color: #1f1f1f; }
    @media (prefers-color-scheme: dark) {
      .surface { background-color: #17181a; color: #f2f2f2; }
    }
  </style>
</head>
<body>
  <table class="wrap" role="presentation"><tr>
    <td id="canvas" class="surface" bgcolor="#ffffff" style="padding: 32px; background-color: #ffffff;">
      <h1 id="headline" style="color: #111111; font-size: 30px;">One idea, clearly stated</h1>
      <p id="lede" style="color: #1f1f1f; font-size: 17px; background-color: #ffffff;">
        Hi {{ subscriber.first_name }}, here is the single thing worth your time this week,
        and the one action I would like you to take after reading it.
      </p>
      <p id="cta-wrap" style="background-color: #ffffff;">
        <a id="cta-button" href="__GOOD__"
           style="background-color: #14477d; color: #ffffff; font-size: 17px; font-weight: bold; padding: 14px 28px; display: inline-block; text-decoration: none;">
          Read the creator guide
        </a>
      </p>
      <p id="body" style="color: #1f1f1f; font-size: 16px; background-color: #ffffff;">
        The guide covers pricing, positioning, and the three launch emails that do most of the work.
        It takes about nine minutes to read and you can skip straight to the templates at the end.
      </p>
      <img id="hero" src="creator-guide-cover.png" alt="Cover of the Wren creator guide, showing a desk and a notebook" width="520">
      <p id="signoff" style="color: #1f1f1f; font-size: 16px; background-color: #ffffff;">Thanks for reading. Reply any time - I read everything.</p>
      <p id="footer" style="color: #4a545e; font-size: 13px; background-color: #ffffff;">
        You subscribed at wren.email. <a id="unsub" href="__GOOD__" style="color: #14477d;">Unsubscribe</a>.
      </p>
    </td>
  </tr></table>
</body>
</html>
"""


#: Pinned HTTP statuses. Benchmark scores must measure the agent, not today's DNS.
LINK_STATUS: dict[str, int | str] = {
    BROKEN_404: 404,
    BROKEN_500: 500,
    GOOD_LINK: 200,
    "https://wren.email/plain-text-archive": 200,
    "https://wren.email/launch-notes": 200,
}

#: target "*" means "this code should fire somewhere in this file" - used for
#: LLM judgments, where which element carries the blame is genuinely arguable.
SAMPLES["sample_7_liquid.html"] = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    .wrap { width: 600px; margin: 0 auto; font-family: Helvetica, Arial, sans-serif; }
    .surface { background-color: #ffffff; color: #1f1f1f; }
    @media (prefers-color-scheme: dark) {
      .surface { background-color: #17181a; color: #f2f2f2; }
    }
  </style>
</head>
<body>
  <table class="wrap" role="presentation"><tr>
    <td id="canvas" class="surface" bgcolor="#ffffff" style="padding: 32px; background-color: #ffffff;">
      <h1 id="headline" style="color: #111111; font-size: 30px; background-color: #ffffff;">Your weekly digest</h1>
      <p id="good-merge" style="color: #1f1f1f; font-size: 17px; background-color: #ffffff;">
        Hi {{ subscriber.first_name }}, here is what shipped this week.
      </p>
      <p id="good-block" style="color: #1f1f1f; font-size: 17px; background-color: #ffffff;">
        {% if subscriber.tags contains "beta" %}You saw these first.{% endif %}
      </p>
      <p id="broken-merge" style="color: #1f1f1f; font-size: 17px; background-color: #ffffff;">
        Thanks again, {{ subscriber.first_name - that is the whole reason this exists.
      </p>
      <p id="broken-block" style="color: #1f1f1f; font-size: 17px; background-color: #ffffff;">
        {% if subscriber.tags contains "founding"
        Founding members get the archive too.
      </p>
      <p id="unclosed-loop" style="color: #1f1f1f; font-size: 17px; background-color: #ffffff;">
        {% for post in recent_posts %}{{ post.title }}
      </p>
      <p id="cta-wrap" style="background-color: #ffffff;">
        <a id="cta" href="__GOOD__"
           style="background-color: #14477d; color: #ffffff; font-size: 17px; font-weight: bold; padding: 14px 28px; display: inline-block; text-decoration: none;">Read the digest</a>
      </p>
    </td>
  </tr></table>
</body>
</html>
"""

SAMPLES["sample_8_envelope.html"] = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="light dark">
  <style>
    .wrap { width: 600px; margin: 0 auto; font-family: Helvetica, Arial, sans-serif; }
    .surface { background-color: #ffffff; color: #1f1f1f; }
    @media (prefers-color-scheme: dark) {
      .surface { background-color: #17181a; color: #f2f2f2; }
    }
  </style>
</head>
<body>
  <table class="wrap" role="presentation"><tr>
    <td id="canvas" class="surface" bgcolor="#ffffff" style="padding: 32px; background-color: #ffffff;">
      <h1 id="headline" style="color: #111111; font-size: 30px; background-color: #ffffff;">This week in the workshop</h1>
      <p id="lede" style="color: #1f1f1f; font-size: 17px; background-color: #ffffff;">
        Hi {{ subscriber.first_name }}, two things worth your time and one worth skipping.
      </p>
      <p id="vague-wrap" style="color: #1f1f1f; font-size: 17px; background-color: #ffffff;">
        The full breakdown is up now - <a id="vague-link" href="__GOOD__" style="color: #14477d;">click here</a>.
      </p>
      <p id="named-wrap" style="color: #1f1f1f; font-size: 17px; background-color: #ffffff;">
        Or jump straight to <a id="named-link" href="__GOOD__" style="color: #14477d;">the pricing teardown</a>.
      </p>
      <p id="cta-wrap" style="background-color: #ffffff;">
        <a id="cta" href="__GOOD__"
           style="background-color: #14477d; color: #ffffff; font-size: 17px; font-weight: bold; padding: 14px 28px; display: inline-block; text-decoration: none;">Read the teardown</a>
      </p>
    </td>
  </tr></table>
</body>
</html>
"""

GROUND_TRUTH: dict[str, dict] = {
    "sample_1_contrast.html": {
        "description": "Isolated WCAG contrast failures on a clean, well-formed layout.",
        "expected_verdict": "HOLD",
        "expected": [
            {"code": "contrast.aa_fail", "target": "headline", "severity": "will_embarrass"},
            {"code": "contrast.aa_fail", "target": "intro", "severity": "will_embarrass"},
            {"code": "contrast.aa_fail", "target": "footer-note", "severity": "will_embarrass"},
        ],
        # Named negative expectations. Unlike a bare false positive these are
        # checked against every finding, INFO included, and are cross-checked
        # against `expected` so ground truth cannot quietly contradict itself.
        "forbidden": [
            {"code": "contrast.aa_fail", "target": "good-copy", "severity": "will_embarrass"},
            {"code": "contrast.aa_fail", "target": "cta", "severity": "will_embarrass"},
            {"code": "img.missing_alt", "target": "sig", "severity": "will_embarrass"},
            {"code": "img.filename_alt", "target": "sig", "severity": "will_embarrass"},
        ],
        "controls": ["good-copy passes at 12.6:1", "cta passes", "sig has real alt text"],
    },
    "sample_2_darkmode.html": {
        "description": "Isolated dark-mode invisibility: unpainted surfaces and a recolor with no background.",
        "expected_verdict": "HOLD",
        "expected": [
            {"code": "darkmode.no_bg_override", "target": "title", "severity": "will_embarrass"},
            {"code": "darkmode.no_bg_override", "target": "card-copy", "severity": "will_embarrass"},
            {"code": "darkmode.no_bg_override", "target": "orphan-copy", "severity": "will_embarrass"},
            {"code": "darkmode.unsafe_override", "target": "card-copy", "severity": "will_embarrass"},
        ],
        "forbidden": [
            {"code": "darkmode.no_bg_override", "target": "safe-copy", "severity": "will_embarrass"},
            {"code": "darkmode.unsafe_override", "target": "safe-copy", "severity": "will_embarrass"},
        ],
        "controls": ["safe-copy pins its own surface and must not be flagged"],
    },
    "sample_3_links_assets.html": {
        "description": "Isolated link and asset hygiene: dead targets, dead-end href, bare URL, missing and lazy alt text, and an image-to-copy ratio filters punish.",
        "expected_verdict": "HOLD",
        "expected": [
            {"code": "link.broken", "target": "dead-link", "severity": "will_break"},
            {"code": "link.broken", "target": "server-error", "severity": "will_break"},
            {"code": "link.empty_href", "target": "empty-link", "severity": "will_break"},
            {"code": "link.bare_url", "target": "raw-url", "severity": "could_be_better"},
            {"code": "img.missing_alt", "target": "hero", "severity": "will_embarrass"},
            {"code": "img.filename_alt", "target": "badge", "severity": "will_embarrass"},
            {"code": "deliverability.image_heavy", "target": "document", "severity": "will_embarrass"},
        ],
        "forbidden": [
            {"code": "link.broken", "target": "good-link", "severity": "will_break"},
            {"code": "img.missing_alt", "target": "logo", "severity": "will_embarrass"},
            {"code": "img.filename_alt", "target": "logo", "severity": "will_embarrass"},
        ],
        "controls": ["good-link resolves 200", "logo has real alt text"],
    },
    "sample_4_cta_spam.html": {
        "description": "Buried CTA and spam-trigger copy. Deterministically clean by construction - this file scores Module B.",
        "expected_verdict": "HOLD",
        # No severity key on LLM entries: severity is the model's judgment, and
        # the fixture that supplies it is authored. Pinning it would score the
        # author against themselves. See D21.
        "expected": [
            {"code": "spam.trigger_phrase", "target": "*"},
            {"code": "spam.trigger_phrase", "target": "*"},
            {"code": "cta.buried", "target": "*"},
            {"code": "cta.weak_prominence", "target": "*"},
        ],
        # Wildcard target: this code must not appear anywhere in the sample.
        "forbidden": [
            {"code": "contrast.aa_fail", "target": "*", "severity": "will_embarrass"},
            {"code": "link.broken", "target": "*", "severity": "will_break"},
            {"code": "img.missing_alt", "target": "*", "severity": "will_embarrass"},
            {"code": "darkmode.no_bg_override", "target": "*", "severity": "will_embarrass"},
        ],
        "controls": ["contrast, links, and alt text are all correct here",
                     "two distinct spam-trigger locations: the headline and the first paragraph"],
    },
    "sample_5_mixed.html": {
        "description": "Multi-failure realistic send: contrast, dead links, dark-mode collapse, missing alt, weak CTA.",
        "expected_verdict": "HOLD",
        "expected": [
            {"code": "contrast.aa_fail", "target": "lede", "severity": "will_embarrass"},
            {"code": "contrast.aa_fail", "target": "disclaimer", "severity": "will_embarrass"},
            {"code": "contrast.aa_fail", "target": "cta-button", "severity": "will_embarrass"},
            {"code": "darkmode.no_bg_override", "target": "headline", "severity": "will_embarrass"},
            {"code": "darkmode.no_bg_override", "target": "body", "severity": "will_embarrass"},
            {"code": "darkmode.no_bg_override", "target": "raw-url", "severity": "will_embarrass"},
            {"code": "darkmode.no_bg_override", "target": "cta-button", "severity": "will_embarrass"},
            {"code": "darkmode.unsafe_override", "target": "disclaimer", "severity": "will_embarrass"},
            {"code": "link.broken", "target": "dead-link", "severity": "will_break"},
            {"code": "link.broken", "target": "server-error", "severity": "will_break"},
            {"code": "link.bare_url", "target": "raw-url", "severity": "could_be_better"},
            {"code": "img.missing_alt", "target": "hero", "severity": "will_embarrass"},
            {"code": "cta.weak_prominence", "target": "*"},
        ],
        "forbidden": [],
        "controls": ["Liquid tags in #body must survive the fixer untouched"],
    },
    "sample_7_liquid.html": {
        "description": "Liquid that reaches the inbox as literal text: an unclosed merge field and an unclosed block, beside two correct ones.",
        "expected_verdict": "HOLD",
        "expected": [
            {"code": "liquid.unparsed", "target": "line 24", "severity": "will_break"},
            {"code": "liquid.unparsed", "target": "line 27", "severity": "will_break"},
            {"code": "liquid.unclosed_block", "target": "{% for %}", "severity": "will_break"},
        ],
        "forbidden": [
            {"code": "contrast.aa_fail", "target": "*"},
            {"code": "darkmode.no_bg_override", "target": "*"},
            {"code": "link.broken", "target": "*"},
        ],
        "controls": ["good-merge and good-block are well-formed and must not be flagged",
                     "the unclosed {% for %} is not rescued by the correct tags above it",
                     "deterministically clean apart from the Liquid"],
    },
    "sample_8_envelope.html": {
        "description": "The lines a subscriber reads before opening, plus link text that promises nothing. Deterministically clean otherwise.",
        "expected_verdict": "REVIEW",
        "envelope": {
            "subject": "A few things I have been meaning to tell you about this week's workshop",
            "preheader": "",
        },
        "expected": [
            {"code": "subject.too_long", "target": "subject", "severity": "could_be_better"},
            {"code": "preheader.missing", "target": "preheader", "severity": "could_be_better"},
            {"code": "link.vague_text", "target": "vague-link", "severity": "could_be_better"},
        ],
        "forbidden": [
            {"code": "link.vague_text", "target": "named-link"},
            {"code": "link.vague_text", "target": "cta"},
            {"code": "contrast.aa_fail", "target": "*"},
            {"code": "darkmode.no_bg_override", "target": "*"},
            {"code": "link.broken", "target": "*"},
        ],
        "controls": ["named-link and cta both name their destination and must not be flagged",
                     "nothing here blocks a send - these are all advisory, so the verdict is REVIEW"],
    },
    "sample_6_clean.html": {
        "description": "Negative control. Any scored finding here is a false positive.",
        "expected_verdict": "READY",
        "expected": [],
        "forbidden": [
            {"code": "contrast.aa_fail", "target": "*", "severity": "will_embarrass"},
            {"code": "darkmode.no_bg_override", "target": "*", "severity": "will_embarrass"},
            {"code": "darkmode.unsafe_override", "target": "*", "severity": "will_embarrass"},
            {"code": "img.missing_alt", "target": "*", "severity": "will_embarrass"},
            {"code": "link.broken", "target": "*", "severity": "will_break"},
            {"code": "cta.weak_prominence", "target": "*"},
            {"code": "cta.buried", "target": "*"},
            {"code": "spam.trigger_phrase", "target": "*"},
        ],
        "controls": ["every surface painted", "dark-mode block pairs color with background",
                     "CTA is isolated, high-contrast, above the fold",
                     "footer clears AAA too, so READY is a reachable verdict and not a dead tier"],
    },
}


_TOKENS = {"__GOOD__": GOOD_LINK, "__404__": BROKEN_404, "__500__": BROKEN_500}


def render(html: str) -> str:
    """Samples embed Liquid, so they are token-substituted rather than
    %-formatted - `{% if %}` is indistinguishable from a format spec."""
    for token, value in _TOKENS.items():
        html = html.replace(token, value)
    return html


def write_all(samples_dir: Path = SAMPLES_DIR, truth_path: Path = GROUND_TRUTH_PATH) -> list[Path]:
    samples_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, html in SAMPLES.items():
        path = samples_dir / name
        path.write_text(render(html))
        written.append(path)
    payload = {
        "link_status": LINK_STATUS,
        "cases": GROUND_TRUTH,
    }
    truth_path.write_text(json.dumps(payload, indent=2) + "\n")
    written.append(truth_path)
    return written


def load_ground_truth(truth_path: Path = GROUND_TRUTH_PATH) -> dict:
    if not truth_path.exists():
        write_all()
    return json.loads(truth_path.read_text())
