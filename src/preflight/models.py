"""Shared data contracts.

Every finding in the system is a `Finding`. The eval harness, the terminal
report, and the auto-fixer all key off `code` + `target`, so those two fields
are the stable public contract - change them and ground truth must change too.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """What this costs the creator, not how the engine classifies it.

    The old tiers were ERROR / WARN / INFO - an engineering taxonomy that told a
    creator nothing about whether to stop. These name the consequence, which is
    the only thing they can act on:

    * ``WILL_BREAK`` - the email does not work. A dead link, a Liquid tag that
      renders as literal text. Some subscribers hit a wall.
    * ``WILL_EMBARRASS`` - it works and it looks wrong. Unreadable contrast, a
      surface that inverts in dark mode, an image with no alt text.
    * ``COULD_BE_BETTER`` - advisory. Never blocks, never scored, and must never
      cost a creator a false positive.

    Only the first two participate in precision/recall (D27).
    """

    WILL_BREAK = "will_break"
    WILL_EMBARRASS = "will_embarrass"
    COULD_BE_BETTER = "could_be_better"


#: What a creator reads. The enum value is the wire format; this is the label.
SEVERITY_LABEL: dict[Severity, str] = {
    Severity.WILL_BREAK: "WILL BREAK",
    Severity.WILL_EMBARRASS: "WILL EMBARRASS",
    Severity.COULD_BE_BETTER: "COULD BE BETTER",
}

#: Ordering for display and sorting only. Deliberately not arithmetic: these
#: are ranks, and nothing sums them into a composite (D28).
SEVERITY_RANK: dict[Severity, int] = {
    Severity.WILL_BREAK: 0,
    Severity.WILL_EMBARRASS: 1,
    Severity.COULD_BE_BETTER: 2,
}

#: Verdicts, worst first.
HOLD, REVIEW, READY = "HOLD", "REVIEW", "READY"

Module = Literal["deterministic", "llm"]


class Finding(BaseModel):
    """One actionable problem found in an email."""

    code: str = Field(description="Stable dotted identifier, e.g. 'contrast.aa_fail'.")
    module: Module = "deterministic"
    severity: Severity = Severity.WILL_BREAK
    target: str = Field(description="Element id when present, else a css-ish path.")
    line: int | None = Field(default=None, description="1-indexed source line.")
    message: str = Field(
        description="What this costs the creator, in their words. No hex codes, "
                    "no ratios, no tag names - a sentence they can act on."
    )
    detail: str = Field(
        default="",
        description="The measurement behind the message. Shown on request, never "
                    "first: it is what a professional needs to defend the change, "
                    "and what a hobbyist does not need at all.",
    )
    remedy: str = Field(default="", description="What to do about it.")
    evidence: dict[str, Any] = Field(default_factory=dict)
    fixable: bool = False
    #: True when the only transformer that repairs this rewrites the creator's
    #: stylesheet, which is `fix --aggressive` and never the default. Findings
    #: like this are offered separately rather than counted in the one-click
    #: button, because a fix the button advertises and does not apply is a
    #: broken promise (D29).
    requires_aggressive: bool = False

    @property
    def key(self) -> tuple[str, str]:
        """Identity used for ground-truth matching."""
        return (self.code, self.target)

    @property
    def scored(self) -> bool:
        return self.severity is not Severity.COULD_BE_BETTER

    @property
    def blocking(self) -> bool:
        """Would this alone stop a send?"""
        return self.severity in (Severity.WILL_BREAK, Severity.WILL_EMBARRASS)

    @property
    def label(self) -> str:
        return SEVERITY_LABEL[self.severity]

    @property
    def fixable_now(self) -> bool:
        """Repairable by the default one-click fix."""
        return self.fixable and not self.requires_aggressive


class Timing(BaseModel):
    deterministic_ms: float = 0.0
    links_ms: float = 0.0
    llm_ms: float = 0.0
    total_ms: float = 0.0

    @property
    def presend_ms(self) -> float:
        """The phases that must feel instant: parsing, math, and link probing."""
        return self.deterministic_ms + self.links_ms

    @property
    def within_sla(self) -> bool:
        return self.presend_ms <= SLA_MS


#: Pre-send SLA, covering the deterministic engine and link probing - everything
#: that can be answered without a model. A pre-send check that makes you wait is
#: a check you skip.
#:
#: It deliberately excludes the intent reviewer. Measured on 2026-08-26, the
#: fastest live configuration (gemini-3.5-flash-lite at LOW) spent 2036ms on that
#: call alone, and the default model 3502ms - so no honest total-time SLA of 2s
#: exists while Module B is on. Rather than quietly miss the number or silently
#: disable the feature, the budget is stated for what it actually governs and the
#: reviewer's cost is reported next to it. See docs/PRODUCT_DECISIONS.md D18.
SLA_MS = 2000.0


class AuditReport(BaseModel):
    path: str
    findings: list[Finding] = Field(default_factory=list)
    timing: Timing = Field(default_factory=Timing)
    llm_status: str = "ok"
    stats: dict[str, Any] = Field(default_factory=dict)

    @property
    def verdict(self) -> str:
        """Can this go out?

        Three states, derived - not scored. There is no composite number here on
        purpose: the old 0-100 readiness score subtracted 12 per error and 5 per
        warning, weights nobody could defend, which is the same fabrication this
        tool refuses to commit for spam scores (D28).

        HOLD    something will break or embarrass. Do not send.
        REVIEW  nothing blocking, but we noted things worth a look.
        READY   nothing found.
        """
        if any(f.blocking for f in self.findings):
            return HOLD
        if self.findings:
            return REVIEW
        return READY

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    def by_module(self, module: Module) -> list[Finding]:
        return [f for f in self.findings if f.module == module]
