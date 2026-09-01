"""Production monitoring: opt-in, content-free, and never able to break an audit."""

from __future__ import annotations

import json

import pytest

from preflight import monitor
from preflight.models import AuditReport, Finding, Severity, Timing

HTML = '<p>Hi {{ subscriber.first_name }}, the launch is live at wren.email/launch</p>'


def report(codes=("contrast.aa_fail", "contrast.aa_fail", "img.missing_alt")) -> AuditReport:
    return AuditReport(
        path="secret-draft.html",
        findings=[Finding(code=c, module="deterministic", severity=Severity.WILL_BREAK,
                          target=f"t{i}", message="m", remedy="r")
                  for i, c in enumerate(codes)],
        timing=Timing(deterministic_ms=1.0, links_ms=0.0, llm_ms=0.0, total_ms=1.0),
        llm_status="ok",
        stats={"words": 10, "links": 1, "images": 0},
    )


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "audits.jsonl"
    monkeypatch.setenv("PREFLIGHT_MONITOR", "1")
    monkeypatch.setenv("PREFLIGHT_MONITOR_LOG", str(path))
    return path


# --- the opt-in contract --------------------------------------------------

def test_monitoring_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PREFLIGHT_MONITOR", raising=False)
    monkeypatch.setenv("PREFLIGHT_MONITOR_LOG", str(tmp_path / "a.jsonl"))
    assert monitor.enabled() is False
    assert monitor.record(report(), HTML) is None
    assert not (tmp_path / "a.jsonl").exists()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_monitoring_turns_on_for_the_obvious_spellings(monkeypatch, value):
    monkeypatch.setenv("PREFLIGHT_MONITOR", value)
    assert monitor.enabled() is True


