"""Phase 2 - what the agent sees after it ships.

The benchmark answers "how did we do on these six files". It cannot answer "is
the agent still behaving on the mail people are actually sending", and the
checks here have real reasons to drift: `link.broken` depends on the live web,
dark-mode behaviour changes as clients change, and export HTML changes whenever
an ESP updates its templates. A check calibrated once rots quietly.

Scope is deliberately small. This is a solo tool, not a fleet:

* One JSONL line per audit - counts, verdict, timings, and what the creator did.
* **No email content, ever.** Not the HTML, not the subject, not a URL. A
  `sha256` prefix of the document identifies repeat audits of the same file
  without storing anything that could be read back.
* Opt-in. `PREFLIGHT_MONITOR=1` turns it on; the default is off, because a
  pre-send tool that starts writing files nobody asked for is a tool people
  stop trusting with their drafts.

What it is for: watching the finding mix, not individual sends. If
`darkmode.no_bg_override` jumps from a fifth of documents to nearly all of them,
either the world changed or a check broke - and that is visible in the
distribution long before anyone thinks to re-run the benchmark.

It also records **what the creator did about it**, which is the harder and more
useful half. An audit log that only stores what the agent found measures the
agent; the questions worth answering are behavioural:

* **Override rate** - saw HOLD, sent anyway. The credibility metric. A creator
  who overrides is telling us the verdict was wrong, and they are usually right.
* **Action rate on HOLD** - saw HOLD, changed something first. What the tool is
  for.
* **Fix acceptance** - kept the one-click repair rather than undoing it.
* **Time to resolve** - the tax this adds to shipping.

Nothing infers these. They are written when the surface observes them, and the
metrics report `n` alongside every rate so a number computed from four sends
cannot be mistaken for a trend (D31).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .models import AuditReport

DEFAULT_LOG = Path.home() / ".preflight" / "audits.jsonl"

#: What a creator did after seeing the report.
#:
#: `ABANDONED` is deliberately absent from anything the app writes: "closed the
#: tab and never came back" cannot be observed from inside a request, and
#: inventing it from a timeout would be a guess dressed as data.
ACTIONS = ("AUTO_FIXED", "MANUALLY_EDITED", "OVERRIDDEN", "SENT_CLEAN",
           "DISMISSED", "IGNORED", "ABANDONED")

#: `IGNORED` is the signal the first version of this file could not see.
#:
#: We assumed a creator who disagreed would say so. Most will not: this audience
#: does not hand-edit markup and will not argue with a panel - they scroll past
#: it and send. A finding shown, understood well enough to skip, and left
#: untouched is feedback, and it was landing nowhere.
#:
#: Written at send for every finding still open and never acted on. Not the same
#: as a dismissal: dismissing is a decision, ignoring is the absence of one, and
#: they mean different things about the check (D38).

#: Why a creator waved a specific finding through.
DISMISS_REASONS = ("INTENTIONAL_DESIGN", "FALSE_ALARM", "FIX_LATER")

#: Read against a check's rubric in `evals/loop.py`, which owns every rate that
#: judges a check. Kept here only as the shared floor: below this many
#: decisions a rate is a rumour, and acting on a rumour is the more expensive
#: mistake.
MIN_DECISIONS = 20


def log_path() -> Path:
    return Path(os.getenv("PREFLIGHT_MONITOR_LOG", str(DEFAULT_LOG))).expanduser()


def enabled() -> bool:
    return os.getenv("PREFLIGHT_MONITOR", "").strip().lower() in {"1", "true", "yes", "on"}


def digest(html: str) -> str:
    """Short content hash. Identifies re-audits of one document, and joins an
    action row to the audit it followed. Reverses to nothing."""
    return hashlib.sha256(html.encode("utf-8")).hexdigest()[:12]


#: Kept for readability at the call site inside this module.
_digest = digest


def record(report: AuditReport, html: str, *, path: Path | None = None,
           source: str = "cli", session: str = "") -> dict | None:
    """Append one audit. Never raises - monitoring must not break an audit.

    Returns the row written, or None when monitoring is off or the write failed.
    """
    if not enabled():
        return None
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "audit",
        "doc": _digest(html),
        "session": session,
        "source": source,
        "verdict": report.verdict,
        "blocking": len(report.blocking_findings),
        "llm_status": report.llm_status,
        "codes": dict(Counter(f.code for f in report.findings)),
        "scored_findings": sum(1 for f in report.findings if f.scored),
        "stats": report.stats,
        "presend_ms": round(report.timing.presend_ms, 2),
        "llm_ms": round(report.timing.llm_ms, 2),
        "within_sla": report.timing.within_sla,
    }
    target = path or log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        # A full disk or a read-only home is not a reason to fail a pre-send
        # check. The creator's email matters; the telemetry does not.
        return None
    return row


def load(path: Path | None = None, limit: int | None = None) -> list[dict]:
    target = path or log_path()
    if not target.exists():
        return []
    rows = [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
    return rows[-limit:] if limit else rows


def summarize(rows: list[dict]) -> dict:
    """The finding mix and the shape of the traffic behind it.

    `share` is the fraction of *documents* a code appeared in, not the fraction
    of findings it accounts for. One email with forty contrast failures is one
    email with a contrast problem, and rating by raw count would let a single
    pathological document redefine the baseline.
    """
    if not rows:
        return {"documents": 0, "codes": {}, "verdicts": {}, "degraded": 0.0,
                "hold_rate": 0.0}
    n = len(rows)
    docs_with: Counter = Counter()
    for row in rows:
        for code in row.get("codes", {}):
            docs_with[code] += 1
    ok = {"ok", "replayed"}
    return {
        "documents": n,
        "unique_documents": len({r.get("doc") for r in rows}),
        "codes": {
            code: {"documents": c, "share": round(c / n, 4)}
            for code, c in docs_with.most_common()
        },
        "verdicts": {v: round(c / n, 4) for v, c in Counter(
            r.get("verdict", "?") for r in rows).most_common()},
        "hold_rate": round(sum(1 for r in rows if r.get("verdict") == "HOLD") / n, 4),
        "degraded": round(
            sum(1 for r in rows if r.get("llm_status") not in ok) / n, 4),
        "sla_breach_rate": round(
            sum(1 for r in rows if not r.get("within_sla", True)) / n, 4),
        "mean_presend_ms": round(
            sum(r.get("presend_ms", 0) for r in rows) / n, 2),
    }


def drift(rows: list[dict], window: int = 20) -> list[dict]:
    """Compare the newest `window` audits against everything before them.

    A finding-mix shift is the cheapest available signal that something moved -
    a check, a client, or the kind of mail arriving. It says look here; it does
    not say what broke.
    """
    if len(rows) < window * 2:
        return []
    recent, baseline = summarize(rows[-window:]), summarize(rows[:-window])
    out = []
    for code in set(recent["codes"]) | set(baseline["codes"]):
        now = recent["codes"].get(code, {}).get("share", 0.0)
        was = baseline["codes"].get(code, {}).get("share", 0.0)
        if abs(now - was) >= 0.20:      # 20 points of document share
            out.append({"code": code, "baseline_share": was,
                        "recent_share": now, "delta": round(now - was, 4)})
    return sorted(out, key=lambda d: abs(d["delta"]), reverse=True)


def record_action(action: str, *, doc: str, session: str = "",
                  verdict_at_audit: str = "", time_to_resolve_sec: float | None = None,
                  fixes_kept: int | None = None, fixes_undone: int | None = None,
                  reason: str = "", code: str = "",
                  decided_in_sec: float | None = None,
                  path: Path | None = None, source: str = "web") -> dict | None:
    """Append what the creator did. Same rules as `record`: opt-in, never raises.

    `doc` is the audit's document hash, so an action joins to the audit it
    followed without either row carrying content.
    """
    if not enabled():
        return None
    if action not in ACTIONS:
        return None
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "action",
        "doc": doc,
        "session": session,
        "source": source,
        "action": action,
        "verdict_at_audit": verdict_at_audit,
        "time_to_resolve_sec": time_to_resolve_sec,
        "fixes_kept": fixes_kept,
        "fixes_undone": fixes_undone,
        # Which rule, and why. An override with no rule attached says the tool
        # is wrong; an override with one says which check is.
        "code": code,
        "reason": reason,
        # How long from seeing this finding to deciding about it. A comprehension
        # measure, not a performance one: a correct finding that takes ninety
        # seconds to act on has still failed, because at that price creators
        # stop reading the panel.
        "decided_in_sec": decided_in_sec,
    }
    target = path or log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        return None
    return row


def _rate(numerator: int, denominator: int) -> float | None:
    """None, not zero, when there is nothing to divide.

    A 0% override rate computed from no sends is not a fact about the product.
    """
    return numerator / denominator if denominator else None


def behaviour(rows: list[dict]) -> dict:
    """The metrics that say whether creators believe the verdicts.

    Every rate ships with the `n` it was computed from. A rate without its
    denominator is how a four-send sample becomes a slide.
    """
    audits = [r for r in rows if r.get("kind", "audit") == "audit"]
    actions = [r for r in rows if r.get("kind") == "action"]
    by_action = Counter(a["action"] for a in actions)

    held = [a for a in actions if a.get("verdict_at_audit") == "HOLD"]
    overridden = sum(1 for a in held if a["action"] == "OVERRIDDEN")
    acted = sum(1 for a in held if a["action"] in ("AUTO_FIXED", "MANUALLY_EDITED"))

    ignored = sum(1 for a in actions if a["action"] == "IGNORED")
    shown = sum(1 for a in actions if a.get("code"))
    kept = sum(a.get("fixes_kept") or 0 for a in actions)
    undone = sum(a.get("fixes_undone") or 0 for a in actions)

    times = [a["time_to_resolve_sec"] for a in actions
             if isinstance(a.get("time_to_resolve_sec"), (int, float))]
    times.sort()

    return {
        "audits": len(audits),
        "resolved_sessions": len(actions),
        "actions": dict(by_action),
        "hold_outcomes": len(held),
        "override_rate": _rate(overridden, len(held)),
        "action_rate_on_hold": _rate(acted, len(held)),
        "fix_acceptance_rate": _rate(kept, kept + undone),
        # Shown, understood enough to skip, and left alone. The quietest of the
        # three signals and often the loudest thing a check is being told.
        "ignore_rate": _rate(ignored, shown),
        "findings_shown": shown,
        # Its own denominator. Every rate here is reported with the n it was
        # actually computed from - borrowing a different one is how a number
        # stops meaning what its label says.
        "fix_decisions": kept + undone,
        "median_time_to_resolve_sec": times[len(times) // 2] if times else None,
        # Audits that never reached a resolution. Not the same as abandonment -
        # a creator may simply not have finished yet.
        "unresolved_audits": max(0, len(audits) - len(actions)),
    }


def rule_health(rows: list[dict]) -> dict:
    """Per-check health. Delegates - it does not compute anything itself.

    This used to have its own arithmetic, and it disagreed with the loop about
    the one thing that matters: whether scrolling past a finding counts as a
    decision. It counted ignores, the loop did not, and on identical evidence
    one reported a 19% false-alarm rate and the other 45% - one silent, the
    other proposing a recalibration.

    A number a creator's behaviour is judged by, implemented twice, is a number
    that drifts. There is now one implementation and this is a view onto it.
    """
    from .evals.loop import read

    return {
        code: {
            "decisions": v.decisions,
            "shown": v.shown,
            "dismissed": v.dismissed,
            "false_alarms": v.false_alarms,
            "dismiss_rate": round((v.dismissed / v.decisions) if v.decisions else 0.0, 4),
            "false_alarm_rate": round(v.false_alarm_rate or 0.0, 4),
            "ignore_rate": round(v.ignore_rate or 0.0, 4),
            "needs_recalibration": bool(v.proposal()),
            "underpowered": v.underpowered,
        }
        for code, v in read(rows).items()
    }
