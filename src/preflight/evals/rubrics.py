"""What a good finding looks like, per check — and what a bad one looks like.

A check can be perfectly accurate and still be wrong for the product. "This text
is 4.3:1" can be true, and firing it on a decorative caption nobody reads is
still a false alarm from where the creator sits. Precision against ground truth
cannot see that; only a definition of *useful* can.

So every check carries a rubric with three parts:

* **good** — the case this check exists to catch, stated as a creator would
  experience it.
* **bad** — the case where it is technically right and unhelpful. This is the
  half that usually goes unwritten, and it is the half that tells you what to
  fix when creators start waving a check through.
* **decides_in** — how long a creator should need to decide what to do about it.
  A finding that takes ninety seconds to act on has failed even if it was
  correct, because at that price they will stop reading.

The rubric is what makes creator feedback interpretable. Without it, a 40%
dismissal rate is a number. With it, you can ask which half of the definition
the check has drifted into.

Nothing here is scored automatically against a model. These are the standard a
human applies when a check gets flagged for recalibration, and the language the
proposal is written in.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Rubric:
    good: str
    bad: str
    #: Seconds a creator should need to decide. Comprehension budget, not a
    #: performance budget - it measures whether the wording landed.
    decides_in: int
    #: What we would change first if creators say this check is wrong.
    first_lever: str


#: The rubrics live in a spreadsheet, not in this file.
#:
#: A rubric is a product artefact - it defines what a good and a bad finding
#: look like for a creator - so the person who owns that definition should be
#: able to change it without opening Python or asking for a deploy. The CSV
#: opens directly in Sheets or Excel, and this module reads it. Editing the code
#: to change a rubric would put the definition back where nobody who needs it
#: can reach it.
RUBRIC_SHEET = Path(__file__).parent / "rubrics.csv"


def _load(path: Path = RUBRIC_SHEET) -> dict[str, Rubric]:
    """Read the rubric sheet. Loud on malformed rows, because a rubric that
    silently fails to load looks exactly like a check nobody has defined."""
    out: dict[str, Rubric] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):
            code = (row.get("check") or "").strip()
            if not code:
                continue
            try:
                decides_in = int((row.get("seconds to decide") or "").strip())
            except ValueError as exc:
                raise ValueError(
                    f"{path.name} row {i} ({code}): 'seconds to decide' must be a "
                    f"whole number of seconds"
                ) from exc
            out[code] = Rubric(
                good=(row.get("a good finding looks like") or "").strip(),
                bad=(row.get("a bad finding looks like") or "").strip(),
                decides_in=decides_in,
                first_lever=(row.get("first lever if creators say it is wrong") or "").strip(),
            )
    return out


RUBRICS: dict[str, Rubric] = _load()


def rubric_for(code: str) -> Rubric | None:
    return RUBRICS.get(code)


def missing_rubrics(codes: set[str]) -> set[str]:
    """Checks shipping without a definition of good and bad.

    A check nobody can describe the failure mode of cannot be recalibrated when
    creators start waving it through - there is nothing to compare the feedback
    against.
    """
    return {c for c in codes if c not in RUBRICS}
