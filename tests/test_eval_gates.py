"""The product-level eval gates: severity, controls, verdict, and the fix pass.

These cover the scoring rules added when the benchmark stopped measuring only
detection. Offline throughout - `run_benchmark` replays pinned link statuses and
authored fixtures.
"""

from __future__ import annotations

import pytest

from preflight.evals.harness import (
    FixOutcome,
    check_forbidden,
    match,
    run_benchmark,
    truth_contradictions,
)
from preflight.models import Finding, Severity


def finding(code: str, target: str, severity: Severity = Severity.WILL_BREAK,
            module: str = "deterministic") -> Finding:
    return Finding(code=code, module=module, severity=severity, target=target,
                   message="m", remedy="r")


# --- severity is part of the match key ------------------------------------

def test_right_code_right_severity_is_a_true_positive():
    out = match([finding("contrast.aa_fail", "x")],
                [{"code": "contrast.aa_fail", "target": "x", "severity": "will_break"}], "s")
    assert out["deterministic"].tp == 1
    assert out["deterministic"].severity_items == []


def test_right_code_wrong_severity_is_not_a_true_positive():
    """A check that fires at the wrong tier can move the verdict - WILL_EMBARRASS
    and COULD_BE_BETTER are the difference between HOLD and REVIEW."""
    out = match([finding("contrast.aa_fail", "x", Severity.WILL_EMBARRASS)],
                [{"code": "contrast.aa_fail", "target": "x", "severity": "will_break"}], "s")
    c = out["deterministic"]
    assert c.tp == 0 and c.fn == 1
    assert c.severity_items == [
        ("s", "contrast.aa_fail", "x", "will_break", "will_embarrass")]


def test_severity_drift_is_not_double_counted_as_a_false_positive():
    """The finding is consumed by the entry it drifted from, so it does not
    also land in the leftovers as an invention."""
    out = match([finding("contrast.aa_fail", "x", Severity.WILL_EMBARRASS)],
                [{"code": "contrast.aa_fail", "target": "x", "severity": "will_break"}], "s")
    assert out["deterministic"].fp == 0


def test_an_entry_without_a_severity_accepts_any():
    """LLM entries carry no expected severity: it is the model's judgment, and
    the fixture supplying it is authored."""
    out = match([finding("cta.buried", "cta", Severity.WILL_EMBARRASS, module="llm")],
                [{"code": "cta.buried", "target": "*"}], "s")
    assert out["llm"].tp == 1


def test_severity_items_survive_addition():
    a = match([finding("contrast.aa_fail", "x", Severity.WILL_EMBARRASS)],
              [{"code": "contrast.aa_fail", "target": "x", "severity": "will_break"}], "s")
    b = match([finding("img.missing_alt", "y", Severity.WILL_EMBARRASS)],
              [{"code": "img.missing_alt", "target": "y", "severity": "will_break"}], "t")
    assert len((a["deterministic"] + b["deterministic"]).severity_items) == 2


# --- forbidden controls ---------------------------------------------------

def test_a_clean_element_flagged_violates_its_control():
    v = check_forbidden([finding("contrast.aa_fail", "good-copy")],
                        [{"code": "contrast.aa_fail", "target": "good-copy"}], "s")
    assert v == [("s", "contrast.aa_fail", "good-copy", "will_break")]


def test_controls_see_advisory_findings_that_false_positives_cannot():
    """Plain FP counting only looks at scored findings. A control says "this
    element is correct", and an advisory note on it still contradicts that."""
    v = check_forbidden([finding("contrast.aaa_fail", "good-copy", Severity.COULD_BE_BETTER)],
                        [{"code": "contrast.aaa_fail", "target": "good-copy"}], "s")
    assert len(v) == 1 and v[0][3] == "could_be_better"


def test_a_wildcard_control_forbids_the_code_anywhere():
    v = check_forbidden([finding("link.broken", "anything")],
                        [{"code": "link.broken", "target": "*"}], "s")
    assert len(v) == 1


def test_a_satisfied_control_is_silent():
    assert check_forbidden([finding("contrast.aa_fail", "bad-copy")],
                           [{"code": "contrast.aa_fail", "target": "good-copy"}], "s") == []


# --- ground truth cannot contradict itself --------------------------------

