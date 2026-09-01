"""Module D (part 4) - benchmark run history.

A single run says where the agent is. It cannot say which direction it is
moving, which is the question that matters once you are changing checks. Every
`eval` run appends one line here; nothing is ever rewritten, so a regression
stays visible after it is fixed.

**Local and gitignored.** This is one machine's record, not a shared artifact -
a tracked file that every branch appends to conflicts on every merge, and the
history is worth more as something you actually keep than as something people
resolve. A number worth publishing goes in the run's own output or
docs/PRODUCT_DECISIONS.md, not here.

JSONL rather than a database: it is greppable, it is appendable, and a run is
recorded by a process that must never fail the benchmark it is recording.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_HISTORY_PATH = Path(__file__).parent / "history.jsonl"


def history_path() -> Path:
    """Overridable so a test run never appends to the repo's own history.

    A results log that fills up with rows from `pytest` stops being a record of
    what the agent scored and becomes noise.
    """
    return Path(os.getenv("PREFLIGHT_HISTORY_LOG", str(DEFAULT_HISTORY_PATH))).expanduser()


def record(result_dict: dict, *, provider: str, model: str,
           path: Path | None = None, note: str = "") -> dict:
    """Append one run. Returns the row written.

    Deliberately narrow: the headline numbers and the identity of what produced
    them. The full report stays in the run's own output - a history file that
    grows by a kilobyte per run stops being read.
    """
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "llm_mode": result_dict.get("llm_mode", ""),
        "note": note,
        "f1": result_dict.get("overall", {}).get("f1"),
        "precision": result_dict.get("overall", {}).get("precision"),
        "recall": result_dict.get("overall", {}).get("recall"),
        "modules": {
            name: {"f1": m.get("f1"), "fp": m.get("fp"), "fn": m.get("fn")}
            for name, m in result_dict.get("modules", {}).items()
        },
        "clean_control_fp": result_dict.get("clean_control_false_positives"),
        "verdict_accuracy": result_dict.get("verdict", {}).get("accuracy"),
        "fix_resolution_rate": result_dict.get("fix", {}).get("resolution_rate"),
        "control_violations": len(result_dict.get("control_violations", [])),
        "severity_drift": len(result_dict.get("severity_drift", [])),
        "llm_degradation_rate": result_dict.get("cost", {}).get("llm_degradation_rate"),
        "mean_latency_ms": result_dict.get("mean_latency_ms"),
        "sla_breaches": len(result_dict.get("sla_breaches", [])),
    }
    target = path or history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def load(path: Path | None = None, limit: int | None = None) -> list[dict]:
    target = path or history_path()
    if not target.exists():
        return []
    rows = [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
    return rows[-limit:] if limit else rows


def deltas(rows: list[dict], keys: tuple[str, ...] = ("f1", "verdict_accuracy",
                                                      "fix_resolution_rate")) -> dict:
    """Change between the last two runs, for the metrics worth alarming on.

    Returns an empty dict on a first run rather than inventing a baseline of
    zero - "F1 improved by 1.0" on run one is not information.
    """
    if len(rows) < 2:
        return {}
    prev, last = rows[-2], rows[-1]
    out: dict[str, dict] = {}
    for key in keys:
        a, b = prev.get(key), last.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out[key] = {"from": a, "to": b, "delta": round(b - a, 4)}
    return out
