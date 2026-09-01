import re
"""The HTTP surface. It must expose the engine faithfully and add nothing."""

import pytest
from fastapi.testclient import TestClient

from preflight.web import create_app


#: Hermetic audit: no model call, no link probing. Tests never hit the network.
OFFLINE = {"skip_llm": True, "check_links": False}


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


def test_root_is_the_pre_send_check(client):
    """`/` is the product, not the console.

    The console was what `/` opened for most of this project's life, which made
    every change to the actual check invisible to anyone who just ran `serve`.
    """
    r = client.get("/")
    assert r.status_code == 200
    assert "Review before sending" in r.text
    assert 'id="pbody"' in r.text            # the problem list
    assert "Dark screen" in r.text            # the failure most findings describe
    # Nothing may cache these: a stale page hid four rounds of changes.
    assert "no-store" in r.headers.get("cache-control", "")


def test_health_reports_the_reviewer_without_leaking_the_key(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["provider"] in ("gemini", "anthropic")
    assert isinstance(body["reviewer_enabled"], bool)
    assert not any("key" in str(v).lower() and len(str(v)) > 20 for v in body.values())
    assert "api_key" not in body


def test_audit_returns_the_same_findings_as_the_engine(client, corpus):
    html = (corpus / "sample_1_contrast.html").read_text()
    body = client.post("/api/audit", json=OFFLINE | {"html": html}).json()
    assert body["verdict"] == "HOLD"
    assert body["blocking"] == 3
    assert sorted(f["target"] for f in body["findings"]) == ["footer-note", "headline", "intro"]
    assert all(f["code"] == "contrast.aa_fail" for f in body["findings"])


def test_clean_sample_is_ready_over_http(client, corpus):
    html = (corpus / "sample_6_clean.html").read_text()
    body = client.post("/api/audit", json=OFFLINE | {"html": html}).json()
    assert body["verdict"] == "READY" and body["blocking"] == 0
    assert body["findings"] == []


def test_audit_payload_carries_timing_and_sla(client, corpus):
    html = (corpus / "sample_1_contrast.html").read_text()
    body = client.post("/api/audit", json=OFFLINE | {"html": html}).json()
    assert body["timing"]["within_sla"] is True
    assert body["timing"]["presend_ms"] >= 0
    assert body["sla_ms"] == 2000.0


@pytest.mark.parametrize("payload", [{"html": ""}, {"html": "   "}])
def test_empty_input_is_rejected(client, payload):
    assert client.post("/api/audit", json=payload).status_code == 400


def test_oversized_input_is_rejected(client):
    assert client.post("/api/audit", json={"html": "x" * 2_000_001}).status_code == 413


def test_link_checking_can_be_turned_off(client, corpus):
    """The slowest pre-send phase must be optional."""
    html = (corpus / "sample_3_links_assets.html").read_text()
    body = client.post("/api/audit", json=OFFLINE | {"html": html}).json()
    assert not any(f["code"] == "link.broken" for f in body["findings"])
    assert body["timing"]["links_ms"] < 100


def test_fix_returns_fixed_html_and_a_change_list(client, corpus):
    html = (corpus / "sample_1_contrast.html").read_text()
    body = client.post("/api/fix", json={"html": html, "check_links": False}).json()
    assert body["report"]["blocking"] == 0
    assert body["applied"], "expected at least one applied fix"
    assert "#767676" in body["fixed_html"]


def test_fix_preserves_liquid_over_http(client, corpus):
    html = (corpus / "sample_5_mixed.html").read_text()
    body = client.post("/api/fix", json={"html": html, "check_links": False}).json()
    assert "{{ subscriber.first_name }}" in body["fixed_html"]
    assert '{% if subscriber.tags contains "early" %}' in body["fixed_html"]


def test_samples_are_served_for_zero_setup_testing(client):
    r = client.get("/api/sample/sample_4_cta_spam")
    assert r.status_code == 200 and "ACT NOW" in r.text


@pytest.mark.parametrize("name", [
    "../../../../etc/passwd", "..%2f..%2fetc%2fpasswd", "nope", "../conftest",
])
def test_sample_endpoint_confines_paths(client, name):
    assert client.get(f"/api/sample/{name}").status_code in (404, 400)


def test_findings_carry_a_canvas_selector(client, corpus):
    html = (corpus / "sample_5_mixed.html").read_text()
    body = client.post("/api/audit", json=OFFLINE | {"html": html}).json()
    assert body["findings"], "expected findings to highlight"
    assert all(f["selector"] for f in body["findings"]), \
        "every finding must be locatable on the canvas"
    by_target = {f["target"]: f["selector"] for f in body["findings"]}
    assert by_target["lede"] == "#lede"


def test_selectors_survive_the_tbody_browsers_invent(client):
    """bs4 never sees <tbody>; browsers always insert one. Child combinators
    would silently match nothing in the live DOM, and every email is tables."""
    html = ("<body><table><tr><td><p id='a' style='color:#aaaaaa'>hello there</p></td>"
            "<td><p style='color:#aaaaaa'>second cell copy</p></td></tr></table></body>")
    body = client.post("/api/audit", json=OFFLINE | {"html": html}).json()
    selectors = [f["selector"] for f in body["findings"]]
    assert "#a" in selectors
    assert all(">" not in s for s in selectors), "child combinators break on tbody"
    assert any("nth-of-type" in s for s in selectors), "siblings must disambiguate"


# --- the pre-send gate ----------------------------------------------------

def test_publish_step_reports_the_check_but_does_not_repeat_it(client):
    """Publishing is not a second place to audit.

    This step used to re-run the whole check against the original draft, so it
    ignored every decision made at /review and displayed "Launch Check passed"
    directly above "20 things to sort". One document checked by two screens is
    how they end up contradicting each other, so the check lives at /review and
    this step reports its outcome and publishes.
    """
    page = client.get("/publish").text
    assert "Publish Broadcast" in page
    assert 'id="outcome"' in page                  # what the review step decided
    # None of the repair controls belong here any more.
    for gone in ("Fix it for me", "Review it myself", "Send as is",
                 'id="tiers"', 'id="fixall"'):
        assert gone not in page, f"{gone!r} is still on the publish step"


def test_applying_a_repair_that_surfaces_another_still_carries_it_out(client, corpus):
    """Darkening pale text for readability can make it newly fail on a dark
    screen. That finding does not exist in the first look at the draft, so a
    single pass would accept a repair for it and quietly do nothing (D34)."""
    html = (corpus / "sample_5_mixed.html").read_text()
    first = client.post("/api/audit", json=OFFLINE | {"html": html}).json()
    keys = [[f["code"], f["target"]] for f in first["findings"] if f["fixable_now"]]

    seen = {tuple(k) for k in keys}
    for _ in range(3):
        body = client.post("/api/apply", json={"html": html, "keys": [list(k) for k in seen],
                                               "check_links": False}).json()
        fresh = {(f["code"], f["target"]) for f in body["report"]["findings"] if f["fixable_now"]}
        if fresh <= seen:
            break
        seen |= fresh

    assert body["report"]["blocking"] == 0, body["report"]["findings"]


def test_undoing_one_repair_over_the_api_keeps_the_others(client, corpus):
    html = (corpus / "sample_5_mixed.html").read_text()
    first = client.post("/api/audit", json=OFFLINE | {"html": html}).json()
    keys = [(f["code"], f["target"]) for f in first["findings"] if f["fixable_now"]]
    assert len(keys) > 2

    dropped = keys[0]
    body = client.post("/api/apply", json={"html": html,
                                           "keys": [list(k) for k in keys[1:]],
                                           "check_links": False}).json()
    still = {(f["code"], f["target"]) for f in body["report"]["findings"]}
    assert dropped in still, "the repair we left out did not come back"
    assert not (still & set(keys[1:])), "leaving one out disturbed the others"


def test_previewing_a_repair_commits_nothing(client, corpus):
    html = (corpus / "sample_1_contrast.html").read_text()
    first = client.post("/api/audit", json=OFFLINE | {"html": html}).json()
    f = next(x for x in first["findings"] if x["fixable_now"])
    body = client.post("/api/preview", json={"html": html, "key": [f["code"], f["target"]],
                                             "check_links": False}).json()
    assert body["before"] == html
    assert body["after"] != html
    assert body["changed"] is True

def test_review_sandboxes_the_broadcast_it_renders(client):
    """The check renders the creator's email, and must never let it run.

    This was briefly rendered inline - which fixed scrolling, because an overlay
    of positioned boxes was swallowing the wheel, but silently gave up the
    sandbox. The overlay is gone for good; the frame is not. Marking happens on
    the elements inside it, which needs `allow-same-origin` and works precisely
    because `allow-scripts` is absent: a document that cannot script cannot lift
    its own sandbox.
    """
    page = client.get("/").text
    sandbox = re.search(r'<iframe[^>]*\bsandbox="([^"]*)"', page)
    assert sandbox, "the broadcast frame must declare a sandbox"
    tokens = sandbox.group(1).split()
    assert "allow-same-origin" in tokens
    assert "allow-scripts" not in tokens
    # No overlay may return: a layer above the frame is what broke scrolling.
    assert 'id="ov"' not in page

def test_the_check_names_every_code_the_engine_can_emit(client):
    """The list must not advertise a category nothing produces, or hide one.

    This invariant outlived the console it was written against: a check added to
    the engine with no creator-facing name would show a raw code like
    `darkmode.no_bg_override` in the panel, and a stale name would advertise a
    finding that can never appear.
    """
    import re
    from pathlib import Path as P
    from typing import get_args

    import preflight.checks.deterministic as det
    import preflight.checks.links as links
    from preflight.checks.llm_eval import LLMCode

    page = client.get("/launch-check").text
    block = page.split("const TITLES = {")[1].split("};")[0]
    titled = set(re.findall(r"'([a-z]+\.[a-z_]+)':", block))

    # Derived from the engine source, not restated here, so a renamed or new
    # check fails loudly instead of drifting.
    source = "".join(P(m.__file__).read_text() for m in (det, links))
    engine = set(re.findall(r'code="([a-z]+\.[a-z_]+)"', source)) | set(get_args(LLMCode))

    assert titled <= engine, f"the check invents codes: {sorted(titled - engine)}"
    assert engine <= titled, f"no creator-facing name for: {sorted(engine - titled)}"


def test_issue_names_are_in_a_creator_s_words(client):
    """Not `darkmode.no_bg_override`, and not WCAG jargon either."""
    page = client.get("/launch-check").text
    for label in ("Disappears in dark mode", "Text too light to read",
                  "Image has no description", "Broken link", "No preview text"):
        assert label in page

def test_a_repair_does_not_lose_the_envelope_findings(client, corpus):
    """Subject and preview text are not in the document, so every audit has to
    be told them - including the one that runs after a repair.

    It was not. A creator pressed Fix all and watched "No preview text"
    disappear without being fixed: the re-audit no longer knew there was a
    subject line to have a preview for. A finding dropped for a plumbing reason
    is worse than one we never made, because the creator believes it is handled.
    """
    html = (corpus / "sample_1_contrast.html").read_text()
    envelope = {"subject": "A subject long enough to be real", "preheader": ""}

    before = client.post("/api/audit", json=OFFLINE | {"html": html} | envelope).json()
    assert any(f["code"] == "preheader.missing" for f in before["findings"])

    fixable = [[f["code"], f["target"]] for f in before["findings"] if f["fixable_now"]]
    after = client.post("/api/apply", json={"html": html, "keys": fixable,
                                            "check_links": False} | envelope).json()
    codes = {f["code"] for f in after["report"]["findings"]}
    assert "preheader.missing" in codes, "the repair silently dropped an envelope finding"