def test_expected_and_forbidden_on_the_same_target_is_refused():
    """The guard on rule 4. The cheapest way to make a failing benchmark pass is
    to add the finding to `expected` - if a control already called that element
    clean, the corpus now says two opposite things."""
    problems = truth_contradictions({"s.html": {
        "expected": [{"code": "contrast.aa_fail", "target": "x"}],
        "forbidden": [{"code": "contrast.aa_fail", "target": "x"}],
    }})
    assert len(problems) == 1 and "both expected and forbidden" in problems[0]


def test_a_wildcard_control_contradicts_an_expectation_of_the_same_code():
    problems = truth_contradictions({"s.html": {
        "expected": [{"code": "link.broken", "target": "dead"}],
        "forbidden": [{"code": "link.broken", "target": "*"}],
    }})
    assert len(problems) == 1


def test_consistent_ground_truth_reports_nothing():
    assert truth_contradictions({"s.html": {
        "expected": [{"code": "contrast.aa_fail", "target": "bad"}],
        "forbidden": [{"code": "contrast.aa_fail", "target": "good"}],
    }}) == []


def test_the_shipped_corpus_does_not_contradict_itself():
    from preflight.evals.generate import GROUND_TRUTH
    assert truth_contradictions(GROUND_TRUTH) == []


# --- fix outcome arithmetic -----------------------------------------------

def test_resolution_rate_of_a_sample_with_nothing_fixable_is_one():
    """Zero of zero is "nothing was promised and nothing was owed", not a
    failure - otherwise a clean sample would drag the pooled rate down."""
    assert FixOutcome(sample="s", fixable_before=0).resolution_rate == 1.0


def test_resolution_rate_counts_what_landed():
    assert FixOutcome(sample="s", fixable_before=4, resolved=3).resolution_rate == 0.75


def test_a_fix_that_touches_liquid_is_never_clean():
    assert FixOutcome(sample="s", liquid_safe=False).clean is False


def test_a_fix_that_does_not_converge_is_never_clean():
    assert FixOutcome(sample="s", converged=False).clean is False


# --- end to end over the real corpus --------------------------------------

@pytest.mark.asyncio
async def test_benchmark_scores_the_verdict_the_creator_acts_on():
    result = await run_benchmark()
    assert result.verdict_accuracy == 1.0, result.verdict_misses


@pytest.mark.asyncio
async def test_no_control_is_violated_on_the_shipped_corpus():
    result = await run_benchmark()
    assert result.control_violations == []


@pytest.mark.asyncio
async def test_no_severity_drift_on_the_shipped_corpus():
    result = await run_benchmark()
    assert result.severity_drift == []


@pytest.mark.asyncio
async def test_the_fixer_never_touches_liquid_anywhere_in_the_corpus():
    result = await run_benchmark()
    unsafe = [c.fix.sample for c in result.cases
              if c.fix is not None and not c.fix.liquid_safe]
    assert unsafe == []


@pytest.mark.asyncio
async def test_pooled_resolution_rate_is_not_averaged_per_sample():
    """A sample with one fixable finding must not weigh the same as one with
    eleven."""
    result = await run_benchmark()
    outcomes = [c.fix for c in result.cases if c.fix is not None]
    fixable = sum(o.fixable_before for o in outcomes)
    resolved = sum(o.resolved for o in outcomes)
    assert result.fix_resolution_rate == pytest.approx(resolved / fixable)


@pytest.mark.asyncio
async def test_the_fix_pass_can_be_turned_off():
    result = await run_benchmark(score_fix=False)
    assert all(c.fix is None for c in result.cases)


@pytest.mark.asyncio
async def test_the_one_click_fix_keeps_its_promise():
    """Everything the button advertises as fixable, the button fixes.

    This was red when the fix pass was first added: `darkmode.unsafe_override`
    was counted and then skipped, because the parser dropped `!important` and
    the stylesheet override it wrote could never win against the inline
    background the previous fixer had pinned (D29).
    """
    result = await run_benchmark()
    assert result.fix_resolution_rate == 1.0, result.mis_advertised_fixes
    assert result.mis_advertised_fixes == []


@pytest.mark.asyncio
async def test_the_shipped_fixer_converges():
    """Measured through `fix_document`, which is what the CLI and the web UI
    call. The single-pass primitive underneath it genuinely does not converge -
    repairing contrast can create a dark-mode finding - which is exactly why
    `fix_document` loops."""
    result = await run_benchmark()
    assert result.unsafe_fixes == []
