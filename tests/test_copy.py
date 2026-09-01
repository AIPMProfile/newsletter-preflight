"""The copy contract: what a creator reads, and what they read only on request.

`PROBLEM.md` says the majority segment has "low tolerance for vocabulary —
'WCAG AA 3.1:1' means nothing; 'this text will be hard to read' does". For a
long time the code said the opposite of that document. These tests make the
principle enforceable instead of aspirational (D33).

The split:

* `message` — what this costs the creator. No hex, no ratios, no tag names.
* `detail`  — the measurement behind it. A professional needs it to defend the
  change; a hobbyist never has to open it.
"""

from __future__ import annotations

import re

import pytest

from preflight.audit import audit_file
from preflight.evals.generate import SAMPLES_DIR, load_ground_truth

#: Vocabulary that belongs in `detail`, never in `message`.
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RATIO = re.compile(r"\b\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\b")
TAG = re.compile(r"<\s*/?\s*(?:p|h[1-6]|div|span|td|table|img|a|body)\b", re.I)
JARGON = re.compile(
    r"\b(WCAG|AAA?\s+floor|prefers-color-scheme|background-color|href|alt attribute|"
    r"element|selector|DOM|CSS|stylesheet|inline style|Liquid tag)\b", re.I)


async def all_findings():
    truth = load_ground_truth()
    out = []
    for sample in truth["cases"]:
        report = await audit_file(SAMPLES_DIR / sample,
                                  offline_links=truth["link_status"], skip_llm=True)
        out.extend(report.findings)
    return out


@pytest.mark.asyncio
@pytest.mark.parametrize("pattern,label", [
    (HEX, "a hex colour"),
    (RATIO, "a contrast ratio"),
    (TAG, "an HTML tag name"),
    (JARGON, "spec jargon"),
])
async def test_no_finding_message_contains_engineer_vocabulary(pattern, label):
    for finding in await all_findings():
        assert not pattern.search(finding.message), (
            f"{finding.code}: message contains {label} — that belongs in `detail`.\n"
            f"  message: {finding.message}"
        )


@pytest.mark.asyncio
async def test_every_finding_says_what_it_costs_the_creator():
    """A message that does not name a consequence is a label, not a sentence."""
    for finding in await all_findings():
        assert len(finding.message.split()) >= 8, (
            f"{finding.code}: message is too terse to carry a consequence — "
            f"{finding.message!r}")
        assert finding.message.strip().endswith((".", "!")), (
            f"{finding.code}: message is not a sentence — {finding.message!r}")


@pytest.mark.asyncio
async def test_the_measurement_is_available_not_discarded():
    """Moving jargon out of `message` must not lose it. A professional has to be
    able to see the number that produced the verdict."""
    measured = {"contrast.aa_fail", "contrast.aaa_fail", "darkmode.no_bg_override",
                "darkmode.unsafe_override", "link.broken"}
    seen = {f.code for f in await all_findings() if f.code in measured}
    assert seen, "corpus no longer exercises the measured checks"
    for finding in await all_findings():
        if finding.code in measured:
            assert finding.detail, f"{finding.code}: measurement was dropped, not moved"


@pytest.mark.asyncio
async def test_detail_never_merely_repeats_the_message():
    for finding in await all_findings():
        if finding.detail:
            assert finding.detail.strip() != finding.message.strip()


@pytest.mark.asyncio
async def test_every_finding_offers_a_next_step():
    for finding in await all_findings():
        assert finding.remedy, f"{finding.code}: no remedy — nothing for a creator to do"


@pytest.mark.asyncio
async def test_remedies_do_not_assume_a_developer():
    """A remedy a creator cannot follow is not a remedy. Hex codes are allowed
    here — "darken it to #767676" is actionable — but markup edits are not."""
    for finding in await all_findings():
        assert not TAG.search(finding.remedy), (
            f"{finding.code}: remedy talks in markup — {finding.remedy!r}")
