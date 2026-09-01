"""The repair harness: does a click make mail sendable, and does layout survive?"""

from __future__ import annotations

import pytest

from preflight.evals.run_harness import (
    _is_subsequence,
    element_sequence,
    parsed_baseline,
    run,
    write,
)

SAFE = '<html><body><table><tr><td><p>Hi {{ subscriber.first_name }}</p></td></tr></table></body></html>'


def test_the_baseline_is_a_settled_round_trip():
    """Layout is compared against the document as the parser returns it, not
    against the raw bytes. On real pages a read/write cycle already moves
    things - one corpus page gained an element with zero repairs applied - so
    comparing to raw input blames the fixer for the parser's tidying. The
    baseline itself must be stable, or the comparison point drifts."""
    once = parsed_baseline(SAFE)
    assert element_sequence(parsed_baseline(once)) == element_sequence(once)


@pytest.mark.asyncio
async def test_an_intended_addition_does_not_count_as_layout_damage(tmp_path):
    """Wrapping a bare URL adds an <a>. Byte equality would fail the repair the
    creator asked for."""
    (tmp_path / "bare.html").write_text(
        '<html><body><td style="background-color:#ffffff">'
        '<p style="color:#111111;background-color:#ffffff">'
        'See https://example.com/guide for more</p></td></body></html>')
    r = await run(corpus_dir=tmp_path)
    case = r["cases"][0]
    assert case["elements_added"] >= 1
    assert case["layout_safe"] is True


def test_an_added_element_is_allowed_but_a_removed_one_is_not():
    """Wrapping a bare URL in an anchor adds an <a>. That is the repair the
    creator asked for, not damage."""
    base = ["table", "tr", "td", "p"]
    assert _is_subsequence(base, ["table", "tr", "td", "p", "a"])      # added
    assert not _is_subsequence(base, ["table", "tr", "p"])             # td removed
    assert not _is_subsequence(base, ["tr", "table", "td", "p"])       # reordered


@pytest.mark.asyncio
async def test_an_empty_corpus_reports_nothing_rather_than_zero(tmp_path):
    """"0% clearance" from no documents reads as a failing product."""
    r = await run(corpus_dir=tmp_path)
    assert r["documents"] == 0
    assert r["clearance_rate"] is None and r["layout_safe_rate"] is None
    assert r["passes"] is False


@pytest.mark.asyncio
async def test_a_clean_document_clears_and_keeps_its_layout(tmp_path):
    (tmp_path / "clean.html").write_text(SAFE)
    r = await run(corpus_dir=tmp_path)
    assert r["documents"] == 1
    assert r["layout_safe_rate"] == 1.0
    assert r["cases"][0]["liquid_safe"] is True


@pytest.mark.asyncio
async def test_a_repairable_document_clears_the_block(tmp_path):
    (tmp_path / "d.html").write_text(
        '<html><body><td style="background-color:#ffffff">'
        '<p style="color:#bbbbbb;background-color:#ffffff">too light to read</p>'
        '</td></body></html>')
    r = await run(corpus_dir=tmp_path)
    case = r["cases"][0]
    assert case["blocking_before"] > 0
    assert case["cleared"] is True
    assert case["layout_safe"] is True


@pytest.mark.asyncio
async def test_results_record_the_real_sample_size(tmp_path):
    """N is whatever the corpus holds. It is never padded toward a target."""
    for i in range(3):
        (tmp_path / f"d{i}.html").write_text(SAFE)
    r = await run(corpus_dir=tmp_path)
    assert r["documents"] == 3
    out = write(r, tmp_path / "results.json")
    assert out.exists() and '"documents": 3' in out.read_text()


@pytest.mark.asyncio
async def test_liquid_survives_every_document(tmp_path):
    (tmp_path / "liquid.html").write_text(SAFE)
    r = await run(corpus_dir=tmp_path)
    assert all(c["liquid_safe"] for c in r["cases"])
