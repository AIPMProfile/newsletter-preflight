"""Does the repair actually clear the send, and does it leave the layout alone?

The benchmark scores findings against a table someone wrote. This asks a
blunter question of real mail: if a creator hit the button, would the broadcast
be sendable afterwards, and would their layout survive it?

Two passes per document - audit, repair, audit again - and two thresholds:

* **Clearance.** More than 90% of documents must come back with nothing
  blocking. Note that this is *not* "reaches READY": READY means nothing was
  found at all, and the repair targets the readable floor rather than the ideal,
  so advisory notes legitimately survive. Holding the bar at READY would fail
  documents for something that is not a defect. The READY share is reported
  beside clearance, which is the honest way to show both.
* **Layout safety.** 100%, no exceptions. Every element in the same order, every
  personalisation tag byte-identical. A repair that rearranges someone's
  template has done more damage than the problem it solved.

  Measured against the document *as the parser returns it untouched*, not
  against the raw bytes. Reading a malformed page and writing it back already
  moves things - BeautifulSoup closes what was left open and supplies what was
  implied, so one real page gained an element with zero repairs applied.
  Comparing to raw input would blame the fixer for the parser's tidying and
  report damage that never happened.

  "Untouched" means **nothing removed and nothing reordered**, and every
  structural tag still present in the same number. It does not mean byte
  equality: wrapping a bare URL in an anchor adds an `<a>`, and that addition is
  the repair the creator asked for. A metric that failed on it would be
  measuring the wrong thing twice over.

The sample size is whatever is actually in `real/`. It is never padded to a
target, and the results file records the real N.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from ..audit import audit_html
from ..fixer.autofix import fix_document, liquid_tokens, serialize
from ..parser import load

REAL_DIR = Path(__file__).parent / "real"
RESULTS_PATH = Path(__file__).parent / "HARNESS_RESULTS.json"

#: Share of documents that must end with nothing blocking a send.
CLEARANCE_TARGET = 0.90

#: Layout safety is absolute. There is no acceptable rate of mangling.
LAYOUT_TARGET = 1.00

_ELEMENTS = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)[\s/>]")

#: Tags that carry the layout. If any of these move or change in number, the
#: template has been altered - and in email, table structure *is* the design.
STRUCTURAL = frozenset({"table", "thead", "tbody", "tr", "td", "th", "div",
                        "p", "h1", "h2", "h3", "h4", "h5", "h6", "img",
                        "ul", "ol", "li", "body", "head", "html"})


def element_sequence(html: str) -> list[str]:
    """Tag names in document order.

    Compared before and after a repair. Cheaper than a tree diff and catches the
    thing that matters: a table cell that moved, vanished, or was invented.
    """
    return _ELEMENTS.findall(html)


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """Every element of `needle`, in order, somewhere in `haystack`.

    This is the "nothing was removed or reordered" test. Additions are allowed
    to fall between them, which is how an anchor the fixer legitimately inserted
    passes while a deleted table cell does not.
    """
    it = iter(haystack)
    return all(tag in it for tag in needle)


def parsed_baseline(html: str) -> str:
    """The document after a read/write cycle with nothing repaired.

    This is the fair comparison point. Anything that differs between this and
    the repaired document was done by a fixer; anything that differs between
    this and the raw input was done by the parser, and is not a defect.
    """
    soup, _ = load(html)
    return serialize(soup, html)


async def check_one(name: str, html: str, check_links: bool) -> dict:
    before = await audit_html(html, path=name,
                              offline_links=None if check_links else {}, skip_llm=True)
    fixed, applied, after = await fix_document(
        html, offline_links=None if check_links else {})

    baseline = parsed_baseline(html)
    base_seq, fixed_seq = element_sequence(baseline), element_sequence(fixed)
    base_struct = Counter(t for t in base_seq if t in STRUCTURAL)
    fixed_struct = Counter(t for t in fixed_seq if t in STRUCTURAL)

    nothing_lost = _is_subsequence(base_seq, fixed_seq)
    structure_held = base_struct == fixed_struct
    layout_safe = nothing_lost and structure_held
    parser_normalised = base_seq != element_sequence(html)
    liquid_safe = liquid_tokens(fixed) == liquid_tokens(html)

    return {
        "file": name,
        "verdict_before": before.verdict,
        "verdict_after": after.verdict,
        "blocking_before": len(before.blocking_findings),
        "blocking_after": len(after.blocking_findings),
        "cleared": not after.blocking_findings,
        "ready": not after.findings,
        "fixes_applied": len(applied),
        "layout_safe": layout_safe,
        "nothing_removed": nothing_lost,
        "structure_held": structure_held,
        "elements_added": len(fixed_seq) - len(base_seq),
        # Recorded, not counted against anything: it says the source was
        # malformed enough that reading it tidied it, which is worth knowing
        # about the corpus and says nothing about the repair.
        "parser_normalised_source": parser_normalised,
        "liquid_safe": liquid_safe,
        "safe": layout_safe and liquid_safe,
        "codes_before": sorted({f.code for f in before.findings}),
        "codes_remaining": sorted({f.code for f in after.findings}),
    }


async def run(corpus_dir: Path = REAL_DIR, check_links: bool = False) -> dict:
    files = sorted(p for p in corpus_dir.glob("*.html"))
    rows = [await check_one(p.name, p.read_text(), check_links) for p in files]
    n = len(rows)

    def share(pred) -> float | None:
        # None, not zero, on an empty corpus. "0% clearance" would read as a
        # failing product rather than an absent measurement.
        return sum(1 for r in rows if pred(r)) / n if n else None

    clearance = share(lambda r: r["cleared"])
    layout = share(lambda r: r["safe"])
    had_blocking = [r for r in rows if r["blocking_before"]]

    return {
        "generated": date.today().isoformat(),
        "documents": n,
        "note": ("Sample size is whatever `real/` holds. It is never padded to a "
                 "target, and no threshold is judged against an assumed N."),
        "clearance_rate": None if clearance is None else round(clearance, 4),
        "clearance_target": CLEARANCE_TARGET,
        "ready_rate": share(lambda r: r["ready"]),
        "layout_safe_rate": None if layout is None else round(layout, 4),
        "layout_target": LAYOUT_TARGET,
        "sources_normalised_by_parser": sum(
            1 for r in rows if r["parser_normalised_source"]),
        "documents_needing_repair": len(had_blocking),
        "repaired_of_those": (
            round(sum(1 for r in had_blocking if r["cleared"]) / len(had_blocking), 4)
            if had_blocking else None),
        "passes": bool(n) and clearance >= CLEARANCE_TARGET and layout >= LAYOUT_TARGET,
        "unsafe": [r["file"] for r in rows if not r["safe"]],
        "uncleared": [r["file"] for r in rows if not r["cleared"]],
        "cases": rows,
    }


def run_sync(corpus_dir: Path = REAL_DIR, check_links: bool = False) -> dict:
    return asyncio.run(run(corpus_dir, check_links))


def write(results: dict, path: Path = RESULTS_PATH) -> Path:
    path.write_text(json.dumps(results, indent=2) + "\n")
    return path
