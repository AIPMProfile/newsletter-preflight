"""Module D (part 3) - judge calibration.

Module B's F1 against an authored fixture measures the harness, not the model.
This module measures the model: it compares the reviewer's judgments against
labels a human wrote independently, and reports the agreement statistic.

Why Cohen's kappa and not raw agreement: the reviewer and the labeller mostly
agree that most things are fine, so raw agreement is inflated by the empty
cells. Kappa discounts the agreement you would expect from two raters guessing
at the same base rate, which is the only number that survives a sparse label
set honestly.

The unit of agreement is one `(code, target)` candidate per sample. The
candidate universe is the union of what the human labelled and what the judge
emitted, so a judgment counts whether it was invented by the model or missed by
it. Both raters then answer one binary question per candidate: is this real?

Labels live in `evals/labels/<sample>.json`:

    {
      "sample": "sample_4_cta_spam.html",
      "labelled_by": "who",
      "labelled_at": "2026-08-29",
      "blind": true,
      "labels": [
        {"code": "cta.buried", "target": "*", "real": true},
        {"code": "spam.trigger_phrase", "target": "*", "real": true}
      ]
    }

`blind` records whether the labeller had seen the model's output first. A label
set written while looking at the judge's answer is not an independent rater, and
the report says so rather than folding it into the headline number.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..models import Finding

LABELS_DIR = Path(__file__).parent / "labels"


@dataclass
class Agreement:
    """A 2x2 confusion between one human labeller and the judge."""

    both_real: int = 0      # human yes, judge yes
    human_only: int = 0     # human yes, judge no  -> judge missed it
    judge_only: int = 0     # human no,  judge yes -> judge invented it
    both_absent: int = 0    # neither, only reachable when a label says "not real"

    @property
    def n(self) -> int:
        return self.both_real + self.human_only + self.judge_only + self.both_absent

    @property
    def observed(self) -> float:
        """Raw agreement. Reported alongside kappa, never instead of it."""
        return (self.both_real + self.both_absent) / self.n if self.n else 0.0

    @property
    def expected(self) -> float:
        """Agreement two raters would reach by chance at these base rates."""
        if not self.n:
            return 0.0
        n = self.n
        human_yes = (self.both_real + self.human_only) / n
        judge_yes = (self.both_real + self.judge_only) / n
        return human_yes * judge_yes + (1 - human_yes) * (1 - judge_yes)

    @property
    def kappa(self) -> float | None:
        """Cohen's kappa, or None when it is undefined.

        When both raters mark everything the same way there is no variance to
        correct for and the statistic is undefined - reporting 0.0 there would
        read as total disagreement, which is the opposite of what happened.
        """
        if not self.n:
            return None
        pe = self.expected
        if abs(1.0 - pe) < 1e-12:
            return None
        return (self.observed - pe) / (1 - pe)

    def __add__(self, other: "Agreement") -> "Agreement":
        return Agreement(
            self.both_real + other.both_real,
            self.human_only + other.human_only,
            self.judge_only + other.judge_only,
            self.both_absent + other.both_absent,
        )


@dataclass
class SampleCalibration:
    sample: str
    agreement: Agreement
    labelled_by: str = ""
    blind: bool = True
    disputes: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class CalibrationResult:
    samples: list[SampleCalibration]
    provenance: str = "none"

    @property
    def total(self) -> Agreement:
        out = Agreement()
        for s in self.samples:
            out = out + s.agreement
        return out

    @property
    def blind(self) -> bool:
        """One non-blind label set makes the whole run non-blind."""
        return all(s.blind for s in self.samples)

    @property
    def labelled_samples(self) -> int:
        return len(self.samples)

    def to_dict(self) -> dict:
        t = self.total
        return {
            "provenance": self.provenance,
            "blind": self.blind,
            "labelled_samples": self.labelled_samples,
            "candidates": t.n,
            "observed_agreement": round(t.observed, 4),
            "expected_agreement": round(t.expected, 4),
            "cohens_kappa": None if t.kappa is None else round(t.kappa, 4),
            "confusion": {
                "both_real": t.both_real,
                "judge_missed": t.human_only,
                "judge_invented": t.judge_only,
                "both_absent": t.both_absent,
            },
            "samples": [
                {
                    "sample": s.sample,
                    "labelled_by": s.labelled_by,
                    "blind": s.blind,
                    "kappa": None if s.agreement.kappa is None else round(s.agreement.kappa, 4),
                    "disputes": [
                        {"code": c, "target": t_, "who": w} for c, t_, w in s.disputes
                    ],
                }
                for s in self.samples
            ],
        }


def interpret(kappa: float | None) -> str:
    """Landis & Koch bands, named so a number does not have to be interpreted
    from memory in a review."""
    if kappa is None:
        return "undefined - no disagreement to correct for"
    if kappa < 0.0:
        return "worse than chance"
    if kappa < 0.21:
        return "slight"
    if kappa < 0.41:
        return "fair"
    if kappa < 0.61:
        return "moderate"
    if kappa < 0.81:
        return "substantial"
    return "almost perfect"


def load_labels(labels_dir: Path = LABELS_DIR) -> dict[str, dict]:
    if not labels_dir.exists():
        return {}
    out: dict[str, dict] = {}
    for path in sorted(labels_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        out[payload.get("sample", path.stem + ".html")] = payload
    return out


def calibrate_sample(sample: str, labels: dict, findings: list[Finding]) -> SampleCalibration:
    """Score one sample's judge output against one human label set.

    Only LLM-module findings participate. The deterministic checks are
    arithmetic - a human labelling whether a contrast ratio is really below 4.5
    is not calibrating a judge, they are re-doing multiplication.
    """
    from .harness import module_of

    human_real = {(e["code"], e["target"]) for e in labels.get("labels", []) if e.get("real", True)}
    human_not = {(e["code"], e["target"]) for e in labels.get("labels", []) if not e.get("real", True)}
    judged = {(f.code, f.target) for f in findings if module_of(f.code) == "llm" and f.scored}

    # Wildcard labels match the code wherever the judge put it: which element
    # carries the blame for a buried CTA is exactly the thing ground truth
    # already refuses to pin down.
    def seen(code: str, target: str) -> bool:
        return (code, target) in judged or (target == "*" and any(c == code for c, _ in judged))

    agreement = Agreement()
    disputes: list[tuple[str, str, str]] = []

    for code, target in sorted(human_real):
        if seen(code, target):
            agreement.both_real += 1
        else:
            agreement.human_only += 1
            disputes.append((code, target, "judge missed"))
    for code, target in sorted(human_not):
        if seen(code, target):
            agreement.judge_only += 1
            disputes.append((code, target, "judge invented"))
        else:
            agreement.both_absent += 1

    matched = {c for c, _ in human_real} | {c for c, _ in human_not}
    for code, target in sorted(judged):
        if (code, target) in human_real or (code, target) in human_not:
            continue
        if any(c == code and t == "*" for c, t in human_real | human_not):
            continue
        if code in matched:
            continue
        agreement.judge_only += 1
        disputes.append((code, target, "judge invented"))

    return SampleCalibration(
        sample=sample,
        agreement=agreement,
        labelled_by=labels.get("labelled_by", ""),
        blind=bool(labels.get("blind", True)),
        disputes=disputes,
    )


async def run_calibration(live_llm: bool = False, labels_dir: Path = LABELS_DIR) -> CalibrationResult:
    """Compare the reviewer against every label set on disk.

    Runs the benchmark rather than re-implementing the audit, so calibration
    always scores the same output the benchmark scored.
    """
    from .harness import run_benchmark

    labels = load_labels(labels_dir)
    if not labels:
        return CalibrationResult(samples=[], provenance="live" if live_llm else "none")

    result = await run_benchmark(live_llm=live_llm, score_fix=False)
    out: list[SampleCalibration] = []
    for case in result.cases:
        if case.sample not in labels:
            continue
        out.append(calibrate_sample(case.sample, labels[case.sample], case.report.findings))
    return CalibrationResult(
        samples=out,
        provenance="live" if live_llm else result.llm_provenance,
    )
