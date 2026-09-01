"""Verdict semantics - the one output a creator acts on.

There is no readiness score any more, so there is nothing here about points.
The old tests asserted that an error cost 12 and a warning 5, which pinned
weights nobody could defend; the verdict is derived instead (D28).
"""

import pytest

from preflight.models import (
    HOLD,
    READY,
    REVIEW,
    SEVERITY_LABEL,
    SEVERITY_RANK,
    SLA_MS,
    AuditReport,
    Finding,
    Severity,
    Timing,
)


def _f(severity, code="x.y", module="deterministic", **kw):
    return Finding(code=code, severity=severity, target="t", message="m",
                   module=module, **kw)


# --- verdict --------------------------------------------------------------

@pytest.mark.parametrize("severities,verdict", [
    ([], READY),
    ([Severity.COULD_BE_BETTER], REVIEW),
    ([Severity.COULD_BE_BETTER] * 5, REVIEW),
    ([Severity.WILL_EMBARRASS], HOLD),
    ([Severity.WILL_EMBARRASS, Severity.COULD_BE_BETTER], HOLD),
    ([Severity.WILL_BREAK], HOLD),
    ([Severity.WILL_BREAK, Severity.WILL_EMBARRASS], HOLD),
])
def test_verdict_is_driven_by_the_worst_finding(severities, verdict):
    assert AuditReport(path="p", findings=[_f(s) for s in severities]).verdict == verdict


def test_ready_means_nothing_was_found_at_all():
    """READY is the strictest state on purpose. An advisory note is still
    something we noticed, and saying READY over it would be a small lie."""
    assert AuditReport(path="p").verdict == READY
    assert AuditReport(path="p", findings=[_f(Severity.COULD_BE_BETTER)]).verdict == REVIEW


def test_anything_that_breaks_or_embarrasses_blocks_the_send():
    for sev in (Severity.WILL_BREAK, Severity.WILL_EMBARRASS):
        assert _f(sev).blocking
    assert not _f(Severity.COULD_BE_BETTER).blocking


def test_blocking_findings_are_listed_for_the_headline():
    report = AuditReport(path="p", findings=[
        _f(Severity.WILL_BREAK, code="a.b"),
        _f(Severity.COULD_BE_BETTER, code="c.d"),
    ])
    assert [f.code for f in report.blocking_findings] == ["a.b"]


def test_there_is_no_score_attribute_left_to_depend_on():
    assert not hasattr(AuditReport(path="p"), "score")


# --- the taxonomy itself --------------------------------------------------

def test_labels_are_what_a_creator_reads():
    assert SEVERITY_LABEL[Severity.WILL_BREAK] == "WILL BREAK"
    assert SEVERITY_LABEL[Severity.WILL_EMBARRASS] == "WILL EMBARRASS"
    assert SEVERITY_LABEL[Severity.COULD_BE_BETTER] == "COULD BE BETTER"
    assert _f(Severity.WILL_BREAK).label == "WILL BREAK"


def test_rank_orders_worst_first_and_is_never_summed():
    assert SEVERITY_RANK[Severity.WILL_BREAK] < SEVERITY_RANK[Severity.WILL_EMBARRASS]
    assert SEVERITY_RANK[Severity.WILL_EMBARRASS] < SEVERITY_RANK[Severity.COULD_BE_BETTER]


def test_severity_values_are_stable_wire_format():
    """Fixtures and the LLM schema both carry these strings."""
    assert [s.value for s in Severity] == ["will_break", "will_embarrass", "could_be_better"]


# --- scored / fixable contracts -------------------------------------------

def test_only_advisory_findings_are_unscored():
    assert _f(Severity.WILL_BREAK).scored and _f(Severity.WILL_EMBARRASS).scored
    assert not _f(Severity.COULD_BE_BETTER).scored


def test_fixable_now_excludes_what_only_aggressive_repairs():
    """The one-click button counts `fixable_now`. A finding it advertises and
    then skips is the broken promise this flag exists to prevent (D29)."""
    assert _f(Severity.WILL_EMBARRASS, fixable=True).fixable_now
    assert not _f(Severity.WILL_EMBARRASS, fixable=True, requires_aggressive=True).fixable_now
    assert not _f(Severity.WILL_EMBARRASS, fixable=False).fixable_now


def test_key_is_the_ground_truth_contract():
    assert _f(Severity.WILL_BREAK, code="a.b").key == ("a.b", "t")


# --- timing ---------------------------------------------------------------

def test_presend_excludes_the_reviewer():
    t = Timing(deterministic_ms=10.0, links_ms=20.0, llm_ms=5000.0, total_ms=5030.0)
    assert t.presend_ms == 30.0
    assert t.within_sla


def test_sla_is_breached_on_the_presend_phases_only():
    t = Timing(deterministic_ms=SLA_MS, links_ms=1.0, llm_ms=0.0, total_ms=SLA_MS + 1)
    assert not t.within_sla
