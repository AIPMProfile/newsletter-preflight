"""Module D (part 2) - the benchmark harness.

Scoring rules, stated up front because they determine what the numbers mean:

* A finding matches ground truth on `(code, target)`. Ground-truth entries with
  target `"*"` match that code anywhere in the file - used only for LLM
  judgments, where which element carries the blame is genuinely arguable.
* Matching is asymmetric, on purpose. Ground truth may expect an advisory
  finding, so recall covers everything the corpus has an opinion about - but an
  *unexpected* advisory is never a false positive. Otherwise a tier would have
  to be chosen for how it scores rather than for what it costs a creator, which
  is exactly backwards (D30).
* Modules are scored separately. A strong contrast engine must not be able to
  hide a weak LLM reviewer inside one blended F1.
* `sample_6_clean.html` is the negative control: every scored finding there is a
  false positive, tracked on its own line, because a tool that cries wolf on a
  clean send is a tool creators stop opening.
* Severity is part of the match key for deterministic findings only. A check
  that emits the right code at the wrong severity moves both the readiness score
  and the verdict, so it is not a clean hit. LLM entries carry no expected
  severity: it is the model's judgment, supplied by an authored fixture, and
  pinning it would score the author against themselves (D21).
* `forbidden` entries are named negative expectations, checked against every
  finding including INFO, and cross-checked against `expected` so ground truth
  cannot contradict itself (D22).
* The benchmark scores the whole product, not just detection: `expected_verdict`
  scores the one output a creator acts on, and the fix pass scores whether the
  repairs the agent offers actually land (D23).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..audit import audit_file, audit_html
from ..models import AuditReport, Finding
from .generate import SAMPLES_DIR, load_ground_truth, write_all

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CLEAN_CONTROL = "sample_6_clean.html"

LLM_CODE_PREFIXES = ("cta.", "copy.")
LLM_CODES = {"spam.trigger_phrase"}


def module_of(code: str) -> str:
    if code.startswith(LLM_CODE_PREFIXES) or code in LLM_CODES:
        return "llm"
    return "deterministic"


@dataclass
class Confusion:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    fp_items: list[tuple[str, str, str]] = field(default_factory=list)
    fn_items: list[tuple[str, str, str]] = field(default_factory=list)
    severity_items: list[tuple[str, str, str, str, str]] = field(default_factory=list)

    def __add__(self, other: "Confusion") -> "Confusion":
        return Confusion(
            self.tp + other.tp, self.fp + other.fp, self.fn + other.fn,
            self.fp_items + other.fp_items, self.fn_items + other.fn_items,
            self.severity_items + other.severity_items,
        )

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def false_positive_rate(self) -> float:
        """Share of everything the agent reported that was not real."""
        reported = self.tp + self.fp
        return self.fp / reported if reported else 0.0


def match(findings: list[Finding], expected: list[dict], sample: str) -> dict[str, "Confusion"]:
    """Greedy match: exact `(code, target)` first, then wildcard targets.

    Where an entry declares a `severity`, the finding must carry it too. The
    miss is recorded as a severity mismatch rather than a plain false negative,
    so a drifting severity is visible without being confused for a missed check.
    """
    # Every finding is available to match an expectation; only scored leftovers
    # can become false positives. See the asymmetry note in the module docstring.
    remaining = list(findings)
    out = {"deterministic": Confusion(), "llm": Confusion()}

    exact = [e for e in expected if e["target"] != "*"]
    wild = [e for e in expected if e["target"] == "*"]

    for entry in exact:
        bucket = out[module_of(entry["code"])]
        hit = next((f for f in remaining if f.key == (entry["code"], entry["target"])), None)
        if hit is not None and entry.get("severity") and hit.severity.value != entry["severity"]:
            # Right check, wrong weight. Counted as a miss so it cannot pass
            # silently, and itemized so the report can name the drift.
            remaining.remove(hit)
            bucket.fn += 1
            bucket.fn_items.append((sample, entry["code"], entry["target"]))
            bucket.severity_items.append(
                (sample, entry["code"], entry["target"], entry["severity"], hit.severity.value))
            continue
        if hit is not None:
            remaining.remove(hit)
            bucket.tp += 1
        else:
            bucket.fn += 1
            bucket.fn_items.append((sample, entry["code"], entry["target"]))
    for entry in wild:
        hit = next((f for f in remaining if f.code == entry["code"]), None)
        bucket = out[module_of(entry["code"])]
        if hit is not None:
            remaining.remove(hit)
            bucket.tp += 1
        else:
            bucket.fn += 1
            bucket.fn_items.append((sample, entry["code"], "*"))
    for leftover in remaining:
        if not leftover.scored:
            continue          # advisory noise costs the creator nothing
        bucket = out[module_of(leftover.code)]
        bucket.fp += 1
        bucket.fp_items.append((sample, leftover.code, leftover.target))
    return out


def check_forbidden(findings: list[Finding], forbidden: list[dict], sample: str) -> list[tuple]:
    """Named negative expectations, violated.

    Deliberately checked against *every* finding, INFO included: a control says
    "this element is correct", and an advisory note on a correct element is
    still the agent contradicting a stated fact about the corpus. Plain false
    positives only ever look at scored findings, so this sees what they cannot.
    """
    violations: list[tuple] = []
    for entry in forbidden:
        code, target = entry["code"], entry["target"]
        for f in findings:
            if f.code != code:
                continue
            if target == "*" or f.target == target:
                violations.append((sample, code, f.target, f.severity.value))
    return violations


def truth_contradictions(cases: dict) -> list[str]:
    """Ground truth that asserts a finding is both required and forbidden.

    This is the guard on rule 4. The cheapest way to make a failing benchmark
    pass is to move the goalposts - add the finding you are emitting to
    `expected`. If a control already said that element was clean, the corpus now
    says two opposite things, and the run refuses rather than reporting a win.
    """
    problems: list[str] = []
    for sample, case in cases.items():
        exact = {(e["code"], e["target"]) for e in case.get("expected", [])}
        codes = {e["code"] for e in case.get("expected", [])}
        for entry in case.get("forbidden", []):
            code, target = entry["code"], entry["target"]
            if (code, target) in exact:
                problems.append(f"{sample}: {code}@{target} is both expected and forbidden")
            elif target == "*" and code in codes:
                problems.append(f"{sample}: {code} is forbidden everywhere but expected")
    return problems


@dataclass
class FixOutcome:
    """Did the repairs the agent offered actually land?

    Detection is only half the promise. `fix` rewrites the creator's HTML, so
    the benchmark measures the rewrite too: what fraction of fixable findings it
    resolved, whether it left Liquid untouched, and whether re-running it is a
    no-op.
    """
    sample: str
    fixable_before: int = 0
    resolved: int = 0
    liquid_safe: bool = True
    converged: bool = True
    verdict_before: str = ""
    verdict_after: str = ""
    #: Codes the default fix left behind that `--aggressive` does resolve.
    needs_aggressive: list[str] = field(default_factory=list)

    @property
    def resolution_rate(self) -> float:
        return self.resolved / self.fixable_before if self.fixable_before else 1.0

    @property
    def clean(self) -> bool:
        return self.liquid_safe and self.converged


@dataclass
class CaseResult:
    sample: str
    description: str
    report: AuditReport
    per_module: dict[str, Confusion]
    expected_count: int
    expected_verdict: str = ""
    control_violations: list[tuple] = field(default_factory=list)
    fix: "FixOutcome | None" = None

    @property
    def total(self) -> Confusion:
        return self.per_module["deterministic"] + self.per_module["llm"]

    @property
    def verdict_ok(self) -> bool:
        """No expectation recorded is not a pass - it is an unscored case."""
        return bool(self.expected_verdict) and self.report.verdict == self.expected_verdict


@dataclass
class BenchmarkResult:
    cases: list[CaseResult]
    live_llm: bool
    llm_provenance: str

    def totals(self) -> dict[str, Confusion]:
        agg = {"deterministic": Confusion(), "llm": Confusion()}
        for case in self.cases:
            for key in agg:
                agg[key] = agg[key] + case.per_module[key]
        return agg

    @property
    def overall(self) -> Confusion:
        t = self.totals()
        return t["deterministic"] + t["llm"]

    @property
    def clean_control_fp(self) -> int:
        for case in self.cases:
            if case.sample == CLEAN_CONTROL:
                return case.total.fp
        return 0

    @property
    def sla_breaches(self) -> list[str]:
        return [c.sample for c in self.cases if not c.report.timing.within_sla]

    @property
    def verdict_accuracy(self) -> float:
        scored = [c for c in self.cases if c.expected_verdict]
        if not scored:
            return 0.0
        return sum(1 for c in scored if c.verdict_ok) / len(scored)

    @property
    def verdict_misses(self) -> list[tuple[str, str, str]]:
        return [(c.sample, c.expected_verdict, c.report.verdict)
                for c in self.cases if c.expected_verdict and not c.verdict_ok]

    @property
    def control_violations(self) -> list[tuple]:
        return [v for c in self.cases for v in c.control_violations]

    @property
    def severity_drift(self) -> list[tuple]:
        return [d for c in self.cases for m in c.per_module.values() for d in m.severity_items]

    @property
    def fix_resolution_rate(self) -> float:
        """Pooled, not averaged per sample: a sample with one fixable finding
        must not weigh the same as one with eleven."""
        outcomes = [c.fix for c in self.cases if c.fix is not None]
        fixable = sum(o.fixable_before for o in outcomes)
        return sum(o.resolved for o in outcomes) / fixable if fixable else 1.0

    @property
    def unsafe_fixes(self) -> list[str]:
        return [o.sample for c in self.cases if (o := c.fix) is not None and not o.clean]

    @property
    def mis_advertised_fixes(self) -> list[tuple[str, str]]:
        """(sample, code) marked fixable that only `--aggressive` repairs."""
        return [(o.sample, code) for c in self.cases if (o := c.fix) is not None
                for code in o.needs_aggressive]

    @property
    def llm_degradation_rate(self) -> float:
        """Share of cases where the reviewer did not return a real assessment."""
        if not self.cases:
            return 0.0
        ok = {"ok", "replayed"}
        return sum(1 for c in self.cases if c.report.llm_status not in ok) / len(self.cases)

    @property
    def mean_llm_ms(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.report.timing.llm_ms for c in self.cases) / len(self.cases)

    @property
    def mean_latency_ms(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.report.timing.total_ms for c in self.cases) / len(self.cases)

    def to_dict(self) -> dict:
        totals = self.totals()
        return {
            "llm_mode": "live" if self.live_llm else f"replayed ({self.llm_provenance})",
            "modules": {
                name: {
                    "precision": round(c.precision, 4),
                    "recall": round(c.recall, 4),
                    "f1": round(c.f1, 4),
                    "tp": c.tp, "fp": c.fp, "fn": c.fn,
                    "false_positive_rate": round(c.false_positive_rate, 4),
                }
                for name, c in totals.items()
            },
            "overall": {
                "precision": round(self.overall.precision, 4),
                "recall": round(self.overall.recall, 4),
                "f1": round(self.overall.f1, 4),
                "false_positive_rate": round(self.overall.false_positive_rate, 4),
            },
            "clean_control_false_positives": self.clean_control_fp,
            "control_violations": [
                {"sample": s, "code": c, "target": t, "severity": sev}
                for s, c, t, sev in self.control_violations
            ],
            "severity_drift": [
                {"sample": s, "code": c, "target": t, "expected": e, "actual": a}
                for s, c, t, e, a in self.severity_drift
            ],
            "verdict": {
                "accuracy": round(self.verdict_accuracy, 4),
                "misses": [{"sample": s, "expected": e, "actual": a}
                           for s, e, a in self.verdict_misses],
            },
            "fix": {
                "resolution_rate": round(self.fix_resolution_rate, 4),
                "unsafe": self.unsafe_fixes,
                "mis_advertised": [{"sample": s, "code": c}
                                   for s, c in self.mis_advertised_fixes],
                "cases": [
                    {"sample": o.sample, "fixable": o.fixable_before, "resolved": o.resolved,
                     "liquid_safe": o.liquid_safe, "converged": o.converged,
                     "verdict": [o.verdict_before, o.verdict_after],
                     "needs_aggressive": o.needs_aggressive}
                    for c in self.cases if (o := c.fix) is not None
                ],
            },
            "cost": {
                "llm_degradation_rate": round(self.llm_degradation_rate, 4),
                "mean_llm_ms": round(self.mean_llm_ms, 2),
            },
            "mean_latency_ms": round(self.mean_latency_ms, 2),
            "sla_breaches": self.sla_breaches,
            "cases": [
                {
                    "sample": c.sample,
                    "blocking": len(c.report.blocking_findings),
                    "verdict": c.report.verdict,
                    "expected": c.expected_count,
                    "tp": c.total.tp, "fp": c.total.fp, "fn": c.total.fn,
                    "latency_ms": c.report.timing.total_ms,
                }
                for c in self.cases
            ],
        }


def _fixture_for(sample: str) -> Path | None:
    path = FIXTURES_DIR / (Path(sample).stem + ".json")
    return path if path.exists() else None


def _provenance(sample: str) -> str:
    path = _fixture_for(sample)
    if path is None:
        return "none"
    return json.loads(path.read_text()).get("provenance", "unknown")


async def _score_fix(path: Path, report: AuditReport, link_status: dict) -> "FixOutcome":
    """Run the fixer over a sample and measure what actually changed.

    Re-audits with the same pinned link statuses so the only difference between
    the two reports is the rewrite.

    Measured through `fix_document`, which is what `preflight fix` and the web
    UI both call - not the single-pass `apply_fixes` primitive underneath it.
    That distinction matters: repairing contrast changes a colour, which can
    create a new dark-mode finding, so one pass genuinely is not enough and
    `fix_document` loops for exactly that reason. Scoring the primitive would
    report a defect the product does not have.

    Convergence is "another pass applies no fixes", not "another pass returns an
    identical string". Re-serializing normalizes indentation, so byte equality
    measures the parser's whitespace handling rather than the fixer's
    idempotence - the CLI already tells creators as much.

    Resolution is measured against the *non-aggressive* fixer, because that is
    what the one-click button calls. Findings that only the aggressive pass can
    repair are recorded separately rather than being quietly forgiven: a finding
    marked fixable that the default fix does not resolve is a promise the UI
    makes and does not keep.
    """
    from ..fixer.autofix import apply_fixes, fix_document, liquid_tokens

    source = path.read_text()
    # `fixable_now` and not `fixable`: the one-click fix is what is being
    # measured, and it deliberately does not touch the creator's stylesheet.
    fixable = [f for f in report.findings if f.fixable_now and f.scored]
    outcome = FixOutcome(
        sample=path.name,
        fixable_before=len(fixable),
        verdict_before=report.verdict,
    )
    if not fixable:
        outcome.verdict_after = report.verdict
        return outcome

    fixed, _, after = await fix_document(source, offline_links=link_status)
    outcome.liquid_safe = liquid_tokens(fixed) == liquid_tokens(source)

    still = {f.key for f in after.findings}
    outcome.resolved = sum(1 for f in fixable if f.key not in still)
    outcome.verdict_after = after.verdict

    _, second = apply_fixes(fixed, after.findings)
    outcome.converged = not second

    unresolved = [f for f in fixable if f.key in still]
    if unresolved:
        # Does the opt-in pass close the gap? If so the finding is not
        # unfixable, it is mis-advertised - and that distinction is the
        # actionable one.
        _, _, deep = await fix_document(source, offline_links=link_status, aggressive=True)
        deep_keys = {f.key for f in deep.findings}
        outcome.needs_aggressive = sorted(
            {f.code for f in unresolved if f.key not in deep_keys})
    return outcome


async def run_benchmark(live_llm: bool = False, samples_dir: Path = SAMPLES_DIR,
                        score_fix: bool = True) -> BenchmarkResult:
    if not samples_dir.exists() or not any(samples_dir.glob("*.html")):
        write_all()
    truth = load_ground_truth()
    contradictions = truth_contradictions(truth["cases"])
    if contradictions:
        # Refuse to report a number computed from a corpus that disagrees with
        # itself. A benchmark that scores against contradictory truth is worse
        # than no benchmark: it produces a confident, meaningless figure.
        raise ValueError("Ground truth contradicts itself:\n  " + "\n  ".join(contradictions))
    link_status = truth["link_status"]
    cases: list[CaseResult] = []
    provenances: set[str] = set()

    for sample, case in truth["cases"].items():
        fixture = None if live_llm else _fixture_for(sample)
        if not live_llm:
            provenances.add(_provenance(sample))
        envelope = case.get("envelope") or {}
        report = await audit_file(
            samples_dir / sample,
            offline_links=link_status,
            llm_fixture=fixture,
            skip_llm=(not live_llm) and fixture is None,
            subject=envelope.get("subject", ""),
            preheader=envelope.get("preheader", ""),
        )
        cases.append(CaseResult(
            sample=sample,
            description=case.get("description", ""),
            report=report,
            per_module=match(report.findings, case["expected"], sample),
            expected_count=len(case["expected"]),
            expected_verdict=case.get("expected_verdict", ""),
            control_violations=check_forbidden(
                report.findings, case.get("forbidden", []), sample),
            fix=await _score_fix(samples_dir / sample, report, link_status) if score_fix else None,
        ))
    provenance = "live" if live_llm else "/".join(sorted(provenances)) or "none"
    return BenchmarkResult(cases=cases, live_llm=live_llm, llm_provenance=provenance)


def run_benchmark_sync(live_llm: bool = False) -> BenchmarkResult:
    return asyncio.run(run_benchmark(live_llm=live_llm))
