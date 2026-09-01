"""The improvement loop: what creators did, read against what each check promised.

The benchmark says whether a check is accurate. It cannot say whether the check
is *useful*, and those come apart constantly — "this text is 4.3:1" can be true
and still be a false alarm on a caption nobody was meant to read.

This reads four creator signals against each check's rubric and proposes what to
change. Three of the four are decisions; the fourth is the absence of one.

* **Approval** — they took the repair. The check was right and the fix was wanted.
* **Override** — they sent over the whole verdict. Says the product is wrong,
  not which part.
* **Dismissal** — they waved one finding through, with a reason. Only
  "flagged wrongly" is evidence against the check; "I meant it" is evidence
  about the creator.
* **Ignore** — shown, skipped, sent. The quietest signal and usually the loudest
  thing a check is being told. We assumed disagreement would be voiced; this
  audience does not hand-edit markup and will not argue with a panel.

And one measure that is not a decision at all: **time to decide.** A correct
finding that takes ninety seconds to act on has failed, because at that price
creators stop reading. Slow decisions are a wording problem, not an accuracy
one, and they get a different prescription.

## What "self-improving" is allowed to mean here

It proposes. It does not retune itself.

A check that quietly changes what it reports based on its own telemetry is a
check nobody can reason about, and the failure mode is vicious: creators ignore
a check because the wording is bad, the loop reads that as inaccuracy, loosens
the threshold, and the check stops catching the thing it existed for. Nobody
notices, because the number went the right way.

So every proposal names the signal, the rubric half it points at, and the lever
its own rubric nominates — and waits for a person. The floor on evidence is the
same one the kill criteria use: below it, a rate is a rumour.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .rubrics import RUBRICS, rubric_for

#: Below this many decisions about a check, every rate here is noise.
MIN_DECISIONS = 20

#: Waved through as "flagged wrongly" this often - the check is wrong.
FALSE_ALARM_AT = 0.40

#: Shown and skipped this often - the check is not landing, whatever its accuracy.
IGNORE_AT = 0.60

#: Decisions taking longer than the rubric's budget, this often - a wording
#: problem rather than an accuracy one.
SLOW_AT = 0.50


@dataclass
class Verdict:
    """What the evidence says about one check, and what to do about it."""

    code: str
    decisions: int = 0
    approved: int = 0
    dismissed: int = 0
    false_alarms: int = 0
    intentional: int = 0
    ignored: int = 0
    shown: int = 0
    slow: int = 0
    times: list[float] = field(default_factory=list)

    def _rate(self, n: int, of: int) -> float | None:
        return n / of if of else None

    @property
    def approval_rate(self) -> float | None:
        return self._rate(self.approved, self.decisions)

    @property
    def false_alarm_rate(self) -> float | None:
        return self._rate(self.false_alarms, self.decisions)

    @property
    def ignore_rate(self) -> float | None:
        return self._rate(self.ignored, self.shown)

    @property
    def slow_rate(self) -> float | None:
        return self._rate(self.slow, len(self.times))

    @property
    def median_decide_sec(self) -> float | None:
        if not self.times:
            return None
        ordered = sorted(self.times)
        return ordered[len(ordered) // 2]

    @property
    def underpowered(self) -> bool:
        return self.decisions < MIN_DECISIONS

    def proposal(self) -> dict | None:
        """What to change, or None while the check is holding up.

        Ordered by how confidently the signal can be read. A creator saying
        "this is flagged wrongly" is unambiguous. Silence is not, so it is
        checked second and phrased as a question about wording rather than
        accuracy.
        """
        if self.underpowered:
            return None
        r = rubric_for(self.code)
        lever = r.first_lever if r else "No rubric — write one before changing anything."

        if (self.false_alarm_rate or 0) >= FALSE_ALARM_AT:
            return {
                "code": self.code,
                "signal": "false alarms",
                "reading": "Creators are telling us this check is wrong, not that "
                           "they disagree with it.",
                "drifted_into": r.bad if r else "",
                "propose": lever,
                "severity": "recalibrate",
            }

        if (self.ignore_rate or 0) >= IGNORE_AT:
            return {
                "code": self.code,
                "signal": "ignored",
                "reading": "Shown and skipped. Nobody is arguing with it, which "
                           "usually means it is not worth arguing with - either it "
                           "does not matter or we have not said why it does.",
                "drifted_into": r.bad if r else "",
                "propose": "Rewrite what it costs the creator, and only then "
                           "question whether the check earns its place.",
                "severity": "rewrite",
            }

        if (self.slow_rate or 0) >= SLOW_AT:
            budget = r.decides_in if r else 0
            return {
                "code": self.code,
                "signal": "slow decisions",
                "reading": f"Half of decisions take longer than the {budget}s this "
                           f"check should need. That is comprehension, not accuracy - "
                           f"the finding is probably right and badly worded.",
                "drifted_into": "",
                "propose": "Shorten the message and lead harder with the consequence. "
                           "Do not touch the check.",
                "severity": "reword",
            }
        return None


def read(rows: list[dict]) -> dict[str, Verdict]:
    """Score every check that has creator evidence against its rubric."""
    actions = [r for r in rows if r.get("kind") == "action" and r.get("code")]
    out: dict[str, Verdict] = defaultdict(lambda: Verdict(code=""))

    for row in actions:
        code = row["code"]
        v = out[code]
        v.code = code
        v.shown += 1

        act = row.get("action")
        if act == "IGNORED":
            v.ignored += 1
            continue                      # not a decision; no time to judge

        v.decisions += 1
        if act == "AUTO_FIXED":
            v.approved += 1
        elif act == "DISMISSED":
            v.dismissed += 1
            if row.get("reason") == "FALSE_ALARM":
                v.false_alarms += 1
            elif row.get("reason") == "INTENTIONAL_DESIGN":
                v.intentional += 1

        t = row.get("decided_in_sec")
        if isinstance(t, (int, float)):
            v.times.append(float(t))
            r = rubric_for(code)
            if r and t > r.decides_in:
                v.slow += 1

    return dict(out)


def proposals(rows: list[dict]) -> list[dict]:
    """Everything the evidence currently supports changing, worst first."""
    order = {"recalibrate": 0, "rewrite": 1, "reword": 2}
    found = [p for v in read(rows).values() if (p := v.proposal())]
    return sorted(found, key=lambda p: order.get(p["severity"], 9))


def coverage(rows: list[dict]) -> dict:
    """How much of the product the evidence can actually speak to.

    Reported beside every proposal. Nine checks with enough evidence out of
    sixteen means seven are running on nobody's opinion, and a summary that
    hides that invites reading silence as approval.
    """
    verdicts = read(rows)
    powered = [c for c, v in verdicts.items() if not v.underpowered]
    return {
        "checks_total": len(RUBRICS),
        "checks_with_evidence": len(verdicts),
        "checks_with_enough_evidence": len(powered),
        "min_decisions": MIN_DECISIONS,
        "unheard": sorted(set(RUBRICS) - set(verdicts)),
    }


def summary(rows: list[dict]) -> dict:
    verdicts = read(rows)
    return {
        "coverage": coverage(rows),
        "proposals": proposals(rows),
        "checks": {
            code: {
                "decisions": v.decisions,
                "shown": v.shown,
                "approval_rate": v.approval_rate,
                "false_alarm_rate": v.false_alarm_rate,
                "ignore_rate": v.ignore_rate,
                "median_decide_sec": v.median_decide_sec,
                "budget_sec": (rubric_for(code).decides_in if rubric_for(code) else None),
                "underpowered": v.underpowered,
            }
            for code, v in sorted(verdicts.items())
        },
        "signals_seen": dict(Counter(
            r.get("action") for r in rows if r.get("kind") == "action")),
    }
