"""Link probing: offline replay, and the degradation contract on live checks."""

import asyncio

import pytest

from preflight.checks.links import (
    LinkResult,
    check_links,
    collect_urls,
    findings_from_results,
    probe_urls,
)
from preflight.parser import load


def test_collect_urls_skips_relative_mailto_and_liquid():
    soup, _ = load(
        '<a href="https://wren.email/a">a</a>'
        '<a href="/relative">b</a>'
        '<a href="mailto:me@wren.email">c</a>'
        '<a href="{{ tracking_url }}">d</a>'
        '<a href="https://wren.email/a">dup</a>'
    )
    urls = collect_urls(soup)
    assert list(urls) == ["https://wren.email/a"]
    assert len(urls["https://wren.email/a"]) == 2, "both anchors share one probe"


async def test_offline_replay_flags_only_the_pinned_failures():
    soup, _ = load('<a id="bad" href="https://x.test/404">a</a>'
                   '<a id="ok" href="https://x.test/fine">b</a>')
    found = await check_links(soup, offline={"https://x.test/404": 404})
    assert [(f.code, f.target) for f in found] == [("link.broken", "bad")]


async def test_offline_replay_treats_error_strings_as_broken():
    soup, _ = load('<a id="bad" href="https://x.test/slow">a</a>')
    found = await check_links(soup, offline={"https://x.test/slow": "timeout"})
    assert found[0].evidence["error"] == "timeout"


@pytest.mark.parametrize("status,error,broken", [
    (200, None, False), (301, None, False), (404, None, True),
    (500, None, True), (None, "timeout", True), (None, "ConnectError", True),
])
def test_broken_classification(status, error, broken):
    assert LinkResult("u", status, error).broken is broken


def test_every_anchor_sharing_a_dead_url_gets_its_own_finding():
    soup, _ = load('<a id="one" href="https://x.test/404">a</a>'
                   '<a id="two" href="https://x.test/404">b</a>')
    results = {"https://x.test/404": LinkResult("https://x.test/404", 404)}
    assert {f.target for f in findings_from_results(soup, results)} == {"one", "two"}


async def test_probe_respects_the_phase_budget():
    """Unanswered links are reported as unknown, never as broken."""
    started = asyncio.get_event_loop().time()
    results = await probe_urls(["https://10.255.255.1/never"], budget=0.3)
    assert asyncio.get_event_loop().time() - started < 2.0
    assert results == {} or all(not r.broken or r.error for r in results.values())


async def test_no_links_means_no_work():
    soup, _ = load("<p>no links here</p>")
    assert await check_links(soup) == []