def test_a_write_failure_never_breaks_the_audit(tmp_path, monkeypatch):
    """A pre-send check must not fail because telemetry could not be written."""
    monkeypatch.setenv("PREFLIGHT_MONITOR", "1")
    monkeypatch.setenv("PREFLIGHT_MONITOR_LOG", str(tmp_path / "nope" / "a.jsonl"))
    monkeypatch.setattr(monitor.Path, "mkdir",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    assert monitor.record(report(), HTML) is None


# --- what it is allowed to store ------------------------------------------

def test_no_email_content_reaches_the_log(log):
    monitor.record(report(), HTML, source="cli")
    raw = log.read_text()
    for leak in ("subscriber", "first_name", "wren.email", "launch", "<p>"):
        assert leak not in raw, f"{leak!r} leaked into the monitor log"


def test_the_document_is_identified_by_a_hash_that_reverses_to_nothing(log):
    row = monitor.record(report(), HTML)
    assert len(row["doc"]) == 12
    assert row["doc"] not in HTML
    # Same document, same id - that is what makes repeat audits countable.
    assert monitor.record(report(), HTML)["doc"] == row["doc"]
    assert monitor.record(report(), HTML + " ")["doc"] != row["doc"]


def test_the_row_carries_counts_and_timings(log):
    row = monitor.record(report(), HTML)
    assert row["codes"] == {"contrast.aa_fail": 2, "img.missing_alt": 1}
    assert row["verdict"] == "HOLD"
    assert row["blocking"] == 3
    assert row["scored_findings"] == 3
    assert "presend_ms" in row and "within_sla" in row


# --- summarising ----------------------------------------------------------

def test_share_counts_documents_not_findings(log):
    """One email with forty contrast failures is one email with a contrast
    problem. Rating by raw count would let a single document set the baseline."""
    monitor.record(report(("contrast.aa_fail",) * 40), HTML)
    monitor.record(report(("img.missing_alt",)), HTML + "x")
    summary = monitor.summarize(monitor.load(log))
    assert summary["documents"] == 2
    assert summary["codes"]["contrast.aa_fail"]["share"] == 0.5
    assert summary["codes"]["img.missing_alt"]["share"] == 0.5


def test_summary_of_nothing_is_empty_not_an_error():
    assert monitor.summarize([])["documents"] == 0


def test_load_returns_empty_when_no_log_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("PREFLIGHT_MONITOR_LOG", str(tmp_path / "missing.jsonl"))
    assert monitor.load() == []


# --- drift ----------------------------------------------------------------

def test_drift_needs_two_full_windows_before_it_will_say_anything():
    rows = [{"codes": {"contrast.aa_fail": 1}, "verdict": "HOLD"}] * 10
    assert monitor.drift(rows, window=20) == []


def test_drift_reports_a_code_that_took_over_the_mix():
    quiet = [{"codes": {"contrast.aa_fail": 1}, "verdict": "HOLD",
              "llm_status": "ok", "within_sla": True, "presend_ms": 1.0, "doc": f"a{i}"}
             for i in range(40)]
    loud = [{"codes": {"darkmode.no_bg_override": 1}, "verdict": "HOLD",
             "llm_status": "ok", "within_sla": True, "presend_ms": 1.0, "doc": f"b{i}"}
            for i in range(20)]
    moved = monitor.drift(quiet + loud, window=20)
    codes = {d["code"] for d in moved}
    assert "darkmode.no_bg_override" in codes
    top = next(d for d in moved if d["code"] == "darkmode.no_bg_override")
    assert top["baseline_share"] == 0.0 and top["recent_share"] == 1.0


def test_a_stable_mix_reports_no_drift():
    rows = [{"codes": {"contrast.aa_fail": 1}, "verdict": "HOLD",
             "llm_status": "ok", "within_sla": True, "presend_ms": 1.0, "doc": f"d{i}"}
            for i in range(60)]
    assert monitor.drift(rows, window=20) == []


def test_rows_are_appended_not_rewritten(log):
    monitor.record(report(), HTML)
    monitor.record(report(), HTML + "x")
    lines = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    assert len(lines) == 2


# --- creator actions ------------------------------------------------------

def test_an_action_joins_to_its_audit_by_document_hash(log):
    audit = monitor.record(report(), HTML)
    action = monitor.record_action("OVERRIDDEN", doc=audit["doc"],
                                   verdict_at_audit="HOLD", time_to_resolve_sec=31.0)
    assert action["doc"] == audit["doc"]
    assert action["kind"] == "action" and audit["kind"] == "audit"


def test_an_unknown_action_is_refused(log):
    assert monitor.record_action("SHIPPED_IT", doc="abc") is None


def test_actions_respect_the_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("PREFLIGHT_MONITOR", raising=False)
    monkeypatch.setenv("PREFLIGHT_MONITOR_LOG", str(tmp_path / "a.jsonl"))
    assert monitor.record_action("OVERRIDDEN", doc="abc") is None


def test_no_email_content_reaches_an_action_row(log):
    monitor.record_action("AUTO_FIXED", doc=monitor.digest(HTML), verdict_at_audit="HOLD")
    raw = log.read_text()
    for leak in ("subscriber", "first_name", "wren.email", "<p>"):
        assert leak not in raw


def _rows():
    return [
        {"kind": "audit", "doc": "a"}, {"kind": "audit", "doc": "b"},
        {"kind": "audit", "doc": "c"},
        {"kind": "action", "doc": "a", "action": "OVERRIDDEN",
         "verdict_at_audit": "HOLD", "time_to_resolve_sec": 40.0},
        {"kind": "action", "doc": "b", "action": "AUTO_FIXED",
         "verdict_at_audit": "HOLD", "time_to_resolve_sec": 10.0,
         "fixes_kept": 3, "fixes_undone": 1},
    ]


def test_override_rate_is_the_trust_signal():
    b = monitor.behaviour(_rows())
    assert b["override_rate"] == 0.5          # 1 of 2 HOLD outcomes
    assert b["action_rate_on_hold"] == 0.5


def test_fix_acceptance_counts_kept_against_undone():
    assert monitor.behaviour(_rows())["fix_acceptance_rate"] == 0.75


def test_an_audit_with_no_recorded_send_is_unresolved_not_abandoned():
    """"Closed the tab" cannot be observed from inside a request. Calling it
    abandonment would be a guess dressed as data."""
    b = monitor.behaviour(_rows())
    assert b["unresolved_audits"] == 1
    assert "ABANDONED" not in b["actions"]


def test_rates_are_none_rather_than_zero_when_nothing_was_observed():
    """A 0% override rate computed from no sends is not a fact about the
    product, and would read as one."""
    b = monitor.behaviour([{"kind": "audit", "doc": "a"}])
    assert b["override_rate"] is None
    assert b["action_rate_on_hold"] is None
    assert b["fix_acceptance_rate"] is None
    assert b["median_time_to_resolve_sec"] is None


def test_behaviour_of_an_empty_log_is_empty_not_an_error():
    b = monitor.behaviour([])
    assert b["audits"] == 0 and b["override_rate"] is None


def test_old_rows_without_a_kind_still_count_as_audits():
    """The schema gained `kind` after the first rows were written."""
    assert monitor.behaviour([{"doc": "a"}])["audits"] == 1


def test_each_rate_reports_its_own_denominator():
    """Regression: fix acceptance was displayed against `hold_outcomes`.

    The rate was right and the n beside it was wrong, which is worse than
    showing no n at all - the label then says something the number does not
    mean. Every rate exposes the denominator it was actually computed from.
    """
    rows = [
        {"kind": "audit", "doc": "a"},
        {"kind": "action", "doc": "a", "action": "AUTO_FIXED",
         "verdict_at_audit": "HOLD", "fixes_kept": 3, "fixes_undone": 2},
    ]
    b = monitor.behaviour(rows)
    assert b["fix_acceptance_rate"] == 0.6
    assert b["fix_decisions"] == 5          # not hold_outcomes, which is 1
    assert b["hold_outcomes"] == 1


def test_fix_decisions_is_zero_when_no_fix_was_offered():
    b = monitor.behaviour([{"kind": "action", "doc": "a", "action": "OVERRIDDEN",
                            "verdict_at_audit": "HOLD"}])
    assert b["fix_decisions"] == 0
    assert b["fix_acceptance_rate"] is None


def test_audit_rate_is_not_reported_because_it_cannot_be_computed():
    """Its denominator is drafts that were never audited, which a tool you had
    to choose to run cannot see. Defining a metric it cannot compute is the
    failure D31 exists to prevent."""
    assert "audit_rate" not in monitor.behaviour([])


# --- dismissal and rule health (D35) --------------------------------------
#
# The rates themselves are exercised in test_loop.py, against the code that
# computes them. What is worth pinning here is the delegation: these two used to
# disagree about whether scrolling past a finding counts as a decision.

def test_a_dismissal_records_which_rule_and_why(log):
    row = monitor.record_action("DISMISSED", doc="abc", code="contrast.aa_fail",
                                reason="FALSE_ALARM", verdict_at_audit="HOLD")
    assert row["code"] == "contrast.aa_fail" and row["reason"] == "FALSE_ALARM"


def _rule_rows(n_false, n_intentional, n_fixed, code="contrast.aa_fail"):
    rows = [{"kind": "action", "doc": "d", "action": "DISMISSED",
             "code": code, "reason": "FALSE_ALARM"} for _ in range(n_false)]
    rows += [{"kind": "action", "doc": "d", "action": "DISMISSED",
              "code": code, "reason": "INTENTIONAL_DESIGN"} for _ in range(n_intentional)]
    rows += [{"kind": "action", "doc": "d", "action": "AUTO_FIXED",
              "code": code} for _ in range(n_fixed)]
    return rows





def test_nothing_can_switch_a_check_off():
    """There is no automatic pause, by design.

    A check that quietly retunes or disables itself on its own telemetry is one
    nobody can reason about, and the failure mode is vicious: creators ignore a
    check because the wording is poor, the loop reads that as inaccuracy, and
    the check stops catching what it existed for while the number moves the
    right way (D35, D40).
    """
    assert not hasattr(monitor, "paused_rules")
    assert not hasattr(monitor, "autopause_enabled")


def test_rule_health_and_the_loop_agree_on_what_a_decision_is():
    """They used to disagree. On identical evidence one reported a 19%
    false-alarm rate and stayed silent while the other reported 45% and proposed
    a recalibration, because one counted ignores as decisions and one did not."""
    from preflight.evals import loop
    rows = _rule_rows(10, 0, 12) + [
        {"kind": "action", "doc": "d", "action": "IGNORED", "code": "contrast.aa_fail"}
    ] * 30
    h = monitor.rule_health(rows)["contrast.aa_fail"]
    v = loop.read(rows)["contrast.aa_fail"]
    assert h["decisions"] == v.decisions == 22
    assert h["false_alarm_rate"] == pytest.approx(v.false_alarm_rate, abs=1e-4)
    assert h["needs_recalibration"] is bool(v.proposal()) is True


def test_actions_without_a_rule_do_not_pollute_rule_health():
    assert monitor.rule_health([{"kind": "action", "doc": "d", "action": "OVERRIDDEN"}]) == {}
