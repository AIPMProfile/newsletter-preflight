"""The improvement loop: creator behaviour read against each check's rubric.

Three signals are decisions and one is the absence of one, and they carry
different prescriptions. These pin that separation, because collapsing them is
how a check gets retuned for the wrong reason.
"""

from __future__ import annotations

import pytest

from preflight.evals import loop
from preflight.evals.rubrics import RUBRICS, missing_rubrics, rubric_for


def act(code, action, reason=None, t=None, n=1):
    return [{"kind": "action", "doc": "d", "code": code, "action": action,
             "reason": reason, "decided_in_sec": t} for _ in range(n)]


# --- rubrics --------------------------------------------------------------

def test_every_shipping_check_has_a_rubric():
    """A check nobody wrote a failure mode for cannot be recalibrated when
    creators start waving it through — there is nothing to read the feedback
    against."""
    import re
    from pathlib import Path
    src = "".join(p.read_text() for p in Path("src/preflight/checks").glob("*.py"))
    shipping = set(re.findall(r'code="([a-z_]+\.[a-z_]+)"', src))
    assert missing_rubrics(shipping) == set()


def test_a_rubric_defines_both_halves():
    for code, r in RUBRICS.items():
        assert r.good and r.bad, f"{code}: a rubric with no bad case defines nothing"
        assert r.decides_in > 0
        assert r.first_lever


# --- reading the signals --------------------------------------------------

def test_false_alarms_recalibrate_the_check():
    rows = act("contrast.aa_fail", "DISMISSED", "FALSE_ALARM", 5, 10) + \
           act("contrast.aa_fail", "AUTO_FIXED", None, 5, 12)
    p = loop.proposals(rows)
    assert p and p[0]["severity"] == "recalibrate"
    assert p[0]["propose"] == rubric_for("contrast.aa_fail").first_lever


def test_meaning_it_is_not_evidence_against_the_check():
    """"I meant it this way" says something about the creator, not the check.
    Counting it would retire rules that work."""
    rows = act("contrast.aa_fail", "DISMISSED", "INTENTIONAL_DESIGN", 5, 20)
    assert loop.proposals(rows) == []


def test_being_ignored_asks_for_a_rewrite_not_a_recalibration():
    """This audience does not hand-edit markup and will not argue with a panel.
    Silence is the feedback, and it means the wording did not land — not that
    the check is inaccurate."""
    rows = act("contrast.aaa_fail", "IGNORED", None, None, 30) + \
           act("contrast.aaa_fail", "AUTO_FIXED", None, 3, 20)
    p = loop.proposals(rows)
    assert p and p[0]["severity"] == "rewrite"
    assert "Do not touch" not in p[0]["propose"]


def test_slow_decisions_are_a_wording_problem_not_an_accuracy_one():
    budget = rubric_for("darkmode.no_bg_override").decides_in
    rows = act("darkmode.no_bg_override", "AUTO_FIXED", None, budget * 2, 24)
    p = loop.proposals(rows)
    assert p and p[0]["severity"] == "reword"
    assert "Do not touch the check" in p[0]["propose"]


def test_a_check_creators_act_on_is_left_alone():
    assert loop.proposals(act("img.missing_alt", "AUTO_FIXED", None, 6, 25)) == []


# --- the evidence floor ---------------------------------------------------

def test_nothing_is_proposed_below_the_evidence_floor():
    """Three dismissals is a rumour. Retiring a working check on a rumour is
    the more expensive mistake."""
    rows = act("link.broken", "DISMISSED", "FALSE_ALARM", 4, 3)
    assert loop.proposals(rows) == []
    assert loop.read(rows)["link.broken"].underpowered is True


def test_ignores_do_not_count_as_decisions():
    """Scrolling past is not deciding, and letting it inflate the denominator
    would let a check reach the floor without anyone having judged it."""
    v = loop.read(act("contrast.aaa_fail", "IGNORED", None, None, 40))["contrast.aaa_fail"]
    assert v.shown == 40 and v.decisions == 0
    assert v.underpowered is True


def test_coverage_reports_what_the_evidence_cannot_speak_to():
    """Proposals about four checks out of sixteen is a different statement from
    proposals about all of them, and silence must not read as approval."""
    cov = loop.coverage(act("img.missing_alt", "AUTO_FIXED", None, 6, 25))
    assert cov["checks_with_enough_evidence"] == 1
    assert cov["checks_total"] == len(RUBRICS)
    assert "link.broken" in cov["unheard"]


def test_an_empty_log_proposes_nothing_and_says_so():
    s = loop.summary([])
    assert s["proposals"] == []
    assert s["coverage"]["checks_with_evidence"] == 0
    assert len(s["coverage"]["unheard"]) == len(RUBRICS)


def test_rates_are_none_rather_than_zero_without_evidence():
    v = loop.read(act("img.missing_alt", "IGNORED", None, None, 1))["img.missing_alt"]
    assert v.approval_rate is None and v.false_alarm_rate is None


@pytest.mark.parametrize("severity", ["recalibrate", "rewrite", "reword"])
def test_every_proposal_names_a_signal_and_a_lever(severity):
    rows = (act("contrast.aa_fail", "DISMISSED", "FALSE_ALARM", 5, 12) +
            act("contrast.aa_fail", "AUTO_FIXED", None, 5, 10) +
            act("contrast.aaa_fail", "IGNORED", None, None, 30) +
            act("contrast.aaa_fail", "AUTO_FIXED", None, 3, 20) +
            act("darkmode.no_bg_override", "AUTO_FIXED", None, 60, 24))
    p = next(x for x in loop.proposals(rows) if x["severity"] == severity)
    assert p["signal"] and p["reading"] and p["propose"]
