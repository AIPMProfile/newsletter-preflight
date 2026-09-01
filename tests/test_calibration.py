"""Cohen's kappa, the label contract, and what an uncalibrated judge looks like.

No network: every case here builds findings by hand and hands them to the same
scorer the CLI uses.
"""

from __future__ import annotations

import json

import pytest

from preflight.evals.calibration import (
    Agreement,
    CalibrationResult,
    SampleCalibration,
    calibrate_sample,
    interpret,
    load_labels,
)
from preflight.models import Finding, Severity


def llm_finding(code: str, target: str = "*", severity: Severity = Severity.WILL_EMBARRASS) -> Finding:
    return Finding(code=code, module="llm", severity=severity, target=target,
                   message="m", remedy="r")


def labels(*entries, blind: bool = True, by: str = "tester") -> dict:
    return {"labelled_by": by, "blind": blind,
            "labels": [{"code": c, "target": t, "real": r} for c, t, r in entries]}


# --- the statistic itself -------------------------------------------------

def test_kappa_is_one_when_raters_agree_and_both_use_both_answers():
    a = Agreement(both_real=5, human_only=0, judge_only=0, both_absent=5)
    assert a.observed == 1.0
    assert a.kappa == pytest.approx(1.0)


def test_kappa_is_undefined_rather_than_zero_when_there_is_no_variance():
    """Both raters said yes to everything. There is no chance-agreement to
    correct for, and reporting 0.0 would read as total disagreement."""
    a = Agreement(both_real=7)
    assert a.observed == 1.0
    assert a.kappa is None
    assert "undefined" in interpret(None)


def test_kappa_is_zero_at_chance():
    # Symmetric disagreement at a 50% base rate: exactly what guessing gives.
    a = Agreement(both_real=25, human_only=25, judge_only=25, both_absent=25)
    assert a.observed == pytest.approx(0.5)
    assert a.expected == pytest.approx(0.5)
    assert a.kappa == pytest.approx(0.0)


def test_kappa_goes_negative_when_worse_than_chance():
    a = Agreement(both_real=1, human_only=9, judge_only=9, both_absent=1)
    assert a.kappa < 0
    assert interpret(a.kappa) == "worse than chance"


def test_raw_agreement_flatters_a_sparse_label_set_and_kappa_does_not():
    """The reason kappa is the headline number.

    One real judgment, one miss, and ninety-eight things nobody flagged: raw
    agreement reads 98%, which would let a judge that finds nothing look good.
    """
    a = Agreement(both_real=1, human_only=1, judge_only=1, both_absent=97)
    assert a.observed == pytest.approx(0.98)
    assert a.kappa < 0.6
    assert interpret(a.kappa) in {"slight", "fair", "moderate"}


def test_agreement_adds_across_samples():
    total = Agreement(1, 2, 3, 4) + Agreement(10, 20, 30, 40)
    assert (total.both_real, total.human_only, total.judge_only, total.both_absent) == (11, 22, 33, 44)


@pytest.mark.parametrize("kappa,band", [
    (0.05, "slight"), (0.3, "fair"), (0.5, "moderate"),
    (0.7, "substantial"), (0.95, "almost perfect"),
])
def test_interpretation_bands(kappa, band):
    assert interpret(kappa) == band


# --- scoring one sample ---------------------------------------------------

def test_perfect_judge_scores_as_agreement():
    cal = calibrate_sample(
        "s.html",
        labels(("cta.buried", "*", True), ("spam.trigger_phrase", "*", True)),
        [llm_finding("cta.buried"), llm_finding("spam.trigger_phrase")],
    )
    assert cal.agreement.both_real == 2
    assert cal.agreement.human_only == 0
    assert cal.agreement.judge_only == 0
    assert cal.disputes == []


def test_a_missed_judgment_is_recorded_against_the_judge():
    cal = calibrate_sample("s.html", labels(("cta.buried", "*", True)), [])
    assert cal.agreement.human_only == 1
    assert cal.disputes == [("cta.buried", "*", "judge missed")]


def test_an_invented_judgment_is_recorded_against_the_judge():
    """A label saying "not real" is what makes an invention visible. Without
    the negative rows kappa cannot tell a careful judge from an eager one."""
    cal = calibrate_sample(
        "s.html",
        labels(("cta.buried", "*", False)),
        [llm_finding("cta.buried")],
    )
    assert cal.agreement.judge_only == 1
    assert cal.disputes == [("cta.buried", "*", "judge invented")]


def test_deterministic_findings_are_not_scored_as_judgments():
    """Whether a contrast ratio is below 4.5 is arithmetic. A human re-deciding
    it is not calibrating anything."""
    det = Finding(code="contrast.aa_fail", module="deterministic",
                  severity=Severity.WILL_BREAK, target="x", message="m", remedy="r")
    cal = calibrate_sample("s.html", labels(("cta.buried", "*", True)), [det])
    assert cal.agreement.human_only == 1
    assert cal.agreement.judge_only == 0


def test_wildcard_label_matches_the_code_wherever_the_judge_put_it():
    cal = calibrate_sample(
        "s.html",
        labels(("cta.buried", "*", True)),
        [llm_finding("cta.buried", target="cta-button")],
    )
    assert cal.agreement.both_real == 1
    assert cal.agreement.judge_only == 0


def test_advisory_judgments_are_not_scored():
    """`scored` excludes COULD_BE_BETTER, and calibration honours the same rule
    the benchmark does."""
    cal = calibrate_sample(
        "s.html",
        labels(("cta.buried", "*", False)),
        [llm_finding("cta.buried", severity=Severity.COULD_BE_BETTER)],
    )
    assert cal.agreement.judge_only == 0
    assert cal.agreement.both_absent == 1


# --- the run-level contract -----------------------------------------------

def test_one_non_blind_label_set_makes_the_whole_run_non_blind():
    result = CalibrationResult(samples=[
        SampleCalibration("a.html", Agreement(1), blind=True),
        SampleCalibration("b.html", Agreement(1), blind=False),
    ])
    assert result.blind is False


def test_empty_labels_directory_reports_no_evidence_rather_than_a_score(tmp_path):
    assert load_labels(tmp_path) == {}


def test_labels_load_keyed_by_sample(tmp_path):
    (tmp_path / "sample_4_cta_spam.json").write_text(json.dumps({
        "sample": "sample_4_cta_spam.html",
        "labelled_by": "tester", "blind": True,
        "labels": [{"code": "cta.buried", "target": "*", "real": True}],
    }))
    loaded = load_labels(tmp_path)
    assert "sample_4_cta_spam.html" in loaded
    assert loaded["sample_4_cta_spam.html"]["labelled_by"] == "tester"


def test_result_serializes_the_numbers_a_reviewer_would_ask_for():
    result = CalibrationResult(
        samples=[SampleCalibration("a.html", Agreement(5, 1, 1, 5), blind=True)],
        provenance="live",
    )
    d = result.to_dict()
    assert d["confusion"] == {"both_real": 5, "judge_missed": 1,
                             "judge_invented": 1, "both_absent": 5}
    assert d["blind"] is True
    assert d["candidates"] == 12
    assert d["cohens_kappa"] is not None
