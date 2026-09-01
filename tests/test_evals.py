"""Module D: the benchmark corpus, ground truth, and the metrics themselves."""

import json

import pytest

from preflight.audit import audit_file
from preflight.evals.generate import GROUND_TRUTH, SAMPLES, write_all
from preflight.evals.harness import (
    CLEAN_CONTROL,
    Confusion,
    match,
    module_of,
    run_benchmark,
)
from preflight.fixer.autofix import liquid_tokens
from preflight.models import Finding, Severity


def _finding(code, target, severity=Severity.WILL_BREAK):
    return Finding(code=code, target=target, severity=severity, message="m")


def test_corpus_has_the_eight_declared_cases():
    assert len(SAMPLES) == 8
    assert set(SAMPLES) == set(GROUND_TRUTH)


def test_every_ground_truth_target_exists_in_its_sample(corpus, ground_truth):
    from preflight.parser import load
    for name, case in ground_truth["cases"].items():
        soup, _ = load((corpus / name).read_text())
        for entry in case["expected"]:
            if entry["target"] in ("*", "document"):
                continue
            # Liquid findings name a source position, not an element: a tag
            # that never closed has no DOM identity to point at. Envelope
            # findings name the subject or preview line, which live beside the
            # document rather than inside it.
            if entry["code"].startswith(("liquid.", "subject.", "preheader.")):
                continue
            assert soup.find(id=entry["target"]) is not None, \
                f"{name}: ground truth points at missing element #{entry['target']}"


def test_clean_control_declares_no_failures(ground_truth):
    assert ground_truth["cases"][CLEAN_CONTROL]["expected"] == []


def test_samples_carry_liquid_so_the_fixer_contract_is_exercised(corpus):
    assert liquid_tokens((corpus / "sample_5_mixed.html").read_text())


def test_broken_link_statuses_are_pinned(ground_truth):
    statuses = set(ground_truth["link_status"].values())
    assert 404 in statuses and 500 in statuses


@pytest.mark.parametrize("code,module", [
    ("contrast.aa_fail", "deterministic"),
    ("darkmode.no_bg_override", "deterministic"),
    ("link.broken", "deterministic"),
    ("spam.link_ratio", "deterministic"),
    ("spam.trigger_phrase", "llm"),
    ("cta.buried", "llm"),
    ("copy.cognitive_friction", "llm"),
])
def test_module_attribution(code, module):
    assert module_of(code) == module


def test_match_counts_hits_misses_and_spurious():
    findings = [_finding("contrast.aa_fail", "a"), _finding("link.broken", "b")]
    expected = [{"code": "contrast.aa_fail", "target": "a"},
                {"code": "img.missing_alt", "target": "c"}]
    det = match(findings, expected, "s")["deterministic"]
    assert (det.tp, det.fn, det.fp) == (1, 1, 1)


def test_match_ignores_info_findings():
    findings = [_finding("contrast.aaa_fail", "a", Severity.COULD_BE_BETTER)]
    det = match(findings, [], "s")["deterministic"]
    assert (det.tp, det.fp, det.fn) == (0, 0, 0)


def test_wildcard_target_matches_any_element():
    findings = [_finding("cta.buried", "whatever")]
    llm = match(findings, [{"code": "cta.buried", "target": "*"}], "s")["llm"]
    assert (llm.tp, llm.fp, llm.fn) == (1, 0, 0)


def test_wildcards_do_not_double_count_one_finding():
    findings = [_finding("spam.trigger_phrase", "h")]
    expected = [{"code": "spam.trigger_phrase", "target": "*"}] * 2
    llm = match(findings, expected, "s")["llm"]
    assert (llm.tp, llm.fn) == (1, 1)


def test_exact_targets_are_matched_before_wildcards():
    findings = [_finding("cta.buried", "cta")]
    expected = [{"code": "cta.buried", "target": "*"},
                {"code": "cta.buried", "target": "cta"}]
    llm = match(findings, expected, "s")["llm"]
    assert (llm.tp, llm.fn) == (1, 1)


@pytest.mark.parametrize("tp,fp,fn,p,r,f1", [
    (3, 1, 1, 0.75, 0.75, 0.75),
    (0, 0, 0, 1.0, 1.0, 1.0),
    (0, 2, 0, 0.0, 1.0, 0.0),
    (0, 0, 2, 1.0, 0.0, 0.0),
])
def test_metric_arithmetic(tp, fp, fn, p, r, f1):
    c = Confusion(tp=tp, fp=fp, fn=fn)
    assert c.precision == pytest.approx(p)
    assert c.recall == pytest.approx(r)
    assert c.f1 == pytest.approx(f1)


def test_confusion_addition_merges_evidence():
    a = Confusion(tp=1, fp=1, fp_items=[("s", "c", "t")])
    b = Confusion(tp=2, fn=1, fn_items=[("s2", "c2", "t2")])
    total = a + b
    assert (total.tp, total.fp, total.fn) == (3, 1, 1)
    assert total.fp_items and total.fn_items


def test_false_positive_rate_is_share_of_everything_reported():
    assert Confusion(tp=3, fp=1).false_positive_rate == pytest.approx(0.25)
    assert Confusion().false_positive_rate == 0.0


async def test_benchmark_meets_its_own_bar():
    result = await run_benchmark()
    totals = result.totals()
    assert totals["deterministic"].f1 == 1.0, totals["deterministic"].fn_items
    assert result.clean_control_fp == 0
    assert result.sla_breaches == []
    assert result.overall.f1 >= 0.9


async def test_benchmark_serializes_for_ci():
    payload = (await run_benchmark()).to_dict()
    json.dumps(payload)
    assert payload["modules"]["deterministic"]["f1"] == 1.0
    assert payload["llm_mode"].startswith("replayed")


async def test_clean_control_reaches_the_best_verdict(corpus, ground_truth):
    report = await audit_file(
        corpus / CLEAN_CONTROL, offline_links=ground_truth["link_status"], skip_llm=True
    )
    # READY is the strictest verdict - not one advisory note either. If the
    # negative control cannot reach it, READY is a tier nothing can ever hit.
    assert report.findings == []
    assert report.verdict == "READY"


async def test_every_sample_stays_inside_the_sla(corpus, ground_truth):
    for name in ground_truth["cases"]:
        report = await audit_file(
            corpus / name, offline_links=ground_truth["link_status"], skip_llm=True
        )
        assert report.timing.within_sla, f"{name} took {report.timing.total_ms}ms"


def test_regenerating_the_corpus_is_deterministic(corpus):
    before = {p.name: p.read_text() for p in corpus.glob("*.html")}
    write_all()
    after = {p.name: p.read_text() for p in corpus.glob("*.html")}
    assert before == after
