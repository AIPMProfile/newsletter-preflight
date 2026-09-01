"""Benchmark run history: append-only, and honest about a first run."""

from __future__ import annotations

import json

from preflight.evals import history

RESULT = {
    "llm_mode": "replayed (authored)",
    "overall": {"f1": 1.0, "precision": 1.0, "recall": 1.0},
    "modules": {"deterministic": {"f1": 1.0, "fp": 0, "fn": 0},
                "llm": {"f1": 1.0, "fp": 0, "fn": 0}},
    "clean_control_false_positives": 0,
    "verdict": {"accuracy": 1.0},
    "fix": {"resolution_rate": 0.95},
    "control_violations": [],
    "severity_drift": [],
    "cost": {"llm_degradation_rate": 0.0},
    "mean_latency_ms": 2.8,
    "sla_breaches": [],
}


def test_a_run_records_the_numbers_worth_alarming_on(tmp_path):
    row = history.record(RESULT, provider="gemini", model="m",
                         path=tmp_path / "h.jsonl", note="baseline")
    assert row["f1"] == 1.0
    assert row["verdict_accuracy"] == 1.0
    assert row["fix_resolution_rate"] == 0.95
    assert row["note"] == "baseline"
    assert row["model"] == "m"


def test_runs_append_and_are_never_rewritten(tmp_path):
    path = tmp_path / "h.jsonl"
    history.record(RESULT, provider="gemini", model="a", path=path)
    history.record(RESULT, provider="anthropic", model="b", path=path)
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    assert [r["model"] for r in rows] == ["a", "b"]


def test_a_regression_stays_visible_after_it_is_fixed(tmp_path):
    """The reason this is append-only. A history that only kept the latest run
    could not show that something broke and was repaired."""
    path = tmp_path / "h.jsonl"
    history.record(RESULT, provider="g", model="m", path=path)
    history.record({**RESULT, "overall": {"f1": 0.5}}, provider="g", model="m", path=path)
    history.record(RESULT, provider="g", model="m", path=path)
    assert [r["f1"] for r in history.load(path)] == [1.0, 0.5, 1.0]


def test_first_run_reports_no_delta_rather_than_inventing_a_baseline(tmp_path):
    """"F1 improved by 1.0" on run one is not information."""
    path = tmp_path / "h.jsonl"
    history.record(RESULT, provider="g", model="m", path=path)
    assert history.deltas(history.load(path)) == {}


def test_deltas_report_direction_between_the_last_two_runs(tmp_path):
    path = tmp_path / "h.jsonl"
    history.record(RESULT, provider="g", model="m", path=path)
    history.record({**RESULT, "overall": {"f1": 0.8},
                    "verdict": {"accuracy": 0.5}}, provider="g", model="m", path=path)
    d = history.deltas(history.load(path))
    assert d["f1"] == {"from": 1.0, "to": 0.8, "delta": -0.2}
    assert d["verdict_accuracy"]["delta"] == -0.5


def test_load_of_a_missing_log_is_empty_not_an_error(tmp_path):
    assert history.load(tmp_path / "nothing.jsonl") == []


def test_limit_returns_the_most_recent_runs(tmp_path):
    path = tmp_path / "h.jsonl"
    for i in range(5):
        history.record({**RESULT, "overall": {"f1": i / 10}},
                       provider="g", model="m", path=path)
    assert [r["f1"] for r in history.load(path, limit=2)] == [0.3, 0.4]


def test_the_log_path_is_overridable_so_tests_never_touch_the_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("PREFLIGHT_HISTORY_LOG", str(tmp_path / "custom.jsonl"))
    assert history.history_path() == tmp_path / "custom.jsonl"
